# tcc_comparativo

Comparativo **stream vs batch** para ingestão de dados IoT industrial (TCC Indústria 4.0).

## Arquitetura

```
Sensores (MQTT)
    │
    ├── Stream ──► async_consumer_v2.py ──► InfluxDB (escrita síncrona por retirada da fila)
    │
    └── Batch ───► batch_consumer.py ──► CSV ──► cron (5 min) ──► cronjob_executor.py ──► PostgreSQL
```

| Abordagem | Destino | Latência típica |
|-----------|---------|-----------------|
| Stream | InfluxDB (`iot_stream_{perfil}`) | ~1–15 ms |
| Batch | PostgreSQL (`sensor_data_{perfil}`) | ~1–5 min (janela do cron) |

### Perfis de carga

| Cenário | Ativos | Fluxos de telemetria | Taxa teórica | Postgres | InfluxDB |
|---------|-------:|---------------------:|-------------:|----------|----------|
| `reduzida` | 25 | 60 | 62,2 msg/s | `sensor_data_reduzida` | `iot_stream_reduzida` |
| `intermediaria` | 50 | 120 | 124,4 msg/s | `sensor_data_intermediaria` | `iot_stream_intermediaria` |
| `completa` | 100 | 240 | 248,8 msg/s | `sensor_data_completa` | `iot_stream_completa` |

Todos os cenários utilizam os mesmos parâmetros de consumo. A carga é variada exclusivamente pela quantidade de ativos industriais ativos.

### Seeds das réplicas

| Réplica | Planta reduzida | Planta intermediária | Planta completa |
|----------|----------------:|---------------------:|----------------:|
| R1 | 20261101 | 20261101 | 20261101 |
| R2 | 20261102 | 20261102 | 20261102 |
| R3 | 20261103 | 20261103 | 20261103 |

As latências até a confirmação recebida pelo cliente usam a diferença entre os relógios monotônicos de criação e confirmação. Os CSVs `metrics/latency_batch.csv` e `metrics/latency_stream.csv` também mantêm os horários civis e a identidade da referência do relógio. O resumo, os histogramas e os painéis usam o intervalo monotônico; os horários civis continuam a localizar os eventos no tempo.

Na nova série, as validações curtas e as réplicas são guardadas em diretórios separados. O manifesto registra as imagens, as dependências e os arquivos usados; `images.tar` permite recuperar as imagens. Cada execução confere integridade, relógio, cobertura de recursos e volume produzido. Como critério operacional, o volume deve ficar entre 95% e 105% do valor teórico calculado para a duração nominal; esse critério não substitui a análise da taxa observada ao longo do tempo.

### Saída por run

Cada execução cria uma pasta timestampada em `runs/`:

```
runs/experimento_reduzida_YYYY_MM_DD_HH_MM/
├── batches_output_reduzida/       # CSVs aguardando processamento
├── batches_processed_reduzida/    # CSVs já ingeridos no PG
└── metrics/
    ├── docker_stats_reduzida.csv       # CPU, RAM, rede por container
    ├── summary_reduzida.json / .csv    # Totais PG/Influx, latência, throughput
    ├── batch_throughput_reduzida.csv   # Throughput por arquivo CSV
    └── latency_hist_reduzida.json      # Histogramas de latência (batch + stream)
```

---

## Como executar

### Experimento único

```bash
./start_experiment.sh reduzida --seed 20261101 # execução isolada, sem apagar dados anteriores
```

O script faz tudo em sequência:
1. Ativa o perfil (`docker.env`)
2. Cria a pasta `runs/experimento_{perfil}_YYYY_MM_DD_HH_MM_SS/` e recursos isolados para a execução
3. `docker compose build` + sobe infra e consumidores
4. Cria tabela PG e bucket InfluxDB (`setup_experiment.py`)
5. Inicia coleta de `docker stats` em background
6. Roda o gerador por **1 hora**
7. Aguarda 10 min de buffer (cron processa os últimos CSVs)
8. Para os consumidores, exporta as métricas e confere os totais e identificadores nas duas abordagens
9. Mantém Postgres, Influx e Grafana em execução; se a validação falhar, a série é interrompida

### Série completa (9 runs, 3 por cenário)

```bash
./run_all_experiments.sh                                  # 3 × (reduzida, intermediaria, completa) = 9 runs (~11 horas)
./run_all_experiments.sh --workloads intermediaria,completa # só esses dois cenários
./run_all_experiments.sh --runs 1          # 1 run por workload
./run_all_experiments.sh --dry-run         # valida a sequência sem executar
```

Logs individuais e master log salvos em `logs/`.

---

## Variáveis principais (`docker.env`)

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `EXPERIMENT_LABEL` | `completa` | Identificador do cenário |
| `EXECUTION_TIME_SECONDS` | `3600` | Duração do gerador |
| `ACTIVE_ASSET_COUNT` | `100` | Quantidade de ativos industriais simulados |
| `EXPERIMENT_SEED` | `20261101` | Seed determinística dos valores e identificadores gerados |
| `PG_TABLE` | `sensor_data_completa` | Tabela destino no PostgreSQL |
| `INFLUXDB_BUCKET` | `iot_stream_completa` | Bucket destino no InfluxDB |
| `BATCH_OUTPUT_HOST` | — | Pasta no host para CSVs pendentes |
| `BATCH_PROCESSED_HOST` | — | Pasta no host para CSVs processados |
| `STREAM_WORKER_COUNT` | `1` | Workers paralelos, mantidos constantes entre os cenários |
| `STREAM_QUEUE_MAXSIZE` | `200000` | Capacidade máxima da fila de mensagens |
| `STREAM_DRAIN_BATCH_SIZE` | `3000` | Máximo de mensagens retiradas da fila por operação |
| `STREAM_DRAIN_TIMEOUT_S` | `0.05` | Espera máxima inicial quando a fila está vazia |

---

## Grafana

Após subir o stack, acesse **http://localhost:5005** (`admin` / `admin`).

O dashboard **TCC — Stream vs Batch** exibe a taxa de confirmações e a latência até a confirmação para a execução ativa. Os seletores devem corresponder ao cenário ativo; não permitem consultar execuções anteriores. A fonte auxiliar `metrics-db` lê os CSVs da execução sem alterá-los e não armazena os dados em seu banco temporário. A atualização a cada 30 segundos e as leituras dos arquivos consomem recursos da máquina e podem interferir nas medições. Os painéis são provisionados automaticamente via `grafana/provisioning/`.
