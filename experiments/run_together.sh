#!/bin/bash
# Run DeonticBench inference using the Together AI API.
#
# Usage:
#   DOMAINS=sara_numeric TOGETHER_API_KEY=... bash experiments/run_together.sh
#
# Required environment variables:
#   TOGETHER_API_KEY    Your Together AI API key
#
# Key optional environment variables:
#   DOMAINS             Space- or comma-separated dataset names to run.
#                       Choices: sara_numeric | sara_binary | airline | housing | uscis
#                       (default: sara_numeric). Use DOMAIN= for backwards compatibility.
#   SPLIT               Dataset split: hard | whole  (default: hard)
#   MODELS              Space-separated model names
#                       (default: "Qwen/Qwen3-235B-A22B-Instruct-2507-tput")
#   MODES               Space-separated modes: few-shot | zero-shot | direct
#                       Comma-separated also accepted. (default: all three)
#   NUM_GENERATIONS     Generations per case (default: 2)
#   NUM_EXEMPLARS       Few-shot exemplar count (default: 2 for sara/airline, 1 for housing/uscis)
#   OUTPUT_DIR          Root for output files (default: <repo_root>/outputs)
#   SWIPL_TIMEOUT       Seconds before SWI-Prolog timeout (default: 10)
#   REASONING_EFFORT    Reasoning effort for thinking models: none | low | medium | high (default: medium)
#                       Use "none" for non-thinking variants (e.g. Qwen3-235B-A22B-Instruct-2507-tput)
#   PYTHON              Python executable (default: python)
#
# Output structure (no timestamp — stable for bootstrapping):
#   outputs/<DOMAIN>/few_shot/together_ai/<MODEL>/prolog.json
#   outputs/<DOMAIN>/swipl/few_shot/<SHORT_NAME>-fewshot.txt
#   outputs/<DOMAIN>/direct/together_ai/<MODEL>/source.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${PYTHON:-python}"

# ── API / run settings (shared across all domains) ─────────────────────────────
SPLIT="${SPLIT:-hard}"
API_KEY="${TOGETHER_API_KEY:-}"
BASE_URL="${BASE_URL:-https://api.together.xyz/v1}"
NUM_GENERATIONS="${NUM_GENERATIONS:-2}"
SWIPL_TIMEOUT="${SWIPL_TIMEOUT:-10}"
REASONING_EFFORT="${REASONING_EFFORT:-medium}"
OUTPUT_BASE="${OUTPUT_DIR:-${REPO_ROOT}/outputs}"

# ── Model list ─────────────────────────────────────────────────────────────────
IFS=' ' read -r -a models <<< "${MODELS:-Qwen/Qwen3-235B-A22B-Instruct-2507-tput}"

# ── Validate required inputs ───────────────────────────────────────────────────
if [ -z "${API_KEY}" ]; then
    echo "Error: TOGETHER_API_KEY is required."
    exit 1
fi

# ── Mode parsing (once, shared across domains) ─────────────────────────────────
MODES_INPUT="${MODES:-}"
if [ -z "${MODES_INPUT}" ]; then
    MODES_DEFAULT="few-shot zero-shot direct"
else
    MODES_DEFAULT="${MODES_INPUT}"
fi
MODES_RAW="${MODES_DEFAULT//,/ }"
IFS=' ' read -r -a MODE_INPUT <<< "${MODES_RAW}"
MODE_LIST=()
for mode in "${MODE_INPUT[@]}"; do
    case "${mode}" in
        few-shot)             MODE_LIST+=("few-shot") ;;
        standalone|zero-shot) MODE_LIST+=("standalone") ;;
        direct)               MODE_LIST+=("direct") ;;
        "")                   ;;
        *) echo "Unknown mode '${mode}'. Use: few-shot, zero-shot, direct."; exit 1 ;;
    esac
done

has_mode() {
    local target="$1"
    for m in "${MODE_LIST[@]}"; do [ "${m}" = "${target}" ] && return 0; done
    return 1
}

# ── Helper: short model name ───────────────────────────────────────────────────
get_short_name() {
    local m="$1"
    local n
    n=$(basename "$m")
    n=$(echo "$n" | sed 's/-[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}$//')
    echo "$n"
}

# ── Domain list ────────────────────────────────────────────────────────────────
# Accept DOMAINS (plural) or fall back to DOMAIN (singular) for backwards compat.
DOMAINS_RAW="${DOMAINS:-${DOMAIN:-sara_numeric}}"
IFS=' ' read -r -a domain_list <<< "${DOMAINS_RAW//,/ }"
CASES_PATH_OVERRIDE="${CASES_PATH:-}"

