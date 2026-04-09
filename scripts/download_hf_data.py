#!/usr/bin/env python3
"""Download DeonticBench data from HuggingFace and write it to data/.

This populates the same data/<domain>/<split>.json layout that the
experimental scripts (experiments/run_*.sh) expect, so you can use a
fresh HuggingFace checkout instead of relying on the files bundled in
the repository.

Usage
-----
# Download all domains and splits (default)
python scripts/download_hf_data.py

# Download specific domains
python scripts/download_hf_data.py --domains sara_numeric airline

# Download specific splits only
python scripts/download_hf_data.py --splits smoke hard

# Custom output directory
python scripts/download_hf_data.py --output-dir /path/to/data

Note: The statute text files in statutes/ (used by sara_numeric,
sara_binary, and airline) are not part of the HuggingFace dataset and
still ship with the repository.
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

HF_REPO = "gydou/DeonticBench"

# Map local domain names → HuggingFace dataset config names and output dirs.
DOMAIN_CONFIG = {
    "sara_numeric": {"hf_config": "sara_numeric", "out_dir": "sara_numeric"},
    "sara_binary":  {"hf_config": "sara_binary",  "out_dir": "sara_binary"},
    "airline":      {"hf_config": "airline",       "out_dir": "airline"},
    "housing":      {"hf_config": "housing",       "out_dir": "housing"},
    "uscis":        {"hf_config": "uscis-aao",     "out_dir": "uscis-aao"},
}

ALL_DOMAINS = list(DOMAIN_CONFIG.keys())
# "smoke" is not a separate split on HuggingFace — it is derived from the
# first 5 cases of "hard" and written automatically when "hard" is downloaded.
ALL_SPLITS  = ["smoke", "hard", "whole"]


def download_split(hf_config: str, split: str) -> list:
    """Load one (config, split) pair from HuggingFace and return a plain list."""
    from datasets import load_dataset  # imported here so the error is clear

    ds = load_dataset(HF_REPO, hf_config, split=split, trust_remote_code=False)
    return [dict(row) for row in ds]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download DeonticBench from HuggingFace into data/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        choices=ALL_DOMAINS,
        default=ALL_DOMAINS,
        metavar="DOMAIN",
        help=f"Domains to download (default: all). Choices: {', '.join(ALL_DOMAINS)}",
    )
    parser.add_argument(
        "--splits",
        nargs="+",
        choices=ALL_SPLITS,
        default=ALL_SPLITS,
        metavar="SPLIT",
        help=f"Splits to download (default: all). Choices: {', '.join(ALL_SPLITS)}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "data",
        help="Root output directory (default: <repo>/data)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files (default: skip if already present)",
    )
    args = parser.parse_args()

    try:
        import datasets as _ds  # noqa: F401
    except ImportError:
        print(
            "ERROR: 'datasets' package not found.\n"
            "Install it with:  pip install datasets",
            file=sys.stderr,
        )
        sys.exit(1)

    for domain in args.domains:
        cfg = DOMAIN_CONFIG[domain]
        hf_config = cfg["hf_config"]
        out_dir = args.output_dir / cfg["out_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)

        # Cache the hard split in memory so we can derive smoke without a
        # second network round-trip.
        hard_rows: list | None = None

        for split in args.splits:
            out_path = out_dir / f"{split}.json"

            if out_path.exists() and not args.force:
                print(f"  [skip] {out_path} already exists (use --force to overwrite)")
                continue

            # smoke is derived from the first 5 cases of hard — not on HF.
            if split == "smoke":
                if hard_rows is None:
                    # hard hasn't been downloaded yet in this run; load it now.
                    hard_path = out_dir / "hard.json"
                    if hard_path.exists():
                        with open(hard_path, encoding="utf-8") as f:
                            hard_rows = json.load(f)
                    else:
                        print(f"Downloading {domain}/hard (needed for smoke) …", end=" ", flush=True)
                        try:
                            hard_rows = download_split(hf_config, "hard")
                        except Exception as exc:
                            print(f"FAILED\n  {exc}", file=sys.stderr)
                            hard_rows = []
                        if hard_rows:
                            with open(hard_path, "w", encoding="utf-8") as f:
                                json.dump(hard_rows, f, ensure_ascii=False, indent=2)
                            print(f"done  ({len(hard_rows)} cases → {hard_path})")

                rows = hard_rows[:5]
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(rows, f, ensure_ascii=False, indent=2)
                print(f"Generating {domain}/smoke … done  ({len(rows)} cases → {out_path})")
                continue

            print(f"Downloading {domain}/{split} …", end=" ", flush=True)
            try:
                rows = download_split(hf_config, split)
            except Exception as exc:
                print(f"FAILED\n  {exc}", file=sys.stderr)
                continue

            if split == "hard":
                hard_rows = rows  # cache for potential smoke derivation

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)

            print(f"done  ({len(rows)} cases → {out_path})")

    print("\nAll done.")
    print(
        "\nNote: statute files (statutes/sara, statutes/airline) are not included in\n"
        "the HuggingFace dataset — they are bundled with the repository."
    )


if __name__ == "__main__":
    main()
