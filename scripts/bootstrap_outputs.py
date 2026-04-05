#!/usr/bin/env python3
"""
Bootstrap CI estimator for DeonticBench outputs.

Auto-discovers all completed runs under outputs/ and computes bootstrapped
accuracy ± 95% CI, abstention rate, and wrong rate for each
(domain, mode, model) triple.

Output layout (mirrors the old sara_parse bootstrap CSVs):
    bootstrap_results/<domain>/<mode>_bootstrap.csv

Bootstrap procedure (per model):
  1. Load per-case outcomes from swipl .txt (Prolog modes) or source.json (direct).
  2. Resample cases with replacement (captures dataset-size uncertainty).
  3. For each resampled case, pick one outcome uniformly at random
     (captures LLM stochasticity across K generations).
  4. Compute accuracy / abstain_rate / wrong_rate for the replicate.
  5. Repeat 1 000 times; report mean ± 95% CI (2.5 / 97.5 percentiles).

Abstention definition
---------------------
* Prolog modes  : empty / timeout swipl output → outcome = ABSTAIN
* Direct mode   : answer text cannot be parsed to the expected label type
                  → outcome = ABSTAIN

Usage
-----
python scripts/bootstrap_outputs.py                    # all domains & modes
python scripts/bootstrap_outputs.py --domains airline sara_numeric
python scripts/bootstrap_outputs.py --modes few_shot direct
python scripts/bootstrap_outputs.py --output bootstrap_results/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ── repo root ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT   = SCRIPT_DIR.parent

# sentinel for abstention
ABSTAIN = float("nan")

# ── domain configuration ──────────────────────────────────────────────────────
# Maps domain folder name → data file relative to REPO_ROOT
DOMAIN_DATA_FILES: Dict[str, str] = {
    "sara_numeric": "data/sara_numeric/hard.json",
    "sara_binary":  "data/sara_binary/hard.json",
    "airline":      "data/airline/hard.json",
    "housing":      "data/housing/hard.json",
    "uscis":        "data/uscis-aao/hard.json",
}

ALL_DOMAINS = list(DOMAIN_DATA_FILES.keys())
ALL_MODES   = ["few_shot", "zero_shot", "direct"]

# Domains where the swipl output embeds the gold label in a "Label: …" line
DOMAINS_WITH_EMBEDDED_LABEL = {"housing", "uscis"}

# Domains with numeric labels (allow ±1 rounding tolerance)
NUMERIC_DOMAINS = {"sara_numeric", "airline"}


# ── label loading ─────────────────────────────────────────────────────────────

def load_labels(domain: str) -> List:
    """Return ordered list of gold labels from the hard.json data file.

    For numeric domains labels are int; for binary domains they are
    already normalised to 1 / -1 / 0 matching generate_e2e.py conventions.
    """
    data_file = REPO_ROOT / DOMAIN_DATA_FILES[domain]
    if not data_file.exists():
        return []
    with open(data_file) as f:
        cases = json.load(f)
    labels = []
    for item in cases:
        raw = item.get("label")
        if domain in NUMERIC_DOMAINS:
            labels.append(int(raw))
        elif domain == "sara_binary":
            labels.append(int(raw))   # 1 = Entailment, 0 = Contradiction
        elif domain == "housing":
            labels.append(_norm_housing(raw))
        elif domain == "uscis":
            labels.append(_norm_uscis(raw))
        else:
            labels.append(raw)
    return labels


def _norm_housing(val) -> int:
    """yes → 1, no → -1, unknown → 0."""
    if isinstance(val, (int, float)):
        iv = int(val)
        return 1 if iv > 0 else (-1 if iv < 0 else 0)
    s = str(val).strip().lower()
    if s in {"yes", "y", "true", "1", "+1"}:
        return 1
    if s in {"no", "n", "false", "-1"}:
        return -1
    return 0


def _norm_uscis(val) -> int:
    """Accepted → 1, Dismissed → -1, unknown → 0."""
    if isinstance(val, (int, float)):
        iv = int(val)
        return 1 if iv > 0 else (-1 if iv < 0 else 0)
    s = str(val).strip().lower()
    if s in {"accepted", "accept", "yes", "1", "+1", "remand", "remanded"}:
        return 1
    if s in {"dismissed", "dismiss", "no", "-1"}:
        return -1
    return 0


# ── swipl .txt parsing ────────────────────────────────────────────────────────

def _is_pl_path(line: str) -> bool:
    """True if the line looks like a path to a .pl file."""
    s = line.strip()
    return s.endswith(".pl") and ("/" in s or "\\" in s)


def _case_idx_from_path(path_line: str) -> Optional[int]:
    """Extract 1-based case index from a processed-prolog filename.

    Patterns handled:
        tax_case_3_1.pl          → 3
        airline_case_5_0.pl      → 5
        sara_binary_case_2_1.pl  → 2
        uscis_case_4_0.pl        → 4
        housing_case_1_2.pl      → 1
    """
    stem = Path(path_line.strip()).stem          # e.g. "airline_case_3_1"
    m = re.search(r"_case_(\d+)_\d+$", stem)
    if m:
        return int(m.group(1))
    return None


def parse_swipl_txt(path: str, domain: str, labels: List) -> Dict[int, dict]:
    """Parse a swipl output file and return per-case outcome dicts.

    Returns:
        {case_pos (0-based): {"label": int/float, "outcomes": [...]}}

    Outcomes are floats for numeric domains; 1 / -1 / 0 for binary;
    NaN for abstentions.
    """
    with open(path) as f:
        raw_lines = f.readlines()
    lines = [l.rstrip("\n") for l in raw_lines]

    # Group lines into blocks per .pl file
    blocks: List[Tuple[str, List[str]]] = []   # (pl_path, output_lines)
    current_pl: Optional[str] = None
    current_out: List[str] = []
    for line in lines:
        if _is_pl_path(line):
            if current_pl is not None:
                blocks.append((current_pl, current_out))
            current_pl = line.strip()
            current_out = []
        else:
            current_out.append(line)
    if current_pl is not None:
        blocks.append((current_pl, current_out))

    # Build per-case accumulator: case_idx (1-based) → list of outcomes
    case_outcomes: Dict[int, List] = {}
    case_labels:   Dict[int, int]  = {}

    for pl_path, out_lines in blocks:
        case_idx = _case_idx_from_path(pl_path)
        if case_idx is None:
            continue

        outcome = _extract_outcome_from_swipl(out_lines, domain)

        # Gold label: try embedded first, fall back to data file
        label = None
        if domain in DOMAINS_WITH_EMBEDDED_LABEL:
            label = _extract_embedded_label(out_lines, domain)
        if label is None:
            # 1-indexed case_idx → 0-indexed position in data file
            pos = case_idx - 1
            label = labels[pos] if 0 <= pos < len(labels) else None

        if label is None:
            continue

        if case_idx not in case_outcomes:
            case_outcomes[case_idx] = []
            case_labels[case_idx] = label
        case_outcomes[case_idx].append(outcome)

    combined: Dict[int, dict] = {}
    for pos, (idx, outcomes) in enumerate(sorted(case_outcomes.items())):
        combined[pos] = {
            "label":    case_labels[idx],
            "outcomes": outcomes,
        }
    return combined


def _extract_outcome_from_swipl(out_lines: List[str], domain: str):
    """Return the numeric/categorical outcome from a block of swipl output lines."""
    # Flatten non-empty lines
    nonempty = [l for l in out_lines if l.strip()]

    # Timeout
    if any("Result: timeout" in l for l in nonempty):
        return ABSTAIN

    if domain in NUMERIC_DOMAINS:
        # Look for "Tax result: <num>" or "Total cost: <num>"
        for l in nonempty:
            m = re.search(r"(?:Tax result|Total cost)[:\s]+([+-]?\d[\d,]*(?:\.\d+)?)", l, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(",", ""))
                except ValueError:
                    pass
        return ABSTAIN

    elif domain == "sara_binary":
        for l in nonempty:
            m = re.search(r"Result:\s*(Entailment|Contradiction)", l, re.IGNORECASE)
            if m:
                return 1 if m.group(1).lower() == "entailment" else 0
        return ABSTAIN

    elif domain == "uscis":
        # Last non-empty line is the Prolog verdict (or an error message)
        for l in reversed(nonempty):
            s = l.strip().lower()
            if s.startswith("label:"):
                continue   # skip the embedded-label line
            if "accepted" in s:
                return 1
            if "dismissed" in s:
                return -1
            # Error / undefined predicate / etc. → abstain
            return ABSTAIN
        return ABSTAIN

    elif domain == "housing":
        for l in reversed(nonempty):
            s = l.strip().lower()
            if s.startswith("label:"):
                continue
            m = re.search(r"housing_answer\((yes|no)\)", s)
            if m:
                return 1 if m.group(1) == "yes" else -1
            # Any other non-label line = abstention
            return ABSTAIN
        return ABSTAIN

    return ABSTAIN


def _extract_embedded_label(out_lines: List[str], domain: str) -> Optional[int]:
    """Extract gold label from a 'Label: …' line in the swipl output."""
    for l in out_lines:
        m = re.match(r"Label:\s*(.+)", l.strip(), re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            if domain == "housing":
                return _norm_housing(raw)
            if domain == "uscis":
                return _norm_uscis(raw)
    return None


# ── direct source.json parsing ────────────────────────────────────────────────

def parse_source_json(path: str, domain: str) -> Dict[int, dict]:
    """Parse a direct-mode source.json and return per-case outcome dicts."""
    with open(path) as f:
        data = json.load(f)

    combined: Dict[int, dict] = {}
    for pos, item in enumerate(data):
        label      = item.get("label")
        answers    = item.get("answers", [])
        statuses   = item.get("generation_statuses", [])

        outcomes = []
        for ans, status in zip(answers, statuses):
            if status not in ("ok", None, ""):
                outcomes.append(ABSTAIN)
                continue
            outcome = _parse_direct_answer(ans, domain)
            outcomes.append(outcome)

        # Pad missing statuses
        for ans in answers[len(statuses):]:
            outcomes.append(_parse_direct_answer(ans, domain))

        if label is None:
            continue

        combined[pos] = {
            "label":    label,
            "outcomes": outcomes,
        }
    return combined


def _parse_direct_answer(text: str, domain: str):
    """Extract a numeric or categorical prediction from a free-text LLM answer."""
    if not text or not text.strip():
        return ABSTAIN

    if domain in NUMERIC_DOMAINS:
        return _extract_number(text)

    elif domain == "sara_binary":
        # Look for \boxed{Entailment} or \boxed{Contradiction} first
        m = re.search(r"\\boxed\{(Entailment|Contradiction)\}", text, re.IGNORECASE)
        if m:
            return 1 if m.group(1).lower() == "entailment" else 0
        # Fall back to last occurrence
        positions = []
        for tok, val in [("entailment", 1), ("contradiction", 0)]:
            idx = text.lower().rfind(tok)
            if idx >= 0:
                positions.append((idx, val))
        if positions:
            return max(positions, key=lambda x: x[0])[1]
        return ABSTAIN

    elif domain == "uscis":
        m = re.search(r"\\boxed\{(Accepted|Dismissed)\}", text, re.IGNORECASE)
        if m:
            raw = m.group(1).lower()
            return 1 if "accept" in raw else -1
        positions = []
        for tok, val in [("accepted", 1), ("dismissed", -1)]:
            idx = text.lower().rfind(tok)
            if idx >= 0:
                positions.append((idx, val))
        if positions:
            return max(positions, key=lambda x: x[0])[1]
        return ABSTAIN

    elif domain == "housing":
        # Prompt says "Answer with one token: Yes or No."
        # Check the very start of the answer first
        first_token = text.strip().split()[0].lower().rstrip(".,;:") if text.strip() else ""
        if first_token in ("yes", "y"):
            return 1
        if first_token in ("no", "n"):
            return -1
        # Fall back to last explicit Yes/No
        positions = []
        for tok, val in [("yes", 1), ("no", -1)]:
            idx = text.lower().rfind(tok)
            if idx >= 0:
                positions.append((idx, val))
        if positions:
            # Require it to be a word boundary hit
            best = max(positions, key=lambda x: x[0])
            idx, val = best
            # Simple boundary check
            before = text[idx - 1] if idx > 0 else " "
            after  = text[idx + (3 if val == 1 else 2)] if idx + (3 if val == 1 else 2) < len(text) else " "
            if not before.isalpha() and not after.isalpha():
                return val
        return ABSTAIN

    return ABSTAIN


def _extract_number(text: str):
    """Extract a numeric answer from free text; returns float or ABSTAIN."""
    if not text:
        return ABSTAIN

    # Priority 1: \boxed{...}
    m = re.search(r"\\boxed\{([^}]+)\}", text)
    if m:
        raw = m.group(1).replace(",", "").replace("$", "").replace(" ", "")
        try:
            return float(raw)
        except ValueError:
            pass

    # Priority 2: last standalone dollar amount "$1,234.56" or "$1234"
    dollar_matches = re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", text)
    if dollar_matches:
        try:
            return float(dollar_matches[-1].replace(",", ""))
        except ValueError:
            pass

    # Priority 3: last bare integer / decimal that looks like a total
    num_matches = re.findall(r"\b([\d,]+(?:\.\d+)?)\b", text)
    if num_matches:
        # Filter: take the last number that's plausible (> 0)
        for raw in reversed(num_matches):
            try:
                v = float(raw.replace(",", ""))
                if v > 0:
                    return v
            except ValueError:
                pass

    return ABSTAIN


# ── correctness ───────────────────────────────────────────────────────────────

def _is_abstain(outcome) -> bool:
    return outcome is None or (isinstance(outcome, float) and outcome != outcome)


def _is_correct(outcome, label, domain: str) -> bool:
    if _is_abstain(outcome):
        return False
    if domain in NUMERIC_DOMAINS:
        # ±1 tolerance (floating-point rounding in Prolog/LLM arithmetic)
        return abs(round(float(outcome)) - int(float(label))) <= 1
    else:
        # Exact match for categorical domains
        return int(round(float(outcome))) == int(float(label))


# ── bootstrap ─────────────────────────────────────────────────────────────────

def bootstrap_accuracy(
    combined: Dict[int, dict],
    domain: str,
    n_bootstrap: int = 1000,
    rng_seed: int = 42,
) -> dict:
    """Bootstrap accuracy ± 95% CI, matching the procedure in bootstrap_uscis.py.

    Abstention definition
    ---------------------
    Prolog modes (few_shot / zero_shot):
        A generation abstains when its Prolog code is non-executable — i.e. swipl
        produces no valid output (empty, error message, or timeout).
    Direct mode:
        A generation abstains when the model's free-text answer cannot be parsed
        to the expected answer type (number for numeric domains; Entailment /
        Contradiction / Accepted / Dismissed / Yes / No for categorical domains).

    Bootstrap procedure (mirrors bootstrap_uscis.py)
    -------------------------------------------------
    For each of 1 000 replicates:
      1. Resample N cases with replacement (N = number of cases in this run).
      2. For each resampled case, pick ONE outcome uniformly at random from its
         K generations (captures LLM stochasticity).
      3. Compute accuracy = n_correct / N.
         Abstentions count as wrong; cases with no outcomes are skipped (do not
         reduce the denominator — matching the reference implementation).
      4. Report mean ± 95% CI (2.5 / 97.5 percentiles across replicates).
    """
    rng   = np.random.default_rng(rng_seed)
    items = list(combined.values())
    n     = len(items)
    if n == 0:
        return _empty_bootstrap_stats()

    rep_accs    = []
    rep_abstain = []
    rep_wrong   = []

    for _ in range(n_bootstrap):
        idxs      = rng.integers(0, n, size=n)
        n_correct = 0
        n_abstain = 0

        for i in idxs:
            item     = items[i]
            outcomes = item["outcomes"]
            label    = item["label"]
            if not outcomes:
                continue   # no generations recorded — skip (matches reference)
            chosen = outcomes[int(rng.integers(0, len(outcomes)))]
            if _is_abstain(chosen):
                n_abstain += 1
            elif _is_correct(chosen, label, domain):
                n_correct += 1

        rep_accs.append(n_correct / n)
        rep_abstain.append(n_abstain / n)
        rep_wrong.append((n - n_correct - n_abstain) / n)

    def _stats(arr):
        return float(np.mean(arr)), float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))

    mean_acc,     lo_acc,     hi_acc     = _stats(rep_accs)
    mean_abstain, lo_abstain, hi_abstain = _stats(rep_abstain)
    mean_wrong,   lo_wrong,   hi_wrong   = _stats(rep_wrong)

    return {
        "n_items":                  n,
        "mean_accuracy":            round(mean_acc,     4),
        "acc_ci_low_95":            round(lo_acc,       4),
        "acc_ci_high_95":           round(hi_acc,       4),
        "acc_ci_half_width":        round((hi_acc - lo_acc) / 2, 4),
        "mean_abstain_rate":        round(mean_abstain, 4),
        "abstain_ci_low_95":        round(lo_abstain,   4),
        "abstain_ci_high_95":       round(hi_abstain,   4),
        "abstain_ci_half_width":    round((hi_abstain - lo_abstain) / 2, 4),
        "mean_wrong_rate":          round(mean_wrong,   4),
        "wrong_ci_low_95":          round(lo_wrong,     4),
        "wrong_ci_high_95":         round(hi_wrong,     4),
        "wrong_ci_half_width":      round((hi_wrong - lo_wrong) / 2, 4),
    }


def _empty_bootstrap_stats() -> dict:
    keys = [
        "n_items",
        "mean_accuracy", "acc_ci_low_95", "acc_ci_high_95", "acc_ci_half_width",
        "mean_abstain_rate", "abstain_ci_low_95", "abstain_ci_high_95", "abstain_ci_half_width",
        "mean_wrong_rate", "wrong_ci_low_95", "wrong_ci_high_95", "wrong_ci_half_width",
    ]
    return {k: 0.0 for k in keys}


# ── discovery ─────────────────────────────────────────────────────────────────

def _model_name_from_swipl_txt(filename: str) -> str:
    """Strip trailing -fewshot / -zeroshot suffix to get model display name."""
    stem = Path(filename).stem
    stem = re.sub(r"-(fewshot|zeroshot)$", "", stem)
    return stem


def discover_runs(outputs_dir: Path, domains: List[str], modes: List[str]):
    """Yield (domain, mode, model_name, path) for every discovered output file."""
    for domain in domains:
        domain_dir = outputs_dir / domain
        if not domain_dir.exists():
            continue

        if "few_shot" in modes:
            for txt in sorted((domain_dir / "swipl" / "few_shot").glob("*.txt")):
                model = _model_name_from_swipl_txt(txt.name)
                yield domain, "few_shot", model, str(txt)

        if "zero_shot" in modes:
            for txt in sorted((domain_dir / "swipl" / "zero_shot").glob("*.txt")):
                model = _model_name_from_swipl_txt(txt.name)
                yield domain, "zero_shot", model, str(txt)

        if "direct" in modes:
            direct_dir = domain_dir / "direct"
            if direct_dir.exists():
                for src in sorted(direct_dir.rglob("source.json")):
                    # Model name = last two path components before source.json
                    # e.g. openai/gpt-4.1-2025-04-14
                    rel = src.relative_to(direct_dir)
                    parts = list(rel.parts[:-1])      # drop "source.json"
                    model = "/".join(parts) if parts else src.parent.name
                    yield domain, "direct", model, str(src)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap CI for all DeonticBench outputs."
    )
    parser.add_argument(
        "--outputs-dir",
        default=str(REPO_ROOT / "outputs"),
        help=f"Root outputs directory (default: {REPO_ROOT / 'outputs'})",
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "bootstrap_results"),
        help="Root directory for bootstrap CSV files (default: bootstrap_results/)",
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        default=ALL_DOMAINS,
        choices=ALL_DOMAINS,
        metavar="DOMAIN",
        help="Domains to evaluate (default: all)",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        default=ALL_MODES,
        choices=ALL_MODES,
        metavar="MODE",
        help="Modes to evaluate: few_shot, zero_shot, direct (default: all)",
    )
    parser.add_argument("--n-bootstrap", type=int, default=1000)
    parser.add_argument("--rng-seed",    type=int, default=42)
    args = parser.parse_args()

    outputs_dir = Path(args.outputs_dir)
    out_root    = Path(args.output)

    # Pre-load labels for all requested domains
    labels_cache: Dict[str, List] = {}
    for domain in args.domains:
        labels_cache[domain] = load_labels(domain)
        print(f"[{domain}] Loaded {len(labels_cache[domain])} gold labels.")

    # Accumulate results per (domain, mode)
    results: Dict[Tuple[str, str], List[dict]] = {}

    runs = list(discover_runs(outputs_dir, args.domains, args.modes))
    print(f"\nDiscovered {len(runs)} output file(s).\n")

    for domain, mode, model_name, path in runs:
        print(f"  [{domain}] [{mode}] {model_name}")
        try:
            if mode in ("few_shot", "zero_shot"):
                combined = parse_swipl_txt(path, domain, labels_cache[domain])
            else:
                combined = parse_source_json(path, domain)
        except Exception as e:
            print(f"    ERROR loading {path}: {e}")
            continue

        if not combined:
            print(f"    SKIP: no parseable cases in {path}")
            continue

        total_outcomes = sum(len(v["outcomes"]) for v in combined.values())
        n_items        = len(combined)
        print(f"    {n_items} cases, {total_outcomes} outcomes ({total_outcomes/n_items:.1f} per case)")

        stats = bootstrap_accuracy(combined, domain, args.n_bootstrap, args.rng_seed)
        print(f"    Accuracy:  {stats['mean_accuracy']:.4f}  "
              f"[{stats['acc_ci_low_95']:.4f}, {stats['acc_ci_high_95']:.4f}]")
        print(f"    Abstain:   {stats['mean_abstain_rate']:.4f}  "
              f"[{stats['abstain_ci_low_95']:.4f}, {stats['abstain_ci_high_95']:.4f}]")
        print(f"    Wrong:     {stats['mean_wrong_rate']:.4f}  "
              f"[{stats['wrong_ci_low_95']:.4f}, {stats['wrong_ci_high_95']:.4f}]")

        row = {
            "model":             model_name,
            "domain":            domain,
            "mode":              mode,
            "n_outcomes_per_item": round(total_outcomes / n_items, 2),
            "n_bootstrap":       args.n_bootstrap,
            **stats,
        }
        key = (domain, mode)
        results.setdefault(key, []).append(row)

    if not results:
        print("\nNo results found.")
        return

    # Save one CSV per (domain, mode)
    for (domain, mode), rows in sorted(results.items()):
        df       = pd.DataFrame(rows)
        dest_dir = out_root / domain
        dest_dir.mkdir(parents=True, exist_ok=True)
        fname    = dest_dir / f"{mode}_bootstrap.csv"
        df.to_csv(fname, index=False)
        print(f"\nSaved: {fname}")

    # Print a compact summary table
    print("\n" + "=" * 90)
    print("Summary")
    print("=" * 90)
    all_rows = [r for rows in results.values() for r in rows]
    summary  = pd.DataFrame(all_rows)[
        ["domain", "mode", "model",
         "n_items",
         "mean_accuracy", "acc_ci_low_95", "acc_ci_high_95",
         "mean_abstain_rate", "mean_wrong_rate"]
    ].sort_values(["domain", "mode", "mean_accuracy"], ascending=[True, True, False])
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
