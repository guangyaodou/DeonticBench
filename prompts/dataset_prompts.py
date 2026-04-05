import re
from typing import Any, Dict, Tuple

from prompts.case_exemplars import (
    EXAMPLE_LEGAL_IR_ONE_SHOT,
    EXAMPLE_USCIS_ONE_SHOT,
)


def compose_prompt_source_legal_ir(statutes: str, case: Dict[str, Any]) -> str:
    statutes_text = case.get("statutes_text", statutes)
    return (
        f"## Statutes:\n{statutes_text}\n\n"
        f"## Question:\n{case['question']}\n\n"
        "Answer with one token: Yes or No. Then provide brief reasoning. "
        "Ensure your final answer is explicitly Yes or No."
    )


def compose_prompt_source_uscis(statutes: str, case: Dict[str, Any]) -> str:
    instruction = case.get("instruction", "").strip()
    return (
        f"{instruction}\n\n"
        "Do not output Prolog for this run. "
        "Output one token only: Accepted or Dismissed."
    )


def compose_prompt_standalone_prolog_legal_ir(statutes: str, case: Dict[str, Any]) -> str:
    statutes_text = case.get("statutes_text", statutes)
    return (
        "You are an expert US housing lawyer and senior SWI-Prolog engineer. "
        "Write a self-contained SWI-Prolog program that translates statutes and question facts.\n\n"
        f"### HousingQA Sample\n- state: {case.get('state', '')}\n- focus_year: 2021\n\n"
        f"### Question\n{case['question']}\n\n"
        f"### Natural Language Statutes\n{statutes_text}\n\n"
        "### Output requirements\n"
        "- Output one runnable ```prolog block only.\n"
        "- Define housing_answer(Result) where Result is yes or no.\n"
        "- Derive Result via statute predicates; do not hardcode.\n"
        "- The file must run correctly under swipl -f file.pl.\n"
        "- Define main/0 and end with exactly :- initialization(main, main).\n"
        "- main must print exactly: housing_answer(~w).\n"
    )


def _extract_uscis_facts_rules(case: Dict[str, Any], statutes: str) -> Tuple[str, str]:
    facts = str(case.get("facts", "") or "").strip()
    rules = str(case.get("rules", "") or "").strip()
    if facts and rules:
        return facts, rules

    instruction = str(case.get("instruction", "") or "").strip()
    if instruction:
        facts_match = re.search(
            r"You are given the following facts:\s*(.*?)\s*You are given the following rules:\s*",
            instruction,
            flags=re.IGNORECASE | re.DOTALL,
        )
        rules_match = re.search(
            r"You are given the following rules:\s*(.*?)(?:For true/false or yes/no predicates|$)",
            instruction,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if facts_match and not facts:
            facts = facts_match.group(1).strip()
        if rules_match and not rules:
            rules = rules_match.group(1).strip()

    if not facts:
        facts = str(case.get("text", "") or "").strip()
    if not rules:
        rules = str(statutes or "").strip()
    return facts, rules


def compose_prompt_standalone_prolog_uscis(statutes: str, case: Dict[str, Any]) -> str:
    facts, rules = _extract_uscis_facts_rules(case, statutes)
    return (
        "You are an expert in the analysis of immigration appeals and you will parse these Administrative Appeals Office cases into Prolog code.\n"
        "Parse the facts and rules into Prolog code, ensuring that the program's output is binary: either Dismissed or Accepted.\n"
        f"You are given the following facts:\n{facts}\n\n"
        f"You are given the following rules:\n{rules}\n\n"
        "For true/false or yes/no predicates, use arity 0 and check it is consistent for all clauses. For example, use there_is_evidence. instead of there_is_evidence(True).\n"
        "Program must be self-executing under `swipl -f file.pl`.\n"
        "Do not include the query in the prolog output, only include the entrypoint.\n"
        "Define main/0 and end with exactly :- initialization(main, main).\n"
        "When executed, print exactly one token: Accepted or Dismissed.\n"
        "Include this structure at the end and work assuming that eligibility_met is all the conditions necessary to Accept the case. Therefore, this must be the last part of the program.\n"
        "decision(Result) :-\n"
        "    (   eligibility_met\n"
        "    ->  Result = 'Accepted'\n"
        "    ;   Result = 'Dismissed'\n"
        "    ).\n"
        "\n"
        "main :-\n"
        "    catch(\n"
        "        (   decision(Result),\n"
        "            writeln(Result)\n"
        "        ),\n"
        "        error(existence_error(procedure, PI), _),\n"
        "        handle_undefined(PI)\n"
        "    ).\n"
        "\n"
        "handle_undefined(Name/Arity) :-\n"
        "    (   current_predicate(Name/OtherArity),\n"
        "        OtherArity \\= Arity\n"
        "    ->  format('Programming error: called ~w/~w, but only ~w/~w is defined.~n',\n"
        "               [Name, Arity, Name, OtherArity])\n"
        "    ;   format('Lack of information: predicate ~w/~w is not defined.~n',\n"
        "               [Name, Arity])\n"
        "    ).\n"
        "\n"
        ":- initialization(main, main).\n"
    )


def compose_prompt_prolog_legal_ir(
    statutes: str,
    case: Dict[str, Any],
    exemplars: str = EXAMPLE_LEGAL_IR_ONE_SHOT,
) -> str:
    statutes_text = case.get("statutes_text", statutes)
    return (
        "You are an expert US housing lawyer and senior SWI-Prolog engineer. "
        "Write a self-contained SWI-Prolog program that translates statutes and question facts.\n\n"
        "## Examples (format/style only - do NOT reuse their facts)\n"
        f"{exemplars}\n\n"
        f"### HousingQA Sample\n- state: {case.get('state', '')}\n- focus_year: 2021\n\n"
        f"### Question\n{case['question']}\n\n"
        f"### Natural Language Statutes\n{statutes_text}\n\n"
        "### Output requirements\n"
        "- Output one runnable ```prolog block only.\n"
        "- Define housing_answer(Result) where Result is yes or no.\n"
        "- Derive Result via statute predicates; do not hardcode.\n"
        "- The file must run correctly under swipl -f file.pl.\n"
        "- Define main/0 and end with exactly :- initialization(main, main).\n"
        "- main must print exactly: housing_answer(~w).\n"
    )


def compose_prompt_prolog_uscis(
    statutes: str,
    case: Dict[str, Any],
    exemplars: str = EXAMPLE_USCIS_ONE_SHOT,
) -> str:
    instruction = case.get("instruction", "").strip()
    return (
        "You are an expert in the analysis of immigration appeals and you will parse "
        "Administrative Appeals Office cases into Prolog code.\n\n"
        "## Examples (format/style only - do NOT reuse their facts)\n"
        f"{exemplars}\n\n"
        "## Current case to parse\n"
        f"{instruction}\n\n"
        "### Output requirements\n"
        "- Output one runnable ```prolog block only.\n"
        "- When executed, print exactly one token: Accepted or Dismissed.\n"
        "- Program must be self-executing under `swipl -f file.pl`.\n"
        "- Define main/0 and end with exactly :- initialization(main, main).\n"
        "- Do not print Label, confidence, or any metadata.\n"
        "- Use quoted atoms 'Accepted' and 'Dismissed' in Prolog (required for uppercase atoms).\n"
    )
