import argparse
import json
import os
import re


parser = argparse.ArgumentParser(description="Extract generated Prolog blocks to .pl files.")
parser.add_argument("--llm-output", type=str, required=True, help="Path to the LLM output JSON file.")
parser.add_argument("--save-dir", type=str, required=True, help="Directory to save processed Prolog files.")
parser.add_argument("--logprobs", action="store_true", default=False, help="Unused compatibility flag.")
parser.add_argument("--standalone", action="store_true", default=False, help="Unused compatibility flag.")
parser.add_argument(
    "--dataset",
    type=str,
    required=True,
    choices=["sara_numeric", "sara_binary", "airline", "housing", "uscis"],
    help="Dataset name used for output file naming and label injection.",
)
args = parser.parse_args()

LLM_OUTPUT_FILE = args.llm_output
SAVE_DIR = args.save_dir

CASE_PREFIXES = {
    "sara_numeric": "tax_case",
    "sara_binary": "sara_binary_case",
    "airline": "airline_case",
    "housing": "housing_case",
    "uscis": "uscis_case",
}
case_prefix = CASE_PREFIXES[args.dataset]

with open(LLM_OUTPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)


# ---------------------------------------------------------------------------
# Label helpers – inject a :- format(...) directive at the top of each .pl
# file so that the swipl runner also prints the gold label for reference.
# ---------------------------------------------------------------------------

def _resolve_housing_label(datum: dict) -> str:
    gold = datum.get("gold_answer", "")
    if isinstance(gold, str) and gold.strip().lower() in ("yes", "no"):
        return gold.strip().lower()
    label = datum.get("label")
    if label == 1:
        return "yes"
    if label == -1:
        return "no"
    return ""


def _resolve_uscis_label(datum: dict) -> str:
    gold = datum.get("gold_answer", "")
    if isinstance(gold, str) and gold.strip().lower() in ("accepted", "dismissed"):
        return gold.strip().capitalize()
    label = datum.get("label")
    if label == 1:
        return "Accepted"
    if label == -1:
        return "Dismissed"
    return ""


def _make_label_directive(dataset: str, datum: dict) -> str:
    """Return a Prolog directive that prints the gold label, or '' if N/A."""
    if dataset == "housing":
        lbl = _resolve_housing_label(datum)
    elif dataset == "uscis":
        lbl = _resolve_uscis_label(datum)
    else:
        return ""
    if not lbl:
        return ""
    return f':- format("Label: ~w~n", ["{lbl}"]).\n'


INITIALIZATION_RE = re.compile(
    r":-\s*initialization\s*\(\s*main\s*,\s*main\s*\)\s*\.",
    flags=re.IGNORECASE,
)
MAIN_DEF_RE = re.compile(r"(^|\n)\s*main\s*(?::-|-->|\\.)", flags=re.IGNORECASE)


def extract_prolog_block(answer: object) -> str:
    if not isinstance(answer, str):
        return ""
    text = answer.strip()
    if not text:
        return ""

    match = re.search(r"```prolog\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        block = match.group(1).strip()
        if block:
            return block

    match = re.search(r"```(?:\w+)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        block = match.group(1).strip()
        if block:
            return block

    return text


def requires_explicit_main_entrypoint(dataset: str) -> bool:
    return dataset in {"housing", "uscis"}


def has_required_main_entrypoint(prolog: str) -> bool:
    if not isinstance(prolog, str):
        return False
    return bool(INITIALIZATION_RE.search(prolog) and MAIN_DEF_RE.search(prolog))


def _repair_missing_entrypoint(prolog: str, dataset: str) -> str:
    """Append missing main/0 and/or :- initialization(main, main). to a Prolog block."""
    has_init = bool(INITIALIZATION_RE.search(prolog))
    has_main = bool(MAIN_DEF_RE.search(prolog))
    additions = []
    if not has_main:
        if dataset == "uscis":
            additions.append(
                "main :-\n"
                "    decision(Result),\n"
                "    writeln(Result).\n"
            )
        elif dataset == "housing":
            additions.append(
                "main :-\n"
                "    housing_answer(Result),\n"
                "    format('housing_answer(~w).~n', [Result]).\n"
            )
    if not has_init:
        additions.append(":- initialization(main, main).\n")
    return prolog.rstrip() + "\n\n" + "".join(additions)


prologs = [
    [extract_prolog_block(answer) for answer in datum.get("answers", [])]
    for datum in data
]

print(len(prologs))
os.makedirs(SAVE_DIR, exist_ok=True)
total_extracts = 0
empty_extracts = 0
invalid_entrypoints = 0
for i, case_prologs in enumerate(prologs):
    for j, prolog in enumerate(case_prologs):
        total_extracts += 1
        if not isinstance(prolog, str) or not prolog.strip():
            empty_extracts += 1
            per_attempt_error = ""
            generation_errors = data[i].get("generation_errors", []) if isinstance(data[i], dict) else []
            if isinstance(generation_errors, list):
                if j < len(generation_errors) and generation_errors[j]:
                    per_attempt_error = str(generation_errors[j]).replace("\n", " ").strip()
                elif generation_errors and generation_errors[0]:
                    per_attempt_error = str(generation_errors[0]).replace("\n", " ").strip()
            prolog = (
                f"% EMPTY_PROLOG_EXTRACT dataset={args.dataset} case_index={i + 1} attempt={j}\n"
                f"% generation_error={per_attempt_error or 'n/a'}\n"
            )
        elif requires_explicit_main_entrypoint(args.dataset) and not has_required_main_entrypoint(prolog):
            invalid_entrypoints += 1
            prolog = _repair_missing_entrypoint(prolog, args.dataset)

        label_directive = _make_label_directive(args.dataset, data[i])
        with open(os.path.join(SAVE_DIR, f"{case_prefix}_{i + 1}_{j}.pl"), "w", encoding="utf-8") as f:
            if label_directive:
                f.write(label_directive)
            f.write(prolog)

print(
    "Processed generations: "
    f"{total_extracts}; empty extracted blocks: {empty_extracts}; "
    f"repaired entrypoints: {invalid_entrypoints}"
)
if total_extracts > 0 and empty_extracts == total_extracts:
    raise SystemExit(
        "All extracted Prolog blocks are empty. "
        "Failing early to avoid label-only artifacts and misleading abstain metrics."
    )
