#!/bin/bash
DOMAINS="uscis airline housing sara_numeric sara_binary" \
MODES="direct,zero-shot" \
MODELS="moonshotai/kimi-k2-0905" \
SPLIT=smoke \
NUM_GENERATIONS=2 \
bash experiments/run_openrouter.sh
