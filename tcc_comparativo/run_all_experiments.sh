#!/usr/bin/env bash
# Executa todos os experimentos TCC em sequência: 3 runs × (reduzida, intermediaria, completa) = 9 runs
# Cada execução usa tabela e bucket próprios.
#
# Uso: ./run_all_experiments.sh [--workloads reduzida,intermediaria,completa] [--runs 3] [--start-run 1] [--dry-run]
#
# Exemplos:
#   ./run_all_experiments.sh                         # sequência completa (9 runs)
#   ./run_all_experiments.sh --workloads completa                 # só 3 runs de planta completa
#   ./run_all_experiments.sh --workloads reduzida,intermediaria  # 3 runs de cada cenário
#   ./run_all_experiments.sh --runs 1                # 1 run por workload

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ── Defaults ──────────────────────────────────────────────────────────────────
WORKLOADS_ARG="reduzida,intermediaria,completa"
RUNS_PER_WORKLOAD=3
FIRST_RUN=1
DRY_RUN=0
REPLICA_SEEDS=(20261101 20261102 20261103)

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workloads) WORKLOADS_ARG="$2"; shift 2 ;;
    --runs)      RUNS_PER_WORKLOAD="$2"; shift 2 ;;
    --start-run) FIRST_RUN="$2"; shift 2 ;;
    --dry-run)   DRY_RUN=1; shift ;;
    *) echo "Argumento desconhecido: $1"; exit 1 ;;
  esac
done

IFS=',' read -ra WORKLOADS <<< "$WORKLOADS_ARG"
if [[ ! "$RUNS_PER_WORKLOAD" =~ ^[1-3]$ || ! "$FIRST_RUN" =~ ^[1-3]$ ]] || (( FIRST_RUN > RUNS_PER_WORKLOAD )); then
  echo "A faixa de réplicas deve estar entre 1 e ${#REPLICA_SEEDS[@]}"
  exit 1
fi
TOTAL=$(( ${#WORKLOADS[@]} * (RUNS_PER_WORKLOAD - FIRST_RUN + 1) ))
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
MASTER_LOG="$LOG_DIR/run_all_${TIMESTAMP}.log"

# ── Helpers ───────────────────────────────────────────────────────────────────
log() { echo "$*" | tee -a "$MASTER_LOG"; }
hr()  { log "══════════════════════════════════════════════════════════"; }

elapsed_since() {
  local start=$1
  local now; now=$(date +%s)
  local diff=$(( now - start ))
  printf "%02d:%02d:%02d" $(( diff/3600 )) $(( (diff%3600)/60 )) $(( diff%60 ))
}

# ── Plano de execução ─────────────────────────────────────────────────────────
hr
log " 🧪 TCC — Execução completa dos experimentos"
log "    Workloads : ${WORKLOADS[*]}"
log "    Réplicas por cenário: $FIRST_RUN a $RUNS_PER_WORKLOAD"
log "    Total de runs: $TOTAL"
log "    Log mestre  : $MASTER_LOG"
if [[ $DRY_RUN -eq 1 ]]; then
  log "    ⚠️  DRY-RUN — nenhum experimento será executado"
fi
hr
log ""

GLOBAL_START=$(date +%s)
RUN_NUMBER=0
FAILURES=()

for WL in "${WORKLOADS[@]}"; do
  if [[ ! "$WL" =~ ^(reduzida|intermediaria|completa)$ ]]; then
    log "❌ Cenário inválido: $WL (use reduzida, intermediaria ou completa)"
    exit 1
  fi

  hr
  log " 📦 Workload: $WL  (${RUNS_PER_WORKLOAD} run(s))"
  hr

  for (( R=FIRST_RUN; R<=RUNS_PER_WORKLOAD; R++ )); do
    RUN_NUMBER=$(( RUN_NUMBER + 1 ))
    RUN_START=$(date +%s)
    RUN_LOG="$LOG_DIR/run_${WL}_${R}_${TIMESTAMP}.log"
    RUN_SEED="${REPLICA_SEEDS[$((R - 1))]}"

    log ""
    log " ▶  [$RUN_NUMBER/$TOTAL]  Workload=$WL  Run=$R/$RUNS_PER_WORKLOAD"
    log "    Seed   : $RUN_SEED"
    log "    Início : $(date '+%Y-%m-%d %H:%M:%S')"
    log "    Log    : $RUN_LOG"

    if [[ $DRY_RUN -eq 1 ]]; then
      log "    (dry-run) saltando ./start_experiment.sh $WL --seed $RUN_SEED"
      continue
    fi

    set +e
    bash "$ROOT/start_experiment.sh" "$WL" --seed "$RUN_SEED" 2>&1 | tee -a "$RUN_LOG" "$MASTER_LOG"
    EXIT_CODE=${PIPESTATUS[0]}
    set -e

    ELAPSED=$(elapsed_since "$RUN_START")
    if [[ $EXIT_CODE -eq 0 ]]; then
      log ""
      log " ✅ [$RUN_NUMBER/$TOTAL]  $WL run $R concluído  (duração: $ELAPSED)"
    else
      log ""
      log " ❌ [$RUN_NUMBER/$TOTAL]  $WL run $R FALHOU (código $EXIT_CODE, duração: $ELAPSED)"
      FAILURES+=("$WL run $R (código $EXIT_CODE)")
      log "    Log completo: $RUN_LOG"
      log "    Ciclo interrompido para preservar os dados desta execução."
      exit "$EXIT_CODE"
    fi

    # Pausa entre runs do mesmo workload para o cron processar os últimos batches
    if [[ $DRY_RUN -eq 0 && $R -lt $RUNS_PER_WORKLOAD ]]; then
      log ""
      log " ⏳ Aguardando 90s antes do próximo run..."
      sleep 90
    fi
  done

  # Pausa maior entre workloads diferentes
  if [[ $DRY_RUN -eq 0 && "$WL" != "${WORKLOADS[-1]}" ]]; then
    log ""
    log " ⏳ Pausa de 120s antes do próximo workload..."
    sleep 120
  fi
done

# ── Resumo final ──────────────────────────────────────────────────────────────
TOTAL_ELAPSED=$(elapsed_since "$GLOBAL_START")
hr
log ""
log " 📋 RESUMO FINAL"
log "    Runs executados : $RUN_NUMBER / $TOTAL"
log "    Duração total   : $TOTAL_ELAPSED"

if [[ ${#FAILURES[@]} -eq 0 ]]; then
  log "    Status          : ✅ Todos os runs concluídos com sucesso"
else
  log "    Status          : ⚠️  ${#FAILURES[@]} run(s) com falha:"
  for F in "${FAILURES[@]}"; do
    log "       - $F"
  done
fi

log ""
log "    Logs individuais em: $LOG_DIR/"
hr
