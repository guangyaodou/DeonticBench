#!/bin/bash
# MODELS="Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8 Qwen/Qwen3-Coder-Next-FP8 Qwen/Qwen3-235B-A22B-Instruct-2507-tput" \
DOMAINS="uscis airline housing sara_numeric sara_binary" \
MODES="direct,few-shot" \
MODELS="Qwen/Qwen3-235B-A22B-Instruct-2507-tput" \
REASONING_EFFORT=none \
SPLIT=smoke \
NUM_GENERATIONS=2 \
bash experiments/run_together.sh
