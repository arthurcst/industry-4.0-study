#!/usr/bin/env bash
# Cria pasta timestampada do run e atualiza docker.env / .env com os paths.
# Uso: ./scripts/init_experiment_run.sh {1x|2x|4x}

set -euo pipefail

PROFILE="${1:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! "$PROFILE" =~ ^(1x|2x|4x)$ ]]; then
  echo "Uso: $0 {1x|2x|4x}"
  exit 1
fi

TIMESTAMP="$(date +%Y_%m_%d_%H_%M)"
EXPERIMENT_RUN_DIR="runs/experimento_${PROFILE}_${TIMESTAMP}"

BATCH_OUTPUT_HOST="./${EXPERIMENT_RUN_DIR}/batches_output_${PROFILE}"
BATCH_PROCESSED_HOST="./${EXPERIMENT_RUN_DIR}/batches_processed_${PROFILE}"
METRICS_HOST="./${EXPERIMENT_RUN_DIR}/metrics"

mkdir -p \
  "$ROOT/${BATCH_OUTPUT_HOST#./}" \
  "$ROOT/${BATCH_PROCESSED_HOST#./}" \
  "$ROOT/${METRICS_HOST#./}"

set_env_var() {
  local file="$1" key="$2" value="$3"
  if [[ ! -f "$file" ]]; then
    echo "${key}=${value}" >> "$file"
    return
  fi
  if grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
}

for env_file in "$ROOT/docker.env" "$ROOT/.env"; do
  set_env_var "$env_file" "EXPERIMENT_RUN_DIR" "$EXPERIMENT_RUN_DIR"
  set_env_var "$env_file" "BATCH_OUTPUT_HOST" "$BATCH_OUTPUT_HOST"
  set_env_var "$env_file" "BATCH_PROCESSED_HOST" "$BATCH_PROCESSED_HOST"
  set_env_var "$env_file" "METRICS_HOST" "$METRICS_HOST"
done

echo "📁 Run: ${EXPERIMENT_RUN_DIR}"
echo "   batches → ${BATCH_OUTPUT_HOST}"
echo "   processed → ${BATCH_PROCESSED_HOST}"
echo "   metrics → ${METRICS_HOST}"
