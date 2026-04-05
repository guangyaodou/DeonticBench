#!/usr/bin/env python3
import argparse
import inspect
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import yaml
from openai import OpenAI
from tqdm import tqdm

# Ensure repository root (which contains utils.py and prompts/) is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Load model configuration from model_config.yaml
_model_config_path = Path(REPO_ROOT) / "model_config.yaml"
with open(_model_config_path) as _f:
    _model_config = yaml.safe_load(_f)

from prompts.case_exemplars import (
    EXEMPLARS_V2,
    EXEMPLARS_V3,
    EXEMPLARS_V4,
    EXAMPLE_AIRLINE,
    EXAMPLE_AIRLINE_1_ONLY,
    EXAMPLE_AIRLINE_2_ONLY,
    EXEMPLAR_SARA_V1,
    DISCARDED_SARA_EXAMPLE,
    EXEMPLAR_SARA_BINARY,
    EXAMPLE_LEGAL_IR_ONE_SHOT,
    EXAMPLE_LEGAL_IR_TWO_SHOT,
    EXAMPLE_USCIS_ONE_SHOT,
)
from prompts.dataset_prompts import (
    compose_prompt_prolog_legal_ir,
    compose_prompt_prolog_uscis,
    compose_prompt_source_legal_ir,
    compose_prompt_source_uscis,
    compose_prompt_standalone_prolog_legal_ir,
    compose_prompt_standalone_prolog_uscis,
)
from label_utils import normalize_legal_ir_label as _norm_legal_ir_label
from label_utils import normalize_uscis_label as _norm_uscis_label
from utils import chat_completion_with_backoff

model_arg_dict: Dict[str, Dict] = _model_config.get("model_params", {}) or {}

logprob_free_models = {
    "o4-mini-2025-04-16",
    "o3-2025-04-16",
    "gpt-5-2025-08-07",
    "gpt-5-chat-latest",
    "deepseek-reasoner",
    "gemini-2.5-pro-preview-06-05",
}

reasoning_models: set = set(_model_config.get("reasoning_models", []))

max_n_1_models = {
    "deepseek-chat",
    "openai/gpt-oss-120b",
}

deepseek_models = {
    "deepseek-chat",
    "deepseek-ai/DeepSeek-R1-0528-tput",
}

gpt4_models = {
    "gpt-4.1",
    "gpt-4.1-2025-04-14",
}

gpt5_models = {
    "gpt-5-2025-08-07",
    "gpt-5.1-2025-11-13",
    "gpt-5.1",
    "gpt-5.2",
}

codex_models = {
    "gpt-5.2-codex",
}

anthropic_models = {
    "claude-sonnet-4-20250514",
}

CABIN_CLASSES = ['Main Cabin', 'Business Class', 'First Class', 'Premium Economy', 'Basic Economy', 'Main Plus']
FALLBACK_CABIN = 'Business Class'


def sorted_alphanumeric(data: List[str]) -> List[str]:
    convert = lambda text: int(text) if text.isdigit() else text.lower()
    alphanum_key = lambda key: [convert(c) for c in re.split("([0-9]+)", key)]
    return sorted(data, key=alphanum_key)


def extract_cabin_class(text: str):
    for cabin in CABIN_CLASSES:
        if cabin in text:
            return cabin
    return None


def load_airline_exemplar_pool(pool_path: str) -> dict:
    """Load O3 correct Prolog pool and index by cabin class.

    Supports two entry formats:
      - Old format: {'text': ..., 'question': ..., 'correct_prolog_generation': ...}
      - New format: {'instruction': ..., 'input': ..., 'output': ...}
        where case text lives after '## Case:' and question after '## Question:'
        in the 'instruction' field.
      - DeonticBench format: {'id': ..., 'text': ..., 'question': ..., 'reference_prolog': ...}
    Entries are normalised to always have 'text', 'question', and
    'correct_prolog_generation' keys so downstream functions need no changes.
    """
    with open(pool_path) as f:
        pool = json.load(f)
    by_class = {}
    for entry in pool:
        if 'text' not in entry and 'instruction' in entry:
            # New format: extract case text and question from instruction
            instruction = entry['instruction']
            m_case = re.search(r'## Case:\s*(.*?)\s*## Question:', instruction, re.DOTALL)
            m_question = re.search(r'## Question:\s*(.*?)\s*(?:The question|$)', instruction, re.DOTALL)
            entry = dict(entry)  # don't mutate original
            entry['text'] = m_case.group(1).strip() if m_case else ''
            entry['question'] = m_question.group(1).strip() if m_question else ''
            entry['correct_prolog_generation'] = entry.get('output', '')
        else:
            entry = dict(entry)  # don't mutate original
        # Support DeonticBench format: use reference_prolog as fallback
        entry['correct_prolog_generation'] = entry.get('correct_prolog_generation') or entry.get('reference_prolog', '')
        cabin = extract_cabin_class(entry['text'])
        by_class.setdefault(cabin, []).append(entry)
    return by_class


