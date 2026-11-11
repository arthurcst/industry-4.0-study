#!/usr/bin/env bash
# Wrapper: evita bug de import no WSL ao rodar scripts/setup_experiment.py
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

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

if "$PYTHON" -I "$ROOT/scripts/setup_experiment.py" "$@"; then
  exit 0
fi

echo "⚠️  Setup via Python local falhou; tentando via container stream-consumer..."
exec docker compose run --rm --no-deps \
  -v "$ROOT/scripts/setup_experiment.py:/app/scripts/setup_experiment.py:ro" \
  stream-consumer python -I /app/scripts/setup_experiment.py "$@"
