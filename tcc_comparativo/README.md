# tcc_comparativo

Comparativo **stream vs batch** para ingestão IoT industrial (TCC Indústria 4.0).

## Trocar experimento (1x / 2x / 4x)

Cada carga usa **tabela Postgres**, **bucket InfluxDB** e **pastas de batch** próprios.

**Windows (PowerShell):**

```powershell
cd tcc_comparativo
.\scripts\switch_experiment.ps1 4x
```

**Linux/macOS:**

```bash
cd tcc_comparativo
chmod +x scripts/switch_experiment.sh
./scripts/switch_experiment.sh 4x
```

| Perfil | RATE_MODIFIER | Postgres | InfluxDB | Saída por run |
|--------|---------------|----------|----------|---------------|
| 1x | 1 | `sensor_data_1x` | `iot_stream_1x` | `runs/experimento_1x_YYYY_MM_DD_HH_MM/` |
| 2x | 2 | `sensor_data_2x` | `iot_stream_2x` | `runs/experimento_2x_YYYY_MM_DD_HH_MM/` |
| 4x | 4 | `sensor_data_4x` | `iot_stream_4x` | `runs/experimento_4x_YYYY_MM_DD_HH_MM/` |

Cada run do `start_experiment.sh` cria uma pasta timestampada, por exemplo:

```text
runs/experimento_1x_2026_05_24_00_13/
├── batches_output_1x/
├── batches_processed_1x/
└── metrics/
    ├── docker_stats_1x.csv
    ├── summary_1x.json
    ├── summary_1x.csv
    └── batch_throughput_1x.csv
```

## Executar um experimento

**Forma recomendada** — um comando faz tudo (build, up, gerador, stats, export, down):

```bash
chmod +x start_experiment.sh
./start_experiment.sh 1x          # ou 2x / 4x — execução normal
./start_experiment.sh 1x truncate # esvazia PG + Influx do perfil antes do run
```

Com `truncate`, a tabela Postgres (`sensor_data_{perfil}`) é esvaziada e o bucket Influx (`iot_stream_{perfil}`) é recriado vazio — útil para comparar stream vs batch sem dados de runs anteriores. Sem `truncate`, os dados acumulam na mesma tabela/bucket.

Também disponível isolado (com serviços no ar):

```bash
bash scripts/setup_experiment.sh --truncate
```

O script:
1. Ativa o perfil (`docker.env`)
2. Cria pasta `runs/experimento_{perfil}_YYYY_MM_DD_HH_MM` e aponta batches/metrics para ela
3. `docker compose build` + sobe infra e consumidores
4. `setup_experiment.py` (tabela PG + bucket Influx)
5. Inicia coleta `docker stats` em background
6. Roda o gerador por 1 h e aguarda
7. Espera a coleta terminar (1 h + 10 min de buffer)
8. `export_experiment_metrics.py`
9. Para apenas o **sensor-generator**; Postgres, Influx, Grafana e consumidores **continuam rodando**

---

<details>
<summary>Passo a passo manual (alternativo)</summary>

```bash
# 1. Escolher carga
./scripts/switch_experiment.sh 2x

# 2. Subir infra + consumidores
docker compose up -d postgres influxdb mosquitto grafana batch-consumer stream-consumer

> **Windows/WSL:** Postgres, InfluxDB e Mosquitto usam **volumes nomeados** do Docker (evita erro de permissão em pastas do host). A config do Mosquitto fica em `mosquitto/mosquitto_config/mosquitto.conf`.

# 3. Criar tabela PG e bucket Influx (com serviços no ar)
bash scripts/setup_experiment.sh
# ou limpar antes de um novo run:
bash scripts/setup_experiment.sh --truncate
# ou: python3 -I scripts/setup_experiment.py  (requer pip install -r requirements.txt)

# 4. Gerador — roda 1 hora e encerra sozinho
docker compose up sensor-generator

# 5. Aguardar ~5 min para o cron processar CSVs restantes

# 6. Exportar resumo (PG, Influx, latência, throughput batch)
python3 -I scripts/export_experiment_metrics.py
```

</details>

## Coletar métricas de desempenho

Durante o experimento, rode a coleta de **CPU/RAM/rede** em um terminal separado (para na duração do gerador + 10 min):

**Linux/WSL:**

```bash
chmod +x scripts/collect_docker_stats.sh
bash scripts/collect_docker_stats.sh
# ou (após chmod +x): ./scripts/collect_docker_stats.sh
```

> Se `./script.sh` falhar com `required file not found`, use `bash script.sh` — é line ending CRLF do Windows. Os `.sh` devem estar em LF (ver `.gitattributes`).

**Windows (PowerShell):**

```powershell
.\scripts\collect_docker_stats.ps1
```

Saída: `${METRICS_HOST}/docker_stats_{1x|2x|4x}.csv` (via `start_experiment.sh`; legado: `metrics/` na raiz).

Após o run (gerador parado + cron processou CSVs), exporte o resumo:

```bash
python3 -I scripts/export_experiment_metrics.py
```

> **WSL + `/mnt/e`:** use `python3 -I scripts/...` ou `bash scripts/setup_experiment.sh` para evitar `KeyError: 'scripts'` ao importar dependências. Se faltar `psycopg2`, rode `pip install -r requirements.txt` no env ativo ou deixe o wrapper usar o container `stream-consumer`.

Gera em `${EXPERIMENT_RUN_DIR}/metrics/` (ex.: `runs/experimento_1x_2026_05_24_00_13/metrics/`):