def format_airline_exemplar(entry: dict) -> str:
    """Format a pool entry as a few-shot exemplar string."""
    gen = entry['correct_prolog_generation']
    # Strip the evaluation-injected Label directive on the first line
    lines = gen.split('\n')
    if lines and lines[0].startswith(':- format(') and '"Label:' in lines[0]:
        gen = '\n'.join(lines[1:]).lstrip('\n')
    # Strip existing ```prolog ... ``` fences if already present (new-format pool entries)
    gen = gen.strip()
    if gen.startswith('```prolog'):
        gen = re.sub(r'^```prolog\s*', '', gen)
        gen = re.sub(r'\s*```$', '', gen)
    return (
        f"% Text\n% {entry['text']}\n\n"
        f"% Question\n%  {entry['question']}\n\n"
        f"```prolog\n{gen.strip()}\n```"
    )


def retrieve_airline_exemplar(pool_by_class: dict, test_text: str) -> str:
    """Return the first correct exemplar matching the test case's cabin class (leave-one-out)."""
    cabin = extract_cabin_class(test_text)
    candidates = pool_by_class.get(cabin) or pool_by_class.get(FALLBACK_CABIN, [])
    # Exclude the test case itself
    candidates = [e for e in candidates if e['text'] != test_text]
    if not candidates:
        # Fallback: any entry from the full pool
        candidates = [e for entries in pool_by_class.values() for e in entries if e['text'] != test_text]
    return format_airline_exemplar(candidates[0])


@dataclass
class Config:
    statutes_path: Optional[str]
    cases_path: str
    model_name: str
    api_base_url: str
    api_key: str
    output_path: str
    token_budget: int
    debug: bool
    num_generations: int
    temperature: float
    ranking_file: Optional[str]
    num_exemplars: int
    task: str
    reasoning_effort: str
    airline_exemplar_pool: Optional[str]
    dataset: str
    split: str


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Process legal reasoning cases using LLM inference")
    parser.add_argument("--statutes-path", required=False, default=None,
                        help="Path to statutes directory (required for sara_numeric, sara_binary, airline)")
    parser.add_argument("--cases-path", required=True, help="Path to DeonticBench JSON file")
    parser.add_argument("--model-name", default="deepseek-ai/DeepSeek-R1-Distill-Qwen-32B", help="Name of the model to use")
    parser.add_argument("--api-base-url", default="http://localhost:9009/v1", help="Base URL for the API")
    parser.add_argument("--api-key", default="token-abc123", help="API key for authentication")
    parser.add_argument("--output-path", default="out/output.json", help="Path to save output JSON")
    parser.add_argument("--token-budget", type=int, default=10000, help="Token budget for model inference")
    parser.add_argument("--debug", default=False, action="store_true", help="Only run on one example")
    parser.add_argument("--num-generations", type=int, default=2, help="Number of generations to sample")
    parser.add_argument("--temperature", type=float, default=0.7, help="Temperature to sample at")
    parser.add_argument("--ranking-file", type=str, default=None, help="Optional ranking file (unused in current flow)")
    parser.add_argument(
        "--num-exemplars",
        type=int,
        default=None,
        help="Number of exemplars to provide (default: 1 for housing/uscis, else 2).",
    )
    parser.add_argument("--task", type=str, default="direct", choices=["direct", "prolog", "standalone"], help="Task mode")
    parser.add_argument("--reasoning-effort", type=str, default="medium", choices=["none", "low", "medium", "high"], help="Reasoning effort level for reasoning models (default: medium)")
    parser.add_argument("--airline-exemplar-pool", type=str, default=None,
                        help="Path to JSON file of correct Prolog programs used for cabin-class retrieval few-shot "
                             "selection in airline prolog tasks. Defaults to cases-path (leave-one-out from the "
                             "cases JSON itself).")
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        choices=["sara_numeric", "sara_binary", "airline", "housing", "uscis"],
        help="Dataset to run.",
    )
    parser.add_argument(
        "--split",
        type=str,
        default="hard",
        help="Split name (e.g. 'hard', 'whole'). Informational only, does not affect case loading.",
    )

    args = parser.parse_args()
    dataset = args.dataset

    # Validate statutes_path requirement
    if dataset in {"sara_numeric", "sara_binary", "airline"} and args.statutes_path is None:
        parser.error(f"--statutes-path is required for dataset '{dataset}'")

    num_exemplars = args.num_exemplars
    if num_exemplars is None:
        num_exemplars = 1 if dataset in {"housing", "uscis"} else 2

    return Config(
        statutes_path=args.statutes_path,
        cases_path=args.cases_path,
        model_name=args.model_name,
        api_base_url=args.api_base_url,
        api_key=args.api_key,
        output_path=args.output_path,
        token_budget=args.token_budget,
        debug=args.debug,
        num_generations=args.num_generations,
        temperature=args.temperature,
        ranking_file=args.ranking_file,
        num_exemplars=num_exemplars,
        task=args.task,
        reasoning_effort=args.reasoning_effort,
        airline_exemplar_pool=args.airline_exemplar_pool,
        dataset=dataset,
        split=args.split,
    )


