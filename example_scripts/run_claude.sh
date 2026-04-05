#!/bin/bash
DOMAINS="uscis airline housing" \
MODES="zero-shot,direct" \
MODELS="anthropic/claude-opus-4" \
SPLIT=smoke \
NUM_GENERATIONS=3 \
bash experiments/run_openrouter.sh
