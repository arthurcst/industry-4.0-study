#!/usr/bin/env bash
# Deprecated — use scripts/collect_docker_stats.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "⚠️  docker_tracker.sh foi movido para scripts/collect_docker_stats.sh"
exec bash "$ROOT/scripts/collect_docker_stats.sh" "$@"