def load_statutes(statutes_path: str, events_only: bool = False) -> str:
    """Load and combine all statute files from the given directory."""
    file_texts: List[str] = []
    try:
        for filename in os.listdir(statutes_path):
            if events_only and filename != "events.pl":
                continue
            file_path = os.path.join(statutes_path, filename)
            if os.path.isfile(file_path):
                with open(file_path, "r", encoding="utf-8") as file:
                    file_texts.append(file.read())
        return "\n\n\n\n".join(file_texts)
    except Exception as exc:
        raise RuntimeError(f"Error loading statutes: {exc}") from exc


def load_cases_from_json(cases_path: str, dataset: str) -> List[Dict]:
    """Load DeonticBench JSON and return cases in the internal dict format.

    Each JSON entry has: id, text, question, label, reference_prolog, plus
    optionally state (housing) and statutes (housing/uscis).

    Returns cases formatted for use by prompt composers and run_inference().
    """
    with open(cases_path, "r", encoding="utf-8") as f:
        raw_cases = json.load(f)

    cases: List[Dict] = []
    for item in raw_cases:
        item_id = item.get("id", len(cases))

        if dataset == "sara_numeric":
            cases.append({
                "id": item_id,
                "text": str(item.get("text", "")),
                "question": str(item.get("question", "")),
                "label": int(item["label"]),
            })

        elif dataset == "sara_binary":
            cases.append({
                "id": item_id,
                "text": str(item.get("text", "")),
                "question": str(item.get("question", "")),
                "label": int(item["label"]),
            })

        elif dataset == "airline":
            cases.append({
                "id": item_id,
                "text": str(item.get("text", "")),
                "question": str(item.get("question", "")),
                "label": int(item["label"]),
                "reference_prolog": str(item.get("reference_prolog", "")),
            })

        elif dataset == "housing":
            statutes_raw = item.get("statutes", "")
            statutes_text = statutes_raw if isinstance(statutes_raw, str) else ""
            cases.append({
                "id": item_id,
                "state": item.get("state", ""),
                "question": str(item.get("question", "")),
                "statutes_text": statutes_text,
                "label": _norm_legal_ir_label(item.get("label")),
            })

        elif dataset == "uscis":
            text = str(item.get("text", ""))
            statutes_raw = item.get("statutes", "")
            statutes = statutes_raw if isinstance(statutes_raw, str) else ""
            instruction = f"You are given the following facts:\n{text}\n\nYou are given the following rules:\n{statutes}"
            cases.append({
                "id": item_id,
                "text": text,
                "statutes_text": statutes,
                "instruction": instruction,
                "question": str(item.get("question", "")),
                "label": _norm_uscis_label(item.get("label")),
            })

        else:
            raise ValueError(f"Unknown dataset: {dataset}")

    return cases


def _normalize_legal_ir_label(value) -> Optional[int]:
    return _norm_legal_ir_label(value)


def _normalize_uscis_label(value) -> Optional[int]:
    return _norm_uscis_label(value)


def compose_prompt_source(statutes: str, case: Dict) -> str:
    return (
        f"Statutes:\n{statutes}\n\n"
        f"Case: {case['text']}\n\n"
        f"Question: {case['question']}\n\n"
        "Answer the question based on the case and statutes above. "
        "Your answer should be a dollar figure. "
        "Indicate your answer using \\boxed{}"
        " Think step-by-step before answering."
    )


def compose_prompt_source_binary(statutes: str, case: Dict) -> str:
    """Create a formatted prompt for binary (entailment/contradiction) direct solving."""
    return (f"Statutes:\n{statutes}\n\n"
            f"Case: {case['text']}\n\n"
            f"Claim: {case['question']}\n\n"
            "The claim above makes a statement about the case in relation to the statutes. "
            "Determine whether the claim is correct (Entailment) or incorrect (Contradiction) "
            "based on the case and statutes above. "
            "Your answer should be exactly one of: Entailment or Contradiction. "
            "Indicate your answer using \\boxed{}"
            " Think step-by-step before answering.")

def compose_prompt_standalone_prolog_sara(statutes: str, case: Dict) -> str:
    return (
        f"## Statutes:\n{statutes}\n\n"
        f"## Case: {case['text']}\n\n"
        f"## Question: {case['question']}\n\n"
        "The question above asks about the case in relation to the statutes. "
        "First, write a logic program in prolog to encode the relevant rules defined in the statutes. "
        "Then write a logic program in prolog to encode the facts and rules contained in the case above. "
        "Then write a query to compute and print the value the question asks.\n"
        "You must indicate your prolog code using:\n```prolog\n<YOUR_LOGIC_PROGRAM_HERE>\n```\n"
        "For instance, to answer \"How much tax does Samuel owe in 1992\", your final lines should be "
        "```prolog:- tax(\"Samuel\", 1992, Tax), format('Tax result: ~w~n', [Tax]).\n:- halt.```"
    )


