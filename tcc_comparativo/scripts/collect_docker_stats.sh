#!/usr/bin/env bash
# Coleta métricas de recursos Docker durante o experimento.
# Saída: ${METRICS_HOST}/docker_stats_{EXPERIMENT_LABEL}.csv

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/docker.env"
INTERVAL="${COLLECT_INTERVAL:-0.5}"
EXTRA_SECONDS="${COLLECT_EXTRA_SECONDS:-600}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "$ENV_FILE"
  set +a
fi

if [[ -n "${METRICS_HOST:-}" ]]; then
  METRICS_DIR="$ROOT/${METRICS_HOST#./}"
elif [[ -n "${EXPERIMENT_RUN_DIR:-}" ]]; then
  METRICS_DIR="$ROOT/${EXPERIMENT_RUN_DIR}/metrics"
else
  METRICS_DIR="$ROOT/metrics"
fi

LABEL="${EXPERIMENT_LABEL:-completa}"
EXECUTION_TIME="${EXECUTION_TIME_SECONDS:-3600}"
DURATION="${COLLECT_DURATION_SECONDS:-$((EXECUTION_TIME + EXTRA_SECONDS))}"
OUT_FILE="$METRICS_DIR/docker_stats_${LABEL}.csv"

mkdir -p "$METRICS_DIR"

echo "timestamp,experiment,container_id,name,cpu_perc,mem_usage,mem_perc,net_io,block_io,pids" > "$OUT_FILE"
echo "📊 Coletando Docker stats → $OUT_FILE"
echo "   Perfil: $LABEL | Intervalo: ${INTERVAL}s | Duração: ${DURATION}s"
echo "   Ctrl+C para parar antes do tempo"

start_epoch=$(date +%s)
end_epoch=$((start_epoch + DURATION))

while true; do
  now_epoch=$(date +%s)
  if (( now_epoch >= end_epoch )); then
    echo "✅ Coleta finalizada (${DURATION}s)"
    break
  fi

  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  mapfile -t containers < <(docker compose -f "$ROOT/docker-compose.yml" ps -q 2>/dev/null || true)

  if ((${#containers[@]} == 0)); then
    mapfile -t containers < <(
      docker ps --filter "name=batch_consumer" --filter "name=stream_consumer" \
        --filter "name=sensor_generator" --filter "name=postgres" \
        --filter "name=influxdb" --filter "name=mosquitto" --filter "name=grafana" -q
    )
  fi

  if ((${#containers[@]} > 0)); then
    for attempt in 1 2 3; do
      if sample="$(docker stats --no-stream --format "{{.Container}},{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}},{{.PIDs}}" "${containers[@]}")"; then
        while IFS= read -r line; do
          [[ -n "$line" ]] && echo "$timestamp,$LABEL,$line" >> "$OUT_FILE"
        done <<< "$sample"
        break
      fi
      echo "⚠️ Falha ao coletar recursos (tentativa $attempt/3)" >&2
      if (( attempt == 3 )); then exit 1; fi
      sleep 2
    done
  fi

  sleep "$INTERVAL"
done
