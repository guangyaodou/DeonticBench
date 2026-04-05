#!/usr/bin/env python3
"""Shared label normalization/scoring helpers for classification datasets."""

from __future__ import annotations

from typing import Optional


def _normalize_binary_label(
    value,
    *,
    positive_tokens: set[str],
    negative_tokens: set[str],
    abstain_tokens: set[str],
) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        iv = int(value)
        if iv > 0:
            return 1
        if iv < 0:
            return -1
        return 0

    text = str(value).strip().lower()
    if text in positive_tokens:
        return 1
    if text in negative_tokens:
        return -1
    if text in abstain_tokens:
        return 0
    return None


def normalize_legal_ir_label(value) -> Optional[int]:
    """Map legal IR labels to +1/-1/0."""
    return _normalize_binary_label(
        value,
        positive_tokens={"yes", "y", "true", "1", "+1", "positive"},
        negative_tokens={"no", "n", "false", "-1", "negative"},
        abstain_tokens={"abstain", "abstention", "unknown", "error", "none", "0"},
    )


def normalize_uscis_label(value) -> Optional[int]:
    """Map USCIS labels to +1/-1/0."""
    return _normalize_binary_label(
        value,
        positive_tokens={"accepted", "accept", "yes", "y", "true", "1", "+1", "remand", "remanded"},
        negative_tokens={"dismissed", "dismiss", "no", "n", "false", "-1"},
        abstain_tokens={"abstain", "abstention", "unknown", "error", "none", "0"},
    )


def normalize_label_for_dataset(dataset: str, value) -> Optional[int]:
    ds = (dataset or "").strip().lower()
    if ds == "legal_ir":
        return normalize_legal_ir_label(value)
    if ds == "uscis":
        return normalize_uscis_label(value)
    return None


def correctness_score(prediction: int, gold: int, abstain_value: int = 0) -> int:
    """Return +1 (correct), -1 (incorrect), 0 (abstain/error)."""
    if prediction == abstain_value:
        return 0
    if prediction == gold:
        return 1
    return -1