def compose_prompt_standalone_prolog_binary(statutes: str, case: Dict) -> str:
    """Create a formatted prompt for binary (entailment/contradiction) Prolog generation."""
    return (f"## Statutes:\n{statutes}\n\n"
            f"## Case: {case['text']}\n\n"
            f"## Claim: {case['question']}\n\n"
            "The claim above makes a statement about the case in relation to the statutes. "
            "Determine whether the claim is correct (Entailment) or incorrect (Contradiction).\n\n"
            "First, write a logic program in Prolog to encode the relevant rules defined in the statutes. "
            "Then write a logic program in Prolog to encode the facts contained in the case above. "
            "Then write a query that checks whether the claim holds, and prints the result.\n"
            " You must indicate your prolog code using:\n```prolog\n<YOUR_LOGIC_PROGRAM_HERE>\n```\n"
            " Your program's final output must be exactly one of:\n"
            "   Result: Entailment\n"
            "   Result: Contradiction\n\n"
            " For example, your final lines should follow this pattern:\n"
            "```prolog\n"
            ":- (  <your_verification_goal>\n"
            "   -> format('Result: Entailment~n')\n"
            "   ;  format('Result: Contradiction~n')\n"
            "   ).\n"
            ":- halt.\n"
            "```\n"
            " Follow this format exactly. Think step-by-step before answering.")

def compose_prompt_prolog_binary(statutes: str, case: Dict, exemplars=EXEMPLAR_SARA_BINARY) -> str:
    """Create a formatted prompt for binary (entailment/contradiction) Prolog generation with few-shot examples."""
    return (f"## Statutes:\n{statutes}\n\n"
            "Here are example prolog programs to follow:\n\n"
            f"Examples:\n{exemplars}\n\n"
            "Based on the examples above, write a prolog program for the case and claim below.\n\n"
            f"## Case: {case['text']}\n\n"
            f"## Claim: {case['question']}\n\n"
            "The claim above makes a statement about the case in relation to the statutes. "
            "Determine whether the claim is correct (Entailment) or incorrect (Contradiction).\n\n"
            "First, write a logic program in Prolog to encode the relevant rules defined in the statutes. "
            "Then write a logic program in Prolog to encode the facts contained in the case above. "
            "Then write a query that checks whether the claim holds, and prints the result.\n"
            " You must indicate your prolog code using:\n```prolog\n<YOUR_LOGIC_PROGRAM_HERE>\n```\n"
            " Your program's final output must be exactly one of:\n"
            "   Result: Entailment\n"
            "   Result: Contradiction\n\n"
            " For example, your final lines should follow this pattern:\n"
            "```prolog\n"
            ":- (  <your_verification_goal>\n"
            "   -> format('Result: Entailment~n')\n"
            "   ;  format('Result: Contradiction~n')\n"
            "   ).\n"
            ":- halt.\n"
            "```\n"
            " Follow the examples' format exactly. Think step-by-step before answering.")

def compose_prompt_standalone_prolog_airline(statutes: str, case: Dict) -> str:
    return (
        f"## Statutes:\n{statutes}\n\n"
        f"## Case: {case['text']}\n\n"
        f"## Question: {case['question']}\n\n"
        "Write a complete runnable SWI-Prolog program that computes the answer. "
        "Indicate your prolog code using:\n```prolog\n<YOUR_LOGIC_PROGRAM_HERE>\n```\n"
        "Final lines should print total result and halt."
    )

# def compose_prompt_prolog_sara(statutes: str, case: Dict, exemplars=EXEMPLAR_SARA_V1) -> str:
def compose_prompt_prolog_sara(statutes: str, case: Dict, exemplars=DISCARDED_SARA_EXAMPLE + EXEMPLAR_SARA_V1) -> str:
    """Create a formatted prompt for the model (Sara Prolog)."""
    return (f"## Statutes:\n{statutes}\n\n"
        "Here are example prolog program formats to follow:\n\n"
        f"Examples:\n{exemplars}\n\n"
        "Based on the examples above, write a prolog program for the case and question below.\n\n"
        f"## Case: {case['text']}\n\n"
        f"## Question: {case['question']}\n\n"
        "The question above asks about the case in relation to the statutes. "
        "First, write a logic program in prolog to encode the relevant rules defined in the statutes. "
        "Then write a logic program in prolog to encode the facts and rules contained in the case above. "
        "Then write a query to compute and print the value the question asks.\n"
        " You must indicate your prolog code using:\n```prolog\n<YOUR_LOGIC_PROGRAM_HERE>\n```\n"
        """ For instance, to answer "How much tax does Samuel owe in 1992", your final lines should be ```prolog:- tax("Samuel", 1992, Tax), format('Tax result: ~w~n', [Tax]).\n:- halt.```"""
        " Follow this format exactly. You will only receive credit if the code you write within this block computes the exact correct tax value."
        " Think step-by-step before answering.")


