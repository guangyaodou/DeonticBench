#!/bin/bash
# Example: run inference against a locally-served vLLM model.
# Replace VLLM_API_BASE_URL with http://<node>:<port>/v1 and MODELS with your model ID or path.
DOMAINS="sara_numeric sara_binary uscis housing airline" \
MODES="few-shot zero-shot direct" \
VLLM_API_BASE_URL="http://h06:9009/v1" \
MODELS="Qwen/Qwen2.5-32B-Instruct" \
SPLIT=smoke \
bash experiments/run_vllm.sh
