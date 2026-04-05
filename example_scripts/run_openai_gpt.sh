#!/bin/bash
# MODELS="gpt-4.1-2025-04-14 gpt-5.2-2025-12-11 gpt-5.1-2025-11-13" \
DOMAINS="sara_numeric housing uscis" \
MODES="direct,few-shot" \
MODELS="gpt-5.1-2025-11-13" \
REASONING_EFFORT=medium \
SPLIT=smoke \
NUM_GENERATIONS=2 \
bash experiments/run_openai.sh