# ── Per-domain loop ────────────────────────────────────────────────────────────
for DOMAIN in "${domain_list[@]}"; do

    # ── Dataset-specific paths ─────────────────────────────────────────────────
    case "${DOMAIN}" in
        sara_numeric|sara_binary)
            DATA_DIR="${REPO_ROOT}/data/sara_numeric"
            [ "${DOMAIN}" = "sara_binary" ] && DATA_DIR="${REPO_ROOT}/data/sara_binary"
            STATUTES_PATH="${REPO_ROOT}/statutes/sara"
            ;;
        airline)
            DATA_DIR="${REPO_ROOT}/data/airline"
            STATUTES_PATH="${REPO_ROOT}/statutes/airline"
            ;;
        housing)
            DATA_DIR="${REPO_ROOT}/data/housing"
            STATUTES_PATH=""
            ;;
        uscis)
            DATA_DIR="${REPO_ROOT}/data/uscis-aao"
            STATUTES_PATH=""
            ;;
        *)
            echo "Error: Unknown DOMAIN '${DOMAIN}'. Use: sara_numeric, sara_binary, airline, housing, uscis"
            exit 1
            ;;
    esac
    CASES_PATH="${CASES_PATH_OVERRIDE:-${DATA_DIR}/${SPLIT}.json}"

    # ── Default num_exemplars ──────────────────────────────────────────────────
    if [ -z "${NUM_EXEMPLARS:-}" ]; then
        case "${DOMAIN}" in
            housing|uscis) NUM_EXEMPLARS=1 ;;
            *)             NUM_EXEMPLARS=2 ;;
        esac
    fi

    # ── Output directory layout (no timestamp — stable for bootstrapping) ───────
    RUN_ROOT="${OUTPUT_BASE}/${DOMAIN}"
    FEWSHOT_LLM_OUT="${RUN_ROOT}/few_shot/together_ai"
    ZEROSHOT_LLM_OUT="${RUN_ROOT}/zero_shot/together_ai"
    FEWSHOT_PROLOG_DIR="${RUN_ROOT}/processed_prolog/few_shot"
    ZEROSHOT_PROLOG_DIR="${RUN_ROOT}/processed_prolog/zero_shot"
    FEWSHOT_SWIPL_DIR="${RUN_ROOT}/swipl/few_shot"
    ZEROSHOT_SWIPL_DIR="${RUN_ROOT}/swipl/zero_shot"
    DIRECT_LLM_OUT="${RUN_ROOT}/direct/together_ai"

    has_mode "few-shot"   && mkdir -p "${FEWSHOT_SWIPL_DIR}"
    has_mode "standalone" && mkdir -p "${ZEROSHOT_SWIPL_DIR}"

    # ── Statutes arg (omit if empty) ───────────────────────────────────────────
    statutes_args=()
    if [ -n "${STATUTES_PATH}" ]; then
        statutes_args=(--statutes-path "${STATUTES_PATH}")
    fi

    FEWSHOT_OUTPUTS=()
    ZEROSHOT_OUTPUTS=()
    DIRECT_OUTPUTS=()

    # ── Per-model loop ─────────────────────────────────────────────────────────
    for model in "${models[@]}"; do
        short_name=$(get_short_name "$model")

        echo "======================================"
        echo "Model : ${model} (${short_name})"
        echo "Domain: ${DOMAIN} | Split: ${SPLIT}"
        echo "Modes : ${MODES_RAW} | Gens: ${NUM_GENERATIONS} | Exemplars: ${NUM_EXEMPLARS}"
        echo "======================================"

        # ── Few-shot Prolog ────────────────────────────────────────────────────
        if has_mode "few-shot"; then
            fewshot_out="${FEWSHOT_SWIPL_DIR}/${short_name}-fewshot.txt"
            if (
                set -euo pipefail
                echo "--- Few-shot Prolog generation ---"
                $PYTHON "${REPO_ROOT}/scripts/generate_e2e.py" \
                    "${statutes_args[@]}" \
                    --cases-path    "${CASES_PATH}" \
                    --output-path   "${FEWSHOT_LLM_OUT}/${model}" \
                    --api-base-url  "${BASE_URL}" \
                    --api-key       "${API_KEY}" \
                    --num-generations "${NUM_GENERATIONS}" \
                    --num-exemplars "${NUM_EXEMPLARS}" \
                    --model-name    "${model}" \
                    --dataset       "${DOMAIN}" \
                    --reasoning-effort "${REASONING_EFFORT}" \
                    --task prolog
                $PYTHON "${REPO_ROOT}/scripts/process_generated_prolog.py" \
                    --dataset       "${DOMAIN}" \
                    --llm-output    "${FEWSHOT_LLM_OUT}/${model}/prolog.json" \
                    --save-dir      "${FEWSHOT_PROLOG_DIR}/${model}"
                echo "--- Running SWI-Prolog (few-shot) ---"
                TIMEOUT_DURATION="${SWIPL_TIMEOUT}" bash "${REPO_ROOT}/scripts/run_swipl.sh" \
                    "${FEWSHOT_PROLOG_DIR}/${model}" > "${fewshot_out}"
                echo "Few-shot results: ${fewshot_out}"
            ); then
                FEWSHOT_OUTPUTS+=("${fewshot_out}")
            else
                echo "WARNING: few-shot mode failed for ${model} — continuing with other modes."
            fi
        fi

        # ── Zero-shot (standalone) Prolog ──────────────────────────────────────
        if has_mode "standalone"; then
            zeroshot_out="${ZEROSHOT_SWIPL_DIR}/${short_name}-zeroshot.txt"
            if (
                set -euo pipefail
                echo "--- Zero-shot Prolog generation ---"
                $PYTHON "${REPO_ROOT}/scripts/generate_e2e.py" \
                    "${statutes_args[@]}" \
                    --cases-path    "${CASES_PATH}" \
                    --output-path   "${ZEROSHOT_LLM_OUT}/${model}" \
                    --api-base-url  "${BASE_URL}" \
                    --api-key       "${API_KEY}" \
                    --num-generations "${NUM_GENERATIONS}" \
                    --num-exemplars "${NUM_EXEMPLARS}" \
                    --model-name    "${model}" \
                    --dataset       "${DOMAIN}" \
                    --reasoning-effort "${REASONING_EFFORT}" \
                    --task standalone
                $PYTHON "${REPO_ROOT}/scripts/process_generated_prolog.py" \
                    --dataset       "${DOMAIN}" \
                    --llm-output    "${ZEROSHOT_LLM_OUT}/${model}/standalone_prolog.json" \
                    --save-dir      "${ZEROSHOT_PROLOG_DIR}/${model}" \
                    --standalone
                echo "--- Running SWI-Prolog (zero-shot) ---"
                TIMEOUT_DURATION="${SWIPL_TIMEOUT}" bash "${REPO_ROOT}/scripts/run_swipl.sh" \
                    "${ZEROSHOT_PROLOG_DIR}/${model}" > "${zeroshot_out}"
                echo "Zero-shot results: ${zeroshot_out}"
            ); then
                ZEROSHOT_OUTPUTS+=("${zeroshot_out}")
            else
                echo "WARNING: zero-shot mode failed for ${model} — continuing with other modes."
            fi
        fi

        # ── Direct answer ──────────────────────────────────────────────────────
        if has_mode "direct"; then
            if (
                set -euo pipefail
                echo "--- Direct answer generation ---"
                $PYTHON "${REPO_ROOT}/scripts/generate_e2e.py" \
                    "${statutes_args[@]}" \
                    --cases-path    "${CASES_PATH}" \
                    --output-path   "${DIRECT_LLM_OUT}/${model}" \
                    --api-base-url  "${BASE_URL}" \
                    --api-key       "${API_KEY}" \
                    --num-generations "${NUM_GENERATIONS}" \
                    --num-exemplars "${NUM_EXEMPLARS}" \
                    --model-name    "${model}" \
                    --dataset       "${DOMAIN}" \
                    --reasoning-effort "${REASONING_EFFORT}" \
                    --task direct
            ); then
                DIRECT_OUTPUTS+=("${DIRECT_LLM_OUT}/${model}/source.json")
            else
                echo "WARNING: direct mode failed for ${model} — continuing with other modes."
            fi
        fi

        echo ""
    done

    # ── Per-domain summary ─────────────────────────────────────────────────────
    echo ""
    echo "======================================"
    echo "Domain complete: ${DOMAIN}"
    echo "Output root: ${RUN_ROOT}"
    echo "======================================"
    if [ ${#FEWSHOT_OUTPUTS[@]} -gt 0 ]; then
        echo ""
        echo "# Few-shot SWI-Prolog result files:"
        for f in "${FEWSHOT_OUTPUTS[@]}"; do echo "  ${f}"; done
    fi
    if [ ${#ZEROSHOT_OUTPUTS[@]} -gt 0 ]; then
        echo ""
        echo "# Zero-shot SWI-Prolog result files:"
        for f in "${ZEROSHOT_OUTPUTS[@]}"; do echo "  ${f}"; done
    fi
    if [ ${#DIRECT_OUTPUTS[@]} -gt 0 ]; then
        echo ""
        echo "# Direct answer JSON files:"
        for f in "${DIRECT_OUTPUTS[@]}"; do echo "  ${f}"; done
    fi
    echo ""

done
