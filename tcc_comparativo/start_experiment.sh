#!/usr/bin/env bash
# Orquestra experimento completo: build → up → setup → gerador → stats → export
# Ao final mantém infra/consumidores no ar; só garante sensor-generator parado.
#
# Uso: ./start_experiment.sh {1x|2x|4x} [truncate]
#   truncate — esvazia tabela PG e bucket Influx do perfil antes do run

set -euo pipefail

PROFILE="${1:-}"
TRUNCATE=0
if [[ "${2:-}" == "truncate" ]]; then
  TRUNCATE=1
elif [[ -n "${2:-}" ]]; then
  echo "Uso: $0 {1x|2x|4x} [truncate]"
  exit 1
fi

if [[ ! "$PROFILE" =~ ^(1x|2x|4x)$ ]]; then
  echo "Uso: $0 {1x|2x|4x} [truncate]"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

COLLECT_PID=""
GENERATOR_EXIT=0

stop_generator() {
  docker compose stop sensor-generator 2>/dev/null || true
  docker rm -f sensor_generator 2>/dev/null || true
}

cleanup() {
  local exit_code=$?
  if [[ -n "$COLLECT_PID" ]] && kill -0 "$COLLECT_PID" 2>/dev/null; then
    echo ""
    echo "⏹️  Encerrando coleta de stats (PID $COLLECT_PID)..."
    kill "$COLLECT_PID" 2>/dev/null || true
    wait "$COLLECT_PID" 2>/dev/null || true
  fi
  echo "⏹️  Garantindo sensor-generator parado (demais serviços permanecem no ar)..."
  stop_generator
  exit "${GENERATOR_EXIT:-$exit_code}"
}

trap cleanup EXIT INT TERM

PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" >/dev/null 2>&1; then
    PYTHON="$cmd"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "❌ Python não encontrado (python3/python)"
  exit 1
fi

echo "══════════════════════════════════════════════"
echo " 🚀 Experimento TCC — perfil ${PROFILE}"
if [[ "$TRUNCATE" -eq 1 ]]; then
  echo "    modo: truncate (PG + Influx limpos antes do run)"
fi
echo "══════════════════════════════════════════════"

# 1. Ativar perfil
bash "$ROOT/scripts/switch_experiment.sh" "$PROFILE" >/dev/null

# 1b. Pasta timestampada deste run (batches, processed, metrics)
bash "$ROOT/scripts/init_experiment_run.sh" "$PROFILE"

run_python_script() {
  "$PYTHON" -I "$@"
}

run_setup_experiment() {
  local setup_args=("$@")
  if run_python_script "$ROOT/scripts/setup_experiment.py" "${setup_args[@]}"; then
    return 0
  fi
  echo ""
  echo "⚠️  Setup via Python local falhou; tentando via container stream-consumer..."
  docker compose run --rm --no-deps \
    -v "$ROOT/scripts/setup_experiment.py:/app/scripts/setup_experiment.py:ro" \
    --env-file "$ROOT/docker.env" \
    stream-consumer python -I /app/scripts/setup_experiment.py "${setup_args[@]}"
}

# shellcheck disable=SC1091
set -a
source "$ROOT/docker.env"
set +a

mkdir -p "$ROOT/${BATCH_OUTPUT_HOST#./}" "$ROOT/${BATCH_PROCESSED_HOST#./}" "$ROOT/${METRICS_HOST#./}"

# 2. Build
echo ""
echo "🔨 Build das imagens..."
docker compose build batch-consumer stream-consumer sensor-generator

# 3. Subir infra + consumidores
echo ""
echo "🐳 Subindo infraestrutura..."
docker compose up -d postgres influxdb mosquitto grafana batch-consumer stream-consumer

echo "⏳ Aguardando Postgres..."
for _ in $(seq 1 60); do
  if docker exec postgres pg_isready -U grafana -d iot_batch >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "⏳ Aguardando InfluxDB..."
for _ in $(seq 1 60); do
  if curl -sf http://localhost:8086/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

# 4. Setup tabela PG + bucket Influx (opcional: truncate)
echo ""
if [[ "$TRUNCATE" -eq 1 ]]; then
  echo "🗄️  Setup + truncate do experimento..."
  run_setup_experiment --truncate
else
  echo "🗄️  Setup do experimento..."
  run_setup_experiment
fi

# 5. Recriar consumidores com env/volumes atualizados
echo ""
echo "🔄 Recriando consumidores..."
docker compose up -d --force-recreate batch-consumer stream-consumer

# 6. Coleta de stats em background (dura EXECUTION_TIME + EXTRA_SECONDS)
echo ""
echo "📊 Iniciando coleta Docker stats em background..."
bash "$ROOT/scripts/collect_docker_stats.sh" &
COLLECT_PID=$!
echo "   PID coleta: $COLLECT_PID"

# 7. Gerador (foreground — encerra após EXECUTION_TIME_SECONDS)
echo ""
echo "📡 Iniciando gerador de sensores (${EXECUTION_TIME_SECONDS}s)..."
set +e
docker compose up --abort-on-container-exit sensor-generator
GENERATOR_EXIT=$?
set -e

if [[ "$GENERATOR_EXIT" -ne 0 ]]; then
  echo "⚠️  Gerador terminou com código $GENERATOR_EXIT"
fi

# 8. Aguardar coleta terminar (inclui buffer pós-gerador para o cron)
echo ""
echo "⏳ Aguardando coleta de stats finalizar..."
wait "$COLLECT_PID" 2>/dev/null || true
COLLECT_PID=""

# 9. Export resumo
echo ""
echo "📤 Exportando métricas..."
run_python_script "$ROOT/scripts/export_experiment_metrics.py" || true

echo ""
echo "══════════════════════════════════════════════"
echo " ✅ Experimento ${EXPERIMENT_LABEL} concluído"
echo "    ${EXPERIMENT_RUN_DIR}/metrics/docker_stats_${EXPERIMENT_LABEL}.csv"
echo "    ${EXPERIMENT_RUN_DIR}/metrics/summary_${EXPERIMENT_LABEL}.json"
echo "    Infra ainda rodando (Grafana, PG, Influx, consumidores)"
echo "══════════════════════════════════════════════"

# cleanup via trap: para coleta + sensor-generator; não derruba a stack