def compose_prompt_prolog_airline(statutes: str, case: Dict, exemplars: str = None) -> str:
    """Create a formatted prompt for the model."""
    # Use per-case retrieved exemplar if available (set by main() via --airline-exemplar-pool),
    # otherwise fall back to the fixed EXAMPLE_AIRLINE_2_ONLY.
    if exemplars is None:
        exemplars = case.get('exemplar', EXAMPLE_AIRLINE_2_ONLY)
    return (f"Statutory Terms:\n{statutes}\n\n"
            f"Examples:\n{exemplars}\n\n"
            f"% Text\n% {case['text']}\n\n"
            f"% Question\n%  {case['question']}\n\n"
            "Write a prolog program that will compute the tax burden for the described case. "
            "Follow the examples given above. Your answer should be a prolog program."
            " These programs follow a neo-Davidsonian structure, with predicates for events defined as descriptive phrases while predicates for individuals are names"
            " Indicate your prolog code using:\n```prolog\n<YOUR_LOGIC_PROGRAM_HERE>\n```\n"
             """ For instance, to answer "how much does Sarah pay for her luggage",
            your final lines should be
            ```prolog
            :- total_cost(Total), format('Total cost: ~w~n', [Total]).
            :- halt."""
            " Copy the example format exactly. If your output does not execute in accordance with the statutes above, you will receive no credit for accurately parsing the cases."
            " Think step-by-step before answering.")


@dataclass
class Logprob:
    token: str
    logprob: float


def process_chat_logprobs(choice):
    if choice.logprobs.content is None:
        choice.logprobs.content = [
            Logprob(token=token, logprob=logprob)
            for token, logprob in zip(choice.logprobs.tokens, choice.logprobs.token_logprobs)
        ]
    return [{"token": x.token, "logprob": x.logprob} for x in choice.logprobs.content]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _invoke_chat_with_fallback(request_args: Dict, debug: bool = False):
    """Run chat.completions with one compatibility fallback for provider-specific arg rejection."""
    try:
        if debug:
            req = dict(request_args)
            req.pop("client", None)
            return request_args["client"].chat.completions.create(**req)
        return chat_completion_with_backoff(**request_args)
    except Exception as exc:
        msg = str(exc).lower()
        fallback_args = dict(request_args)
        changed = False

        # OpenRouter and some providers reject this field.
        if "reasoning_effort" in fallback_args and any(
            tok in msg for tok in ["reasoning_effort", "unknown parameter", "unsupported", "extra_forbidden"]
        ):
            fallback_args.pop("reasoning_effort", None)
            changed = True

        if "max_completion_tokens" in fallback_args and "max_completion_tokens" in msg:
            fallback_args.pop("max_completion_tokens", None)
            changed = True

        if not changed:
            raise

        if debug:
            req = dict(fallback_args)
            req.pop("client", None)
            return fallback_args["client"].chat.completions.create(**req)
        return chat_completion_with_backoff(**fallback_args)


def _append_failure_generation(
    *,
    answers: List[str],
    generation_statuses: List[str],
    generation_errors: List[Optional[str]],
    status: str,
    error_message: str,
    token_logprobs_out: Optional[List[List[Dict]]],
) -> None:
    answers.append("")
    generation_statuses.append(status)
    generation_errors.append(error_message)
    if token_logprobs_out is not None:
        token_logprobs_out.append([])


def _finalize_generation_lists(
    *,
    expected_n: int,
    answers: List[str],
    generation_statuses: List[str],
    generation_errors: List[Optional[str]],
    token_logprobs_out: Optional[List[List[Dict]]],
) -> None:
    current_n = len(answers)
    if current_n > expected_n:
        del answers[expected_n:]
        del generation_statuses[expected_n:]
        del generation_errors[expected_n:]
        if token_logprobs_out is not None:
            del token_logprobs_out[expected_n:]
    elif current_n < expected_n:
        for _ in range(expected_n - current_n):
            _append_failure_generation(
                answers=answers,
                generation_statuses=generation_statuses,
                generation_errors=generation_errors,
                status="response_parse_error",
                error_message="Missing generation output for this attempt.",
                token_logprobs_out=token_logprobs_out,
            )


