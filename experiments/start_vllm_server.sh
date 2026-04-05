#!/bin/bash
# Start a vLLM OpenAI-compatible server for DeonticBench local inference.
#
# Usage (interactive):
#   MODEL=/path/to/model bash experiments/start_vllm_server.sh
#
# Usage (SLURM):
#   MODEL=Qwen/Qwen2.5-32B-Instruct sbatch experiments/start_vllm_server.sh
#
# Required environment variables:
#   MODEL     Path to model weights or a HuggingFace model ID
#             e.g. MODEL=Qwen/Qwen2.5-32B-Instruct
#             e.g. MODEL=/data/models/my-finetuned-model
#
# Key optional environment variables:
#   PORT             vLLM port (default: 9009)
#   HOST             Bind address (default: 0.0.0.0)
#   DTYPE            Model dtype: bfloat16 | float16 | float32 (default: bfloat16)
#   GPU_UTIL         GPU memory utilization fraction (default: 0.94)
#   MAX_TOKENS       Max model context length in tokens (default: 32768)
#   KV_CACHE_DTYPE   KV cache dtype: auto | fp8 | fp16 (default: auto)
#   CACHE_DIR        HuggingFace model cache directory (default: $HF_HOME, then ~/.cache/huggingface/hub)
#                    On HPC clusters with small home quotas, set HF_HOME or CACHE_DIR to a scratch path.
#   TP               Tensor parallel degree — auto-detected from CUDA_VISIBLE_DEVICES if unset
#   HF_TOKEN         HuggingFace token for gated models (optional)
#   VLLM_API_KEY     Access key clients must send (optional; omit to disable auth)
#   CONDA_ENV        Conda environment to activate before launching (optional)
#
# Qwen-specific (YaRN long-context RoPE scaling):
#   ENABLE_YARN           auto | true | false  (default: auto — enables when MAX_TOKENS > base)
#   ORIGINAL_MAX_POS_EMB  Pretraining context length (default: 32768)
#   YARN_FACTOR           Manual scaling factor override (auto-computed when unset)
#   ROPE_TYPE             RoPE type (default: yarn)
#
# SLURM headers:
#SBATCH --job-name=deontic_vllm_server
#SBATCH --output=outputs/logs_deontic/%j.%x.log
#SBATCH --error=outputs/logs_deontic/%j.%x.log
#SBATCH --partition=h100
#SBATCH --gpus=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64GB
#SBATCH --nodes=1
#SBATCH --time=1-23:59:00

set -euo pipefail

# ── Conda environment (optional) ───────────────────────────────────────────────
# Set CONDA_ENV to activate a conda environment before launching vLLM.
# If unset, the current PATH is used as-is.
if [ -n "${CONDA_ENV:-}" ]; then
    _nounset_on=0
    [[ $- == *u* ]] && { _nounset_on=1; set +u; }
    # Try to find conda.sh in common locations
    for _conda_sh in \
        "${CONDA_PREFIX:-}/../../etc/profile.d/conda.sh" \
        "${HOME}/anaconda3/etc/profile.d/conda.sh" \
        "${HOME}/miniconda3/etc/profile.d/conda.sh" \
        "/opt/conda/etc/profile.d/conda.sh"; do
        [ -f "${_conda_sh}" ] && { source "${_conda_sh}"; break; }
    done
    conda activate "${CONDA_ENV}"
    [ "${_nounset_on}" -eq 1 ] && set -u
fi

mkdir -p "${SLURM_SUBMIT_DIR:-$(pwd)}/outputs/logs_deontic"
echo "Node hostname: $(hostname)"

# ── Model (required) ───────────────────────────────────────────────────────────
MODEL="${MODEL:-}"
if [ -z "${MODEL}" ]; then
    echo "Error: MODEL is required."
    echo "  Example: MODEL=Qwen/Qwen2.5-32B-Instruct bash experiments/start_vllm_server.sh"
    exit 1
fi

# ── Server settings ────────────────────────────────────────────────────────────
PORT="${PORT:-9009}"
HOST="${HOST:-0.0.0.0}"
DTYPE="${DTYPE:-bfloat16}"
GPU_UTIL="${GPU_UTIL:-0.94}"
MAX_TOKENS="${MAX_TOKENS:-10000}"
KV_CACHE_DTYPE="${KV_CACHE_DTYPE:-auto}"
CACHE_DIR="${CACHE_DIR:-${HF_HOME:-${HOME}/.cache/huggingface/hub}}"

# ── GPU / tensor-parallel setup ────────────────────────────────────────────────
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-${SLURM_VISIBLE_DEVICES:-0}}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"

