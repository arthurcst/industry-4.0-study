# tcc_comparativo

Comparativo **stream vs batch** para ingestão de dados IoT industrial (TCC Indústria 4.0).

## Arquitetura

```
Sensores (MQTT)
    │
    ├── Stream ──► async_consumer_v2.py ──► InfluxDB (micro-batch, ~500 ms)
    │
    └── Batch ───► batch_consumer.py ──► CSV ──► cron (5 min) ──► cronjob_executor.py ──► PostgreSQL
```

| Abordagem | Destino | Latência típica |
|-----------|---------|-----------------|
| Stream | InfluxDB (`iot_stream_{perfil}`) | ~1–15 ms |
| Batch | PostgreSQL (`sensor_data_{perfil}`) | ~1–5 min (janela do cron) |

### Perfis de carga

| Perfil | `RATE_MODIFIER` | Postgres | InfluxDB |
|--------|-----------------|----------|----------|
| `1x` | 1 | `sensor_data_1x` | `iot_stream_1x` |
| `2x` | 2 | `sensor_data_2x` | `iot_stream_2x` |
| `4x` | 4 | `sensor_data_4x` | `iot_stream_4x` |

### Saída por run

Cada execução cria uma pasta timestampada em `runs/`:

```
runs/experimento_1x_YYYY_MM_DD_HH_MM/
├── batches_output_1x/       # CSVs aguardando processamento
├── batches_processed_1x/    # CSVs já ingeridos no PG
└── metrics/
    ├── docker_stats_1x.csv       # CPU, RAM, rede por container
    ├── summary_1x.json / .csv    # Totais PG/Influx, latência, throughput
    ├── batch_throughput_1x.csv   # Throughput por arquivo CSV
    └── latency_hist_1x.json      # Histogramas de latência (batch + stream)
```

---

## Como executar

### Experimento único

```bash
./start_experiment.sh 1x          # execução normal (dados acumulam)
./start_experiment.sh 1x truncate # limpa PG + Influx antes de iniciar
```

O script faz tudo em sequência:
1. Ativa o perfil (`docker.env`)
2. Cria a pasta `runs/experimento_{perfil}_YYYY_MM_DD_HH_MM/`
3. `docker compose build` + sobe infra e consumidores
4. Cria tabela PG e bucket InfluxDB (`setup_experiment.py`)
5. Inicia coleta de `docker stats` em background
6. Roda o gerador por **1 hora**
7. Aguarda 10 min de buffer (cron processa os últimos CSVs)
8. Exporta métricas (`export_experiment_metrics.py`)
9. Para o gerador; Postgres, Influx, Grafana e consumidores **continuam rodando**

### Série completa (9 runs — 3 por workload)

```bash
./run_all_experiments.sh                   # 3 × (1x, 2x, 4x) = 9 runs (~11 horas)
./run_all_experiments.sh --workloads 2x,4x # só 2x e 4x
./run_all_experiments.sh --runs 1          # 1 run por workload
./run_all_experiments.sh --dry-run         # valida a sequência sem executar
```

Logs individuais e master log salvos em `logs/`.

---

## Variáveis principais (`docker.env`)

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `EXPERIMENT_LABEL` | `1x` | Identificador do perfil |
| `EXECUTION_TIME_SECONDS` | `3600` | Duração do gerador |
| `RATE_MODIFIER` | `1` | Multiplicador de taxa de publicação |
| `PG_TABLE` | `sensor_data_1x` | Tabela destino no PostgreSQL |
| `INFLUXDB_BUCKET` | `iot_stream_1x` | Bucket destino no InfluxDB |
| `BATCH_OUTPUT_HOST` | — | Pasta no host para CSVs pendentes |
| `BATCH_PROCESSED_HOST` | — | Pasta no host para CSVs processados |
| `STREAM_WORKER_COUNT` | `1` / `4` / `6` | Workers paralelos (1x / 2x / 4x) |
| `INFLUX_BATCH_SIZE` | `5000` | Pontos por lote no flush do InfluxDB |
| `INFLUX_FLUSH_INTERVAL_MS` | `500` | Flush forçado a cada N ms |

---

## Grafana

Após subir o stack, acesse **http://localhost:3000** (`admin` / `admin`).

O dashboard **TCC — Stream vs Batch** exibe registros/s, latência e throughput de ambos os pipelines em tempo real. Datasources e dashboard são provisionados automaticamente via `grafana/provisioning/`.