def run_inference(cases: List[Dict], statutes: str, config: Config, prompt_composer=compose_prompt_source) -> List[Dict]:
    """Run model inference on all cases."""
    long_timeout_client = httpx.Client(timeout=7200)
    client = OpenAI(
        base_url=config.api_base_url,
        api_key=config.api_key,
        http_client=long_timeout_client,
    )

    processed_cases: List[Dict] = []
    for _, case_query in tqdm(list(enumerate(cases)), desc="Processing cases"):
        prompt = prompt_composer(statutes, case_query)
        processed_case = {
            "text": case_query.get("text", ""),
            "question": case_query["question"],
            "label": case_query.get("label"),
            "prompt": prompt,
            "dataset": config.dataset,
        }
        for k in ("id", "idx", "state", "question_group", "statute_ids", "gold_answer", "answer"):
            if k in case_query:
                processed_case[k] = case_query[k]

        messages = [
            # {"role": "system", "content": "You are Qwen, created by Alibaba Cloud. You are a helpful assistant."},
            {"role": "system", "content": "You are a helpful assistant trained to conduct deontic reasoning"},
            {"role": "user", "content": prompt},
        ]

        use_logprobs = False  # Keep existing behavior.
        use_reasoning = config.model_name in reasoning_models
        answers: List[str] = []
        generation_statuses: List[str] = []
        generation_errors: List[Optional[str]] = []
        token_logprobs_out: Optional[List[List[Dict]]] = [] if use_logprobs else None
        generated_tokens = 0
        prompt_tokens = 0

        try:
            request_args = {
                "client": client,
                "model": config.model_name,
                "n": config.num_generations,
                "messages": messages,
                "temperature": config.temperature,
            }
            if config.model_name in deepseek_models:
                request_args["top_p"] = 0.95
                request_args["temperature"] = 0.7
                request_args["max_tokens"] = 8192
            if config.model_name in gpt4_models:
                request_args["max_completion_tokens"] = 8192
            if use_logprobs:
                request_args["logprobs"] = True
            if use_reasoning:
                request_args["reasoning_effort"] = config.reasoning_effort
                request_args.pop("temperature", None)
            for arg, val in model_arg_dict.get(config.model_name, {}).items():
                request_args[arg] = val

            is_openrouter = "openrouter.ai" in config.api_base_url
            is_together = "together.xyz" in config.api_base_url
            if config.model_name in max_n_1_models or is_openrouter or is_together:
                request_args["n"] = 1
                n_iters = config.num_generations
            else:
                n_iters = 1

            if config.model_name in codex_models:
                for _ in range(config.num_generations):
                    try:
                        model_output = client.responses.create(
                            model=config.model_name,
                            input=prompt,
                            reasoning={"effort": config.reasoning_effort},
                            store=True,
                        )
                    except Exception as exc:
                        _append_failure_generation(
                            answers=answers,
                            generation_statuses=generation_statuses,
                            generation_errors=generation_errors,
                            status="request_error",
                            error_message=str(exc),
                            token_logprobs_out=token_logprobs_out,
                        )
                        continue

                    output_text = getattr(model_output, "output_text", "")
                    if output_text is None:
                        output_text = ""
                    if not isinstance(output_text, str):
                        output_text = str(output_text)
                    answers.append(output_text)
                    if output_text.strip():
                        generation_statuses.append("ok")
                        generation_errors.append(None)
                    else:
                        generation_statuses.append("empty_output")
                        generation_errors.append("Model returned an empty output.")
                    usage = getattr(model_output, "usage", None)
                    generated_tokens += getattr(usage, "output_tokens", 0) if usage else 0
                    prompt_tokens += getattr(usage, "input_tokens", 0) if usage else 0
                    if token_logprobs_out is not None:
                        token_logprobs_out.append([])
            else:
                request_n = int(request_args.get("n", 1))
                for _ in range(n_iters):
                    try:
                        model_output = _invoke_chat_with_fallback(request_args, debug=config.debug)
                    except Exception as exc:
                        for _ in range(request_n):
                            _append_failure_generation(
                                answers=answers,
                                generation_statuses=generation_statuses,
                                generation_errors=generation_errors,
                                status="request_error",
                                error_message=str(exc),
                                token_logprobs_out=token_logprobs_out,
                            )
                        continue

                    choices = list(getattr(model_output, "choices", []) or [])
                    if not choices:
                        for _ in range(request_n):
                            _append_failure_generation(
                                answers=answers,
                                generation_statuses=generation_statuses,
                                generation_errors=generation_errors,
                                status="response_parse_error",
                                error_message="Model response did not include choices.",
                                token_logprobs_out=token_logprobs_out,
                            )
                    else:
                        for choice in choices[:request_n]:
                            content = getattr(getattr(choice, "message", None), "content", "")
                            if content is None:
                                content = ""
                            if not isinstance(content, str):
                                content = str(content)
                            answers.append(content)
                            if content.strip():
                                generation_statuses.append("ok")
                                generation_errors.append(None)
                            else:
                                generation_statuses.append("empty_output")
                                generation_errors.append("Model returned an empty output.")
                            if token_logprobs_out is not None:
                                try:
                                    token_logprobs_out.append(process_chat_logprobs(choice))
                                except Exception as exc:
                                    token_logprobs_out.append([])
                                    generation_statuses[-1] = "response_parse_error"
                                    generation_errors[-1] = f"Could not parse token logprobs: {exc}"

                        if len(choices) < request_n:
                            for _ in range(request_n - len(choices)):
                                _append_failure_generation(
                                    answers=answers,
                                    generation_statuses=generation_statuses,
                                    generation_errors=generation_errors,
                                    status="response_parse_error",
                                    error_message="Model returned fewer choices than requested.",
                                    token_logprobs_out=token_logprobs_out,
                                )

                    usage = getattr(model_output, "usage", None)
                    generated_tokens += getattr(usage, "completion_tokens", 0) if usage else 0
                    prompt_tokens += getattr(usage, "prompt_tokens", 0) if usage else 0
        except Exception as exc:
            print(f"Error processing case: {exc}")

        _finalize_generation_lists(
            expected_n=config.num_generations,
            answers=answers,
            generation_statuses=generation_statuses,
            generation_errors=generation_errors,
            token_logprobs_out=token_logprobs_out,
        )

        processed_case["answers"] = answers
        processed_case["generation_statuses"] = generation_statuses
        processed_case["generation_errors"] = generation_errors
        processed_case["generation_attempted"] = len(answers)
        processed_case["generation_succeeded"] = sum(1 for status in generation_statuses if status == "ok")
        processed_case["generation_failed"] = sum(1 for status in generation_statuses if status != "ok")
        if processed_case["generation_succeeded"] == processed_case["generation_attempted"]:
            processed_case["case_status"] = "ok"
        elif processed_case["generation_succeeded"] == 0:
            processed_case["case_status"] = "all_failed"
        else:
            processed_case["case_status"] = "partial_failure"
        if token_logprobs_out is not None:
            processed_case["token_logprobs"] = token_logprobs_out
        processed_case["generated_tokens"] = generated_tokens
        processed_case["prompt_tokens"] = prompt_tokens
        processed_cases.append(processed_case)

    return processed_cases


