#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-}"
if [[ ! "$PROFILE" =~ ^(reduzida|intermediaria|completa)$ ]]; then
    echo "Uso: $0 {reduzida|intermediaria|completa}"
    exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/docker.env.$PROFILE"

cp "$SOURCE" "$ROOT/docker.env"
cp "$SOURCE" "$ROOT/.env"

echo "✅ Experimento $PROFILE ativado"
echo ""
echo "Próximos passos:"
echo "  1. docker compose up -d postgres influxdb mosquitto grafana batch-consumer stream-consumer"
echo "  2. python scripts/setup_experiment.py"
echo "  4. docker compose up -d --force-recreate batch-consumer stream-consumer"
echo "  5. docker compose up sensor-generator"
echo ""
grep -E "^(EXPERIMENT_LABEL|PG_TABLE|INFLUXDB_BUCKET|ACTIVE_ASSET_COUNT|EXPERIMENT_SEED|BATCH_OUTPUT_HOST)=" "$ROOT/docker.env" | sed 's/^/   /'