TP="${TP:-}"
if [ -z "${TP}" ]; then
    if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then
        IFS=',' read -r -a _DEV_ARR <<< "${CUDA_VISIBLE_DEVICES}"
        TP="${#_DEV_ARR[@]}"
        echo "  Auto-detected TP=${TP} from CUDA_VISIBLE_DEVICES"
    elif [[ "${SLURM_GPUS_ON_NODE:-}" =~ ^[0-9]+$ ]]; then
        TP="${SLURM_GPUS_ON_NODE}"
        echo "  Auto-detected TP=${TP} from SLURM_GPUS_ON_NODE"
    else
        TP=1
        echo "  Could not auto-detect TP; defaulting to TP=1"
    fi
fi

# ── HuggingFace cache & auth ───────────────────────────────────────────────────
mkdir -p "${CACHE_DIR}"
export HF_HOME="${CACHE_DIR}"
export HUGGINGFACE_HUB_CACHE="${CACHE_DIR}"
[ -n "${HF_TOKEN:-}" ] && export HF_TOKEN

# ── Optional API key (passed to vLLM --api-key) ────────────────────────────────
API_KEY_ARG=()
[ -n "${VLLM_API_KEY:-}" ] && API_KEY_ARG=(--api-key "${VLLM_API_KEY}")

# ── YaRN RoPE scaling for Qwen long-context ───────────────────────────────────
ENABLE_YARN="${ENABLE_YARN:-auto}"
ORIGINAL_MAX_POS_EMB="${ORIGINAL_MAX_POS_EMB:-32768}"
ROPE_TYPE="${ROPE_TYPE:-yarn}"
ROPE_SCALING_ARG=()

MODEL_LC="${MODEL,,}"
IS_QWEN=false
[[ "${MODEL_LC}" == qwen/* || "${MODEL_LC}" == *qwen* ]] && IS_QWEN=true

if $IS_QWEN; then
    if [ "${ENABLE_YARN}" = "auto" ]; then
        [ "${MAX_TOKENS}" -gt "${ORIGINAL_MAX_POS_EMB}" ] && ENABLE_YARN=true || ENABLE_YARN=false
    fi

    if [ "${ENABLE_YARN}" = "true" ]; then
        if [ -z "${YARN_FACTOR:-}" ]; then
            YARN_FACTOR=$(python3 - <<PY
from math import ceil
val = ceil((${MAX_TOKENS}/${ORIGINAL_MAX_POS_EMB})*100)/100
print(f"{val:.2f}")
PY
)
        fi
        export YARN_FACTOR ORIGINAL_MAX_POS_EMB ROPE_TYPE
        ROPE_JSON=$(python3 - <<'PY'
import json, os
print(json.dumps({
    "rope_type": os.environ["ROPE_TYPE"],
    "factor": float(os.environ["YARN_FACTOR"]),
    "original_max_position_embeddings": int(os.environ["ORIGINAL_MAX_POS_EMB"]),
}))
PY
)
        echo "  Enabling YaRN for Qwen: rope_scaling=${ROPE_JSON}"
        ROPE_SCALING_ARG=(--rope-scaling "${ROPE_JSON}")
    else
        echo "  YaRN disabled (ENABLE_YARN=${ENABLE_YARN}; MAX_TOKENS=${MAX_TOKENS} <= ${ORIGINAL_MAX_POS_EMB})."
    fi
else
    echo "  Non-Qwen model — YaRN RoPE scaling not applied."
fi

# ── Launch ─────────────────────────────────────────────────────────────────────
echo ""
echo "Starting vLLM OpenAI-compatible server:"
echo "  MODEL=${MODEL}"
echo "  HOST=${HOST}  PORT=${PORT}  TP=${TP}  DTYPE=${DTYPE}"
echo "  MAX_TOKENS=${MAX_TOKENS}  GPU_UTIL=${GPU_UTIL}  KV_CACHE_DTYPE=${KV_CACHE_DTYPE}"
echo "  CACHE_DIR=${CACHE_DIR}"
echo ""

vllm serve "${MODEL}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --tensor-parallel-size "${TP}" \
    --dtype "${DTYPE}" \
    --max-model-len "${MAX_TOKENS}" \
    --gpu-memory-utilization "${GPU_UTIL}" \
    --kv-cache-dtype "${KV_CACHE_DTYPE}" \
    "${ROPE_SCALING_ARG[@]}" \
    "${API_KEY_ARG[@]}" \
    --trust-remote-code \
    --download-dir "${CACHE_DIR}"