def save_results(cases: List[Dict], output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(cases, f, indent=2)
    except Exception as exc:
        raise RuntimeError(f"Error saving results: {exc}") from exc


def save_prompt_template_artifacts(
    *,
    output_dir: str,
    config: Config,
    prompt_composer,
    template_meta: Optional[Dict] = None,
) -> None:
    os.makedirs(output_dir, exist_ok=True)
    source_text = ""
    source_file = None
    try:
        source_text = inspect.getsource(prompt_composer)
        source_file = inspect.getsourcefile(prompt_composer)
    except Exception:
        source_text = f"# source_unavailable for {getattr(prompt_composer, '__name__', str(prompt_composer))}\n"

    source_path = os.path.join(output_dir, "prompt_template_source.txt")
    with open(source_path, "w", encoding="utf-8") as f:
        f.write(source_text)

    info = {
        "generated_at_utc": utc_now_iso(),
        "dataset": config.dataset,
        "task": config.task,
        "model_name": config.model_name,
        "prompt_composer_name": getattr(prompt_composer, "__name__", str(prompt_composer)),
        "prompt_composer_source_file": source_file,
        "source_artifact": "prompt_template_source.txt",
    }
    if template_meta:
        info.update(template_meta)

    info_path = os.path.join(output_dir, "prompt_template_info.json")
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)


def should_write_prompt_template_artifacts(dataset: str) -> bool:
    return dataset not in {"housing", "uscis"}


def clear_prompt_template_artifacts(output_dir: str) -> None:
    for artifact_name in ("prompt_template_source.txt", "prompt_template_info.json"):
        artifact_path = os.path.join(output_dir, artifact_name)
        if os.path.exists(artifact_path):
            os.remove(artifact_path)