| Arquivo | Conteúdo |
|---------|----------|
| `docker_stats_1x.csv` | CPU, memória, rede, PIDs por container (série temporal) |
| `summary_1x.json` / `summary_1x.csv` | Totais PG/Influx, latência, throughput batch |
| `batch_throughput_1x.csv` | Throughput por arquivo CSV (do log do cron) |

Variáveis opcionais:

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `COLLECT_INTERVAL` | `0.5` | Intervalo entre amostras (segundos) |
| `COLLECT_EXTRA_SECONDS` | `600` | Tempo extra após `EXECUTION_TIME_SECONDS` |
| `COLLECT_DURATION_SECONDS` | `EXECUTION_TIME + EXTRA` | Duração total da coleta |

> O script legado `docker_tracker.sh` redireciona para `scripts/collect_docker_stats.sh`.

## Variáveis principais (`docker.env`)

| Variável | Descrição |
|----------|-----------|
| `EXPERIMENT_LABEL` | Identificador do run (1x, 2x, 4x) |
| `EXECUTION_TIME_SECONDS` | Duração do gerador (padrão: 3600) |
| `RATE_MODIFIER` | Multiplicador de taxa de publicação |
| `PG_TABLE` | Tabela destino no PostgreSQL |
| `INFLUXDB_BUCKET` | Bucket destino no InfluxDB |
| `BATCH_OUTPUT_HOST` | Pasta no host para CSVs pendentes |
| `BATCH_PROCESSED_HOST` | Pasta no host para CSVs processados |
| `PG_PORT_HOST` | Porta Postgres no host para `setup_experiment.py` (padrão: 5434) |

## Arquitetura

- **Stream:** MQTT → `async_consumer_v2.py` → InfluxDB (fila + drain em lote + micro-batch Influx)
- **Batch:** MQTT → `batch_consumer.py` → CSV → cron (5 min) → `cronjob_executor.py` → PostgreSQL

`async_consumer.py` permanece como v1 legado (rollback no `Dockerfile.stream`).

Para comparar stream vs batch sem dados antigos: `./start_experiment.sh 1x truncate`.

Em perfis **2x/4x**, aumente `STREAM_WORKER_COUNT` no `docker.env.*` se `stream_dropped` ou o gap PG/Influx subir (1x usa 1 worker; 2x usa 4; 4x usa 6).

## Notas para o TCC — micro-batch no stream

> **Lembrete:** incluir esta justificativa na metodologia / discussão do TCC.

### Decisão adotada

O pipeline **stream usa micro-batching** (`WriteOptions` do InfluxDB: padrão `500` pontos ou flush a cada `1000` ms). **Não** usamos write síncrono ponto a ponto — esse modo era um gargalo artificial, não representativo de produção.

### Por que micro-batch é comum em IoT

Em cenários reais, escrever **1 ponto por requisição HTTP** é ineficiente (CPU, rede, custo de API). Gateways, Telegraf, clientes InfluxDB e plataformas cloud agrupam leituras antes de persistir — tipicamente **100–1000 pontos** ou janelas de **0,5–5 s**.

Micro-batch equilibra **throughput** e **latência**: ainda é tempo quase real para monitoramento, sem sacrificar desempenho do pipeline.

### Espectro comparado neste experimento

| Abordagem | Latência típica | Caso de uso |
|-----------|-----------------|-------------|
| Tempo real estrito | &lt; 100 ms | Controle de máquina, emergência (PLC, OPC-UA) |
| **Stream + micro-batch** | ~0,5–5 s | Dashboards, alertas, séries temporais operacionais |
| **Batch (CSV + cron)** | minutos | ETL, BI, histórico, data warehouse |

Os dois pipelines deste projeto comparam **padrões arquiteturais legítimos**, não uma implementação ingênua vs. otimizada.

### O que documentar no texto

1. Stream implementado com micro-batch assíncrono — **prática padrão em TSDBs** (InfluxDB, Telegraf).
2. Batch mantém macro-lotes (10k registros + cron a cada 5 min) — **característica do modelo**, não bug.
3. Latência end-to-end do stream deve ser **ordens de magnitude menor** que batch, mesmo com micro-batch.
4. Micro-batch **não** substitui hard real-time (&lt; 100 ms); telemetria MQTT aqui simula monitoramento industrial, não controle fechado de loop.

### Configuração atual (`docker.env`)

| Variável | Padrão | Função |
|----------|--------|--------|
| `INFLUX_BATCH_SIZE` | `5000` | Pontos por lote antes do flush (WriteAPI) |
| `INFLUX_FLUSH_INTERVAL_MS` | `500` | Flush forçado a cada N ms |
| `STREAM_DRAIN_BATCH_SIZE` | `3000` | Mensagens drenadas da fila por ciclo (v2) |
| `STREAM_WORKER_COUNT` | `1` / `8` / `12` | Workers paralelos (1x / 2x / 4x no `docker.env.*`) |
| `STREAM_QUEUE_MAXSIZE` | `200000` | Capacidade da fila MQTT→Influx (v2) |
| `MQTT_QOS` | `1` | Subscribe alinhado ao publish do gerador |

Tag `experiment` nos pontos Influx identifica a carga (1x / 2x / 4x) dentro do bucket.

## Grafana — dashboards

Após subir o stack, acesse http://localhost:3000 (`admin` / `admin`).

O dashboard **TCC — Stream vs Batch** inclui:

- **Stream:** registros/s, delay médio, throughput (InfluxDB / Flux)
- **Batch:** registros/s, delay médio, throughput de carga no Postgres (SQL)

Datasources e dashboard são provisionados automaticamente (`grafana/provisioning/`). Detalhes e queries em `grafana/PANELS.md`.

