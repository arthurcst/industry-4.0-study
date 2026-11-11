#!/usr/bin/env bash
# Orquestra experimento completo: build → up → setup → gerador → stats → export
# Ao final mantém a infraestrutura no ar e encerra gerador e consumidores.
#
# Uso: ./start_experiment.sh {reduzida|intermediaria|completa} [--seed N]

set -euo pipefail

PROFILE="${1:-}"
shift || true
RUN_SEED=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --seed) RUN_SEED="${2:-}"; shift 2 ;;
    *) echo "Uso: $0 {reduzida|intermediaria|completa} [--seed N]"; exit 1 ;;
  esac
done

if [[ ! "$PROFILE" =~ ^(reduzida|intermediaria|completa)$ ]]; then
  echo "Uso: $0 {reduzida|intermediaria|completa} [--seed N]"
  exit 1
fi

if [[ -n "$RUN_SEED" && ! "$RUN_SEED" =~ ^[0-9]+$ ]]; then
  echo "A seed deve conter apenas dígitos"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

COLLECT_PID=""

stop_generator() {
  docker compose stop sensor-generator 2>/dev/null || true
}

cleanup() {
  local exit_code=$?
  if [[ -n "$COLLECT_PID" ]] && kill -0 "$COLLECT_PID" 2>/dev/null; then
    echo ""
    echo "⏹️  Encerrando coleta de stats (PID $COLLECT_PID)..."
    kill "$COLLECT_PID" 2>/dev/null || true
    wait "$COLLECT_PID" 2>/dev/null || true
  fi
  echo "⏹️  Garantindo sensor-generator parado..."
  stop_generator
  trap - EXIT
  exit "$exit_code"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

PYTHON=""
for cmd in "$ROOT/.venv/Scripts/python.exe" "$ROOT/.venv/bin/python" python3 python; do
  if command -v "$cmd" >/dev/null 2>&1; then
    PYTHON="$cmd"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "❌ Python não encontrado (python3/python)"
  exit 1
fi
if ! "$PYTHON" -I -c 'import psycopg2, influxdb_client, dotenv' >/dev/null 2>&1; then
  echo "❌ Dependências Python para setup e exportação não estão disponíveis"
  exit 1
fi

echo "══════════════════════════════════════════════"
echo " 🚀 Experimento TCC — perfil ${PROFILE}"
echo "══════════════════════════════════════════════"

# 1. Ativar perfil
bash "$ROOT/scripts/switch_experiment.sh" "$PROFILE" >/dev/null
if [[ -n "$RUN_SEED" ]]; then
  sed -i "s|^EXPERIMENT_SEED=.*|EXPERIMENT_SEED=$RUN_SEED|" "$ROOT/docker.env" "$ROOT/.env"
fi
if [[ -n "${EXPERIMENT_TEST_DURATION_SECONDS:-}" ]]; then
  [[ "$EXPERIMENT_TEST_DURATION_SECONDS" =~ ^[0-9]+$ ]] || exit 1
  sed -i "s|^EXECUTION_TIME_SECONDS=.*|EXECUTION_TIME_SECONDS=$EXPERIMENT_TEST_DURATION_SECONDS|" "$ROOT/docker.env" "$ROOT/.env"
fi

# 1b. Pasta timestampada deste run (batches, processed, metrics)
bash "$ROOT/scripts/init_experiment_run.sh" "$PROFILE"

run_python_script() {
  "$PYTHON" -I -X utf8 "$@"
}

if [[ -n "${EXPERIMENT_MANIFEST:-}" ]]; then
  run_python_script "$ROOT/scripts/environment_manifest.py" check "$EXPERIMENT_MANIFEST"
fi

run_setup_experiment() {
  local setup_args=("$@")
  if run_python_script "$ROOT/scripts/setup_experiment.py" "${setup_args[@]}"; then
    return 0
  fi
  echo ""
  echo "⚠️  Setup via Python local falhou; tentando via container stream-consumer..."
  docker compose run --rm --no-deps \
    -v "$ROOT/scripts/setup_experiment.py:/app/scripts/setup_experiment.py:ro" \
    stream-consumer python -I /app/scripts/setup_experiment.py "${setup_args[@]}"
}

# shellcheck disable=SC1091
set -a
source "$ROOT/docker.env"
set +a

mkdir -p "$ROOT/${BATCH_OUTPUT_HOST#./}" "$ROOT/${BATCH_PROCESSED_HOST#./}" "$ROOT/${METRICS_HOST#./}"
grep -E '^(EXPERIMENT_LABEL|EXPERIMENT_SEED|EXECUTION_TIME_SECONDS|ACTIVE_ASSET_COUNT|PG_TABLE|INFLUXDB_BUCKET|MQTT_DATA_VOLUME|MQTT_BROKER|MQTT_PORT|MQTT_TOPIC|MQTT_QOS|MQTT_MAX_INFLIGHT|BATCH_THRESHOLD|BATCH_FLUSH_INTERVAL|STREAM_QUEUE_MAXSIZE|STREAM_DRAIN_BATCH_SIZE|STREAM_DRAIN_TIMEOUT_S|STREAM_WORKER_COUNT|STREAM_METRICS_LOG_INTERVAL_S|INFLUX_BATCH_SIZE|INFLUX_FLUSH_INTERVAL_MS)=' "$ROOT/docker.env" > "$ROOT/${METRICS_HOST#./}/parameters.env"

# 2. Build
echo ""
if [[ "${EXPERIMENT_REUSE_IMAGES:-0}" == 1 ]]; then
  echo "🔨 Usando as imagens já existentes..."
  docker image inspect tcc_comparativo-batch-consumer:latest tcc_comparativo-stream-consumer:latest tcc_comparativo-sensor-generator:latest >/dev/null
else
  echo "🔨 Build das imagens..."
  docker compose build batch-consumer stream-consumer sensor-generator
fi

# 3. Subir infra + consumidores
echo ""
echo "🐳 Subindo infraestrutura..."
docker compose up -d postgres influxdb mosquitto grafana

echo "⏳ Aguardando Postgres..."
ready=0
for _ in $(seq 1 60); do
  if docker exec postgres pg_isready -U grafana -d iot_batch >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" -eq 1 ]] || { echo "❌ PostgreSQL indisponível"; exit 1; }

echo "⏳ Aguardando InfluxDB..."
ready=0
for _ in $(seq 1 60); do
  if curl -sf http://localhost:8086/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" -eq 1 ]] || { echo "❌ InfluxDB indisponível"; exit 1; }

ready=0
for _ in $(seq 1 60); do
  if docker exec mosquitto mosquitto_pub -h localhost -t __healthcheck__ -m ready -q 1 >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" -eq 1 ]] || { echo "❌ Broker MQTT indisponível"; exit 1; }

# 4. Setup tabela PG + bucket Influx (opcional: truncate)
echo ""
echo "🗄️  Setup do experimento..."
run_setup_experiment

# 5. Recriar consumidores com env/volumes atualizados
echo ""
echo "🔄 Recriando consumidores..."
docker compose up -d --force-recreate batch-consumer stream-consumer
for container in batch_consumer stream_consumer; do
  ready=0
  for _ in $(seq 1 60); do
    if docker logs "$container" 2>&1 | grep -q MQTT_SUBSCRIBED; then
      ready=1
      break
    fi
    [[ "$(docker inspect -f '{{.State.Running}}' "$container")" == true ]] || break
    sleep 1
  done
  [[ "$ready" -eq 1 ]] || { echo "❌ $container não confirmou inscrição MQTT"; exit 1; }
done

# 6. Coleta de stats em background (dura EXECUTION_TIME + EXTRA_SECONDS)
echo ""
if [[ -n "${EXPERIMENT_MANIFEST:-}" ]]; then
  run_python_script "$ROOT/scripts/environment_manifest.py" snapshot "$ROOT/${METRICS_HOST#./}/host_before.json"
fi
echo "📊 Iniciando coleta Docker stats em background..."
bash "$ROOT/scripts/collect_docker_stats.sh" &
COLLECT_PID=$!
echo "   PID coleta: $COLLECT_PID"

# 7. Gerador (foreground — encerra após EXECUTION_TIME_SECONDS)
echo ""
echo "📡 Iniciando gerador de sensores (${EXECUTION_TIME_SECONDS}s)..."
docker compose up -d --no-deps --force-recreate sensor-generator
docker inspect -f '{{.Name}} {{.Image}}' batch_consumer stream_consumer sensor_generator > "$ROOT/${METRICS_HOST#./}/images.txt"
if [[ -n "${EXPERIMENT_MANIFEST:-}" ]]; then
  run_python_script "$ROOT/scripts/environment_manifest.py" check-running "$EXPERIMENT_MANIFEST"
fi
GENERATOR_EXIT="$(timeout "$((EXECUTION_TIME_SECONDS + 300))s" docker wait sensor_generator)" || {
  echo "❌ Gerador não terminou no prazo esperado"
  exit 1
}
docker logs sensor_generator > "$ROOT/${METRICS_HOST#./}/generator.log" 2>&1
docker inspect -f '{{.State.StartedAt}} {{.State.FinishedAt}}' sensor_generator > "$ROOT/${METRICS_HOST#./}/generator_window.txt"
[[ "$GENERATOR_EXIT" == 0 ]] || { echo "❌ Gerador terminou com código $GENERATOR_EXIT"; exit 1; }

echo "⏳ Aguardando processamento dos últimos registros..."
sleep "${COLLECT_EXTRA_SECONDS:-600}"

# 8. Aguardar coleta terminar (inclui buffer pós-gerador para o cron)
echo ""
echo "⏳ Aguardando coleta de stats finalizar..."
wait "$COLLECT_PID"
COLLECT_PID=""

docker compose stop -t 60 batch-consumer stream-consumer
docker logs batch_consumer > "$ROOT/${METRICS_HOST#./}/batch.log" 2>&1
docker logs stream_consumer > "$ROOT/${METRICS_HOST#./}/stream.log" 2>&1
for container in batch_consumer stream_consumer; do
  code="$(docker inspect -f '{{.State.ExitCode}}' "$container")"
  [[ "$code" == 0 ]] || { echo "❌ $container terminou com código $code"; exit 1; }
done

# 9. Export resumo
echo ""
echo "📤 Exportando métricas..."
run_python_script "$ROOT/scripts/export_experiment_metrics.py"
run_python_script "$ROOT/scripts/audit_clock.py" "$ROOT/${METRICS_HOST#./}"
run_python_script "$ROOT/scripts/audit_resource_coverage.py" "$ROOT/${METRICS_HOST#./}" "$EXPERIMENT_LABEL"
run_python_script "$ROOT/scripts/validate_experiment.py" "$ROOT/${METRICS_HOST#./}" "$EXPERIMENT_LABEL"
run_python_script "$ROOT/scripts/audit_workload.py" "$ROOT/${METRICS_HOST#./}" "$EXPERIMENT_LABEL"

echo ""
echo "══════════════════════════════════════════════"
echo " ✅ Experimento ${EXPERIMENT_LABEL} concluído"
echo "    ${EXPERIMENT_RUN_DIR}/metrics/docker_stats_${EXPERIMENT_LABEL}.csv"
echo "    ${EXPERIMENT_RUN_DIR}/metrics/summary_${EXPERIMENT_LABEL}.json"
echo "    Infra ainda rodando (Grafana, PG e Influx); consumidores parados"
echo "══════════════════════════════════════════════"

# cleanup via trap: para coleta + sensor-generator; não derruba a stack