def main():
    config = parse_args()

    # Load cases from DeonticBench JSON
    cases = load_cases_from_json(config.cases_path, config.dataset)

    # Load statutes (only for sara_numeric, sara_binary, airline).
    # In DeonticBench the statutes directory contains the source files directly
    # (e.g. statutes/sara/ has section1, section151, … at the top level).
    if config.dataset in {"sara_numeric", "sara_binary", "airline"}:
        statutes_source = load_statutes(config.statutes_path, events_only=False)
    else:
        # housing, uscis: statutes are inline in each case's statutes_text field
        statutes_source = ""

    # Inject per-case retrieved exemplars for airline few-shot (cabin-class retrieval)
    if config.dataset == "airline" and config.task == "prolog":
        pool_path = config.airline_exemplar_pool or config.cases_path
        pool_by_class = load_airline_exemplar_pool(pool_path)
        for case in cases:
            case['exemplar'] = retrieve_airline_exemplar(pool_by_class, case['text'])
        print(f"Loaded airline exemplar pool from {pool_path} (cabin-class retrieval)")

    if config.debug:
        cases = cases[:1]

    if config.task == "prolog":
        template_meta: Dict[str, object] = {}
        if config.dataset == "airline":
            prompt_composer = compose_prompt_prolog_airline
            prompt_template_source = compose_prompt_prolog_airline
            statutes_blob = statutes_source
        elif config.dataset == "housing":
            legal_ir_exemplars = (
                EXAMPLE_LEGAL_IR_ONE_SHOT if config.num_exemplars <= 1 else EXAMPLE_LEGAL_IR_TWO_SHOT
            )
            prompt_composer = lambda statutes, case: compose_prompt_prolog_legal_ir(
                statutes, case, exemplars=legal_ir_exemplars
            )
            prompt_template_source = compose_prompt_prolog_legal_ir
            template_meta["num_exemplars"] = int(config.num_exemplars)
            template_meta["legal_ir_exemplar_variant"] = "one-shot" if config.num_exemplars <= 1 else "two-shot"
            statutes_blob = ""
        elif config.dataset == "uscis":
            uscis_exemplars = EXAMPLE_USCIS_ONE_SHOT
            prompt_composer = lambda statutes, case: compose_prompt_prolog_uscis(
                statutes, case, exemplars=uscis_exemplars
            )
            prompt_template_source = compose_prompt_prolog_uscis
            template_meta["requested_num_exemplars"] = int(config.num_exemplars)
            template_meta["num_exemplars"] = 1
            template_meta["uscis_exemplar_variant"] = "one-shot"
            statutes_blob = ""
        elif config.dataset == "sara_binary":
            prompt_composer = compose_prompt_prolog_binary
            prompt_template_source = compose_prompt_prolog_binary
            statutes_blob = statutes_source
        else:
            # sara_numeric
            prompt_composer = compose_prompt_prolog_sara
            prompt_template_source = compose_prompt_prolog_sara
            statutes_blob = statutes_source

        if should_write_prompt_template_artifacts(config.dataset):
            save_prompt_template_artifacts(
                output_dir=config.output_path,
                config=config,
                prompt_composer=prompt_template_source,
                template_meta=template_meta,
            )
        else:
            clear_prompt_template_artifacts(config.output_path)
        cases_prolog = run_inference(cases, statutes_blob, config, prompt_composer=prompt_composer)
        save_results(cases_prolog, os.path.join(config.output_path, "prolog.json"))
    elif config.task == "direct":
        template_meta = {}
        if config.dataset == "housing":
            prompt_composer = compose_prompt_source_legal_ir
            prompt_template_source = compose_prompt_source_legal_ir
            statutes_blob = ""
        elif config.dataset == "uscis":
            prompt_composer = compose_prompt_source_uscis
            prompt_template_source = compose_prompt_source_uscis
            statutes_blob = ""
        elif config.dataset == "sara_binary":
            prompt_composer = compose_prompt_source_binary
            prompt_template_source = compose_prompt_source_binary
            statutes_blob = statutes_source
        else:
            # sara_numeric, airline
            prompt_composer = compose_prompt_source
            prompt_template_source = compose_prompt_source
            statutes_blob = statutes_source

        if should_write_prompt_template_artifacts(config.dataset):
            save_prompt_template_artifacts(
                output_dir=config.output_path,
                config=config,
                prompt_composer=prompt_template_source,
                template_meta=template_meta,
            )
        else:
            clear_prompt_template_artifacts(config.output_path)
        cases_source = run_inference(cases, statutes_blob, config, prompt_composer=prompt_composer)
        save_results(cases_source, os.path.join(config.output_path, "source.json"))
    elif config.task == "standalone":
        template_meta = {}
        if config.dataset == "airline":
            prompt_composer = compose_prompt_standalone_prolog_airline
            prompt_template_source = compose_prompt_standalone_prolog_airline
            statutes_blob = statutes_source
        elif config.dataset == "housing":
            prompt_composer = compose_prompt_standalone_prolog_legal_ir
            prompt_template_source = compose_prompt_standalone_prolog_legal_ir
            statutes_blob = ""
        elif config.dataset == "uscis":
            prompt_composer = compose_prompt_standalone_prolog_uscis
            prompt_template_source = compose_prompt_standalone_prolog_uscis
            statutes_blob = ""
        elif config.dataset == "sara_binary":
            prompt_composer = compose_prompt_standalone_prolog_binary
            prompt_template_source = compose_prompt_standalone_prolog_binary
            statutes_blob = statutes_source
        else:
            # sara_numeric
            prompt_composer = compose_prompt_standalone_prolog_sara
            prompt_template_source = compose_prompt_standalone_prolog_sara
            statutes_blob = statutes_source

        if should_write_prompt_template_artifacts(config.dataset):
            save_prompt_template_artifacts(
                output_dir=config.output_path,
                config=config,
                prompt_composer=prompt_template_source,
                template_meta=template_meta,
            )
        else:
            clear_prompt_template_artifacts(config.output_path)
        cases_standalone_prolog = run_inference(cases, statutes_blob, config, prompt_composer=prompt_composer)
        save_results(cases_standalone_prolog, os.path.join(config.output_path, "standalone_prolog.json"))
    else:
        print("invalid task:", config.task)

    print(f"Processing complete. Results saved to {config.output_path}")


if __name__ == "__main__":
    main()
