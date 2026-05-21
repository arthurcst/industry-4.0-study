#!/bin/bash

# Arquivo de saída
OUT_FILE="docker_stats.csv"

# Cabeçalho
echo "timestamp,container_id,name,cpu_perc,mem_usage,mem_perc,net_io,block_io,pids" > "$OUT_FILE"

# Loop infinito para registrar os stats
while true; do
  # Timestamp no formato ISO 8601
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  # Captura e adiciona cada linha com timestamp
  docker stats --no-stream --format "{{.Container}},{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}},{{.PIDs}}" \
    | while IFS= read -r line; do
        echo "$timestamp,$line" >> "$OUT_FILE"
      done

  # Espera 10 segundos antes da próxima coleta
  sleep 0.5
done