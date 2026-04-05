import re
import os
from tenacity import retry, stop_after_attempt, wait_random_exponential # for exponential backoff

@retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
def chat_completion_with_backoff(client, **kwargs):
    return client.chat.completions.create(**kwargs)



def mask_test(test: str):
    """
    Convert a test string of the form ':- tax("Alice",2019,3219).\n:- halt.'
    to ':- tax("Alice",2019,Res), format('Tax result: ~w~n', [Res]).\n:- halt.'
    """
    test = test.strip()
    # Match the pattern :- tax(args..., result). :- halt.
    m = re.match(r':-\s*tax\((.*),\s*([^\),]+)\)\.\s*:-\s*halt\.', test, re.I)
    if m:
        args = m.group(1)
        return f":- tax({args},Res), format('Tax result: ~w~n', [Res]).\n:- halt."
    raise ValueError("Test format not recognized.")

    
def sorted_alphanumeric(data):
    convert = lambda text: int(text) if text.isdigit() else text.lower()
    alphanum_key = lambda key: [ convert(c) for c in re.split('([0-9]+)', key) ] 
    return sorted(data, key=alphanum_key)

def parse_case(case_str: str) -> dict:
    """
    Parse a case file formatted with % Text / % Question / % Facts / % Test blocks.

    Returns a dict with keys: text, question, answer, facts, test.
    """
    # Split the big string into its four labelled blocks
    m = re.search(
        r'%\s*Text(.*?)%\s*Question(.*?)%\s*Facts(.*?)%\s*Test(.*)',
        case_str,
        flags=re.S | re.I,
    )
    if not m:
        raise ValueError('Input does not match expected format.')

    raw_text, raw_q, raw_facts, raw_test = [s.strip() for s in m.groups()]

    # Strip the leading '%' markers from each block
    strip_pct = lambda s: re.sub(r'^\s*%[ \t]?', '', s, flags=re.M).strip()

    text  = strip_pct(raw_text)
    qline = strip_pct(raw_q)          # single-line question
    facts = strip_pct(raw_facts)
    test  = strip_pct(raw_test)

    # Extract the trailing dollar number (answer) from the question
    ans_match = re.search(r'\$\s*([\d,]+(?:\.\d+)?)\s*$', qline)
    if not ans_match:
        raise ValueError('Answer not found in question line.')

    label = int(ans_match.group(1).replace(',', ''))
    question = qline[: ans_match.start()].rstrip()  # question without the answer

    return {
        "text": text,
        "question": question,
        "label": label,
        "facts": facts,
        "test": test,
    }

def load_tax_cases(cases_dir: str):
    tax_cases = []

    for fname in sorted_alphanumeric(os.listdir(cases_dir)):
        if fname.startswith("tax") or fname.startswith("airline"):
            with open(os.path.join(cases_dir, fname), "r", encoding="utf-8") as f:
                tax_cases.append((fname, f.read()))

    parsed_tax_cases = [{**parse_case(tax_case), "fname": fname} for fname, tax_case in tax_cases]
    return parsed_tax_cases



def assemble_exemplars(tax_cases, indices):
    """
    Return a multi-example prompt formatted like EXEMPLARS_V2.

    Parameters
    ----------
    tax_cases : list[dict]
        Each dict needs at least: 'text', 'question', 'facts', 'test'.
    indices : Iterable[int]
        Zero-based indices of the cases to include (order preserved).

    Returns
    -------
    str
        The assembled prompt string.
    """
    prompt_chunks = []
    for ex_no, idx in enumerate(indices, start=1):
        case = tax_cases[idx]

        # Prefix every line of the narrative text with '% '
        text_block = "% " + "\n% ".join(case["text"].splitlines())

        exemplar = [
            f"Example {ex_no}:\n",
            "% Text",
            text_block,
            "\n% Question",
            f"% {case['question']}\n",
            "% Facts",
            case["facts"].rstrip(),
            "\n\n% Test",
            mask_test(case["test"].rstrip()),  # assumes mask_test is available
            "\n\n=============\n",
        ]
        prompt_chunks.append("\n".join(exemplar))

    return "\n".join(prompt_chunks)

def top_k_from_parsed(parsed_ranking, k):
    return [x for xs in parsed_ranking for x in xs][:k]
