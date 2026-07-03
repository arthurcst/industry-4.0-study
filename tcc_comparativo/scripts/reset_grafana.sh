#!/usr/bin/env bash
# Remove volume grafana_data (estado corrompido após upgrade para Grafana 13+).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "🛑 Parando Grafana..."
docker compose rm -sf grafana 2>/dev/null || true
docker rm -f grafana 2>/dev/null || true

VOLUME="${COMPOSE_PROJECT_NAME:-tcc_comparativo}_grafana_data"
if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo "🗑️  Removendo volume $VOLUME ..."
  docker volume rm "$VOLUME"
else
  echo "ℹ️  Volume $VOLUME não encontrado (já removido ou nome diferente)."
  docker volume ls | grep grafana || true
fi

echo "🚀 Subindo Grafana (provisionamento limpo)..."
docker compose up -d grafana

echo "✅ Pronto. Acesse http://localhost:3000 (admin/admin)"
