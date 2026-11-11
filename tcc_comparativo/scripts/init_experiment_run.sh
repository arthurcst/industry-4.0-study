#!/usr/bin/env bash
# Cria pasta timestampada do run e atualiza docker.env / .env com os paths.
# Uso: ./scripts/init_experiment_run.sh {reduzida|intermediaria|completa}

set -euo pipefail

PROFILE="${1:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! "$PROFILE" =~ ^(reduzida|intermediaria|completa)$ ]]; then
  echo "Uso: $0 {reduzida|intermediaria|completa}"
  exit 1
fi

TIMESTAMP="$(date +%Y_%m_%d_%H_%M_%S)"
RUN_ROOT="${EXPERIMENT_RUN_ROOT:-runs}"
if [[ ! "$RUN_ROOT" =~ ^runs(/[a-zA-Z0-9_]+)*$ ]]; then
  echo "Diretório de execuções inválido"
  exit 1
fi
EXPERIMENT_RUN_DIR="${RUN_ROOT}/experimento_${PROFILE}_${TIMESTAMP}"
RUN_SUFFIX="${TIMESTAMP//_/}"

mkdir -p "$ROOT/$RUN_ROOT"
mkdir "$ROOT/$EXPERIMENT_RUN_DIR"

BATCH_OUTPUT_HOST="./${EXPERIMENT_RUN_DIR}/batches_output_${PROFILE}"
BATCH_PROCESSED_HOST="./${EXPERIMENT_RUN_DIR}/batches_processed_${PROFILE}"
METRICS_HOST="./${EXPERIMENT_RUN_DIR}/metrics"

mkdir -p \
  "$ROOT/${BATCH_OUTPUT_HOST#./}" \
  "$ROOT/${BATCH_PROCESSED_HOST#./}" \
  "$ROOT/${METRICS_HOST#./}"

touch "$ROOT/${METRICS_HOST#./}/latency_batch.csv" "$ROOT/${METRICS_HOST#./}/latency_stream.csv"

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
  set_env_var "$env_file" "PG_TABLE" "sensor_data_${PROFILE}_${RUN_SUFFIX}"
  set_env_var "$env_file" "INFLUXDB_BUCKET" "iot_stream_${PROFILE}_${RUN_SUFFIX}"
  set_env_var "$env_file" "MQTT_DATA_VOLUME" "tcc_mqtt_${PROFILE}_${RUN_SUFFIX}"
done

echo "📁 Run: ${EXPERIMENT_RUN_DIR}"
echo "   batches → ${BATCH_OUTPUT_HOST}"
echo "   processed → ${BATCH_PROCESSED_HOST}"
echo "   metrics → ${METRICS_HOST}"
