# Grafana — painéis TCC

## Onde encontrar no Grafana

1. Abra http://localhost:3000 (`admin` / `admin`)
2. Menu lateral → **Dashboards** (ícone de quadrados)
3. Na lista à esquerda, abra a pasta **TCC**
4. Clique em **TCC — Stream vs Batch**

Ou use a busca no topo: digite `TCC`.

## Se não aparecer

Recrie o Grafana para carregar os arquivos de provisioning:

```bash
cd tcc_comparativo
docker compose up -d --force-recreate grafana
```

**Import manual:**

1. **Dashboards** → **New** → **Import**
2. **Upload** → `grafana/dashboards/tcc-pipelines.json`
3. Selecione datasources: **InfluxDB-Stream** e **PostgreSQL-Batch**
4. **Import**

Datasources provisionadas: **Connections → Data sources** → `InfluxDB-Stream`, `PostgreSQL-Batch`.

---

## Variáveis do dashboard

| Variável | Opções |
|----------|--------|
| **Bucket Influx** | `iot_stream_1x`, `2x`, `4x` |
| **Tabela PG** | `sensor_data_1x`, `2x`, `4x` |

Alinhe com o perfil do experimento ativo.

---

## Painéis incluídos

### Stream (InfluxDB)

| Painel | Tipo | Métrica |
|--------|------|---------|
| Registros por segundo | Time series | Contagem de `value` / 1s |
| Delay médio | Time series | `ingested_at − created_at` (média / 10s) |
| Throughput médio | Stat | Média de msg/s nos últimos 2 min |

**Flux — registros/s:**

```flux
from(bucket: "iot_stream_1x")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._field == "value")
  |> aggregateWindow(every: 1s, fn: count, createEmpty: true)
```

**Flux — delay médio:**

```flux
from(bucket: "iot_stream_1x")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._field == "ingested_at" or r._field == "created_at")
  |> pivot(rowKey: ["_time", "sensor_id", "location", "production_line_id", "metric"], columnKey: ["_field"], valueColumn: "_value")
  |> map(fn: (r) => ({ _time: r._time, _value: float(v: r.ingested_at) - float(v: r.created_at) }))
  |> aggregateWindow(every: 10s, fn: mean, createEmpty: false)
```

### Batch (PostgreSQL)

| Painel | Tipo | Métrica |
|--------|------|---------|
| Registros por segundo | Time series | `COUNT(*)` por segundo em `created_at` |
| Delay médio | Time series | `AVG(ingested_at - created_at)` por segundo |
| Throughput carga PG | Time series | `COUNT(*)` por segundo em `ingested_at` |

**SQL — registros/s (geração MQTT):**

```sql
SELECT
  to_timestamp(created_at / 1000.0) AS "time",
  COUNT(*)::double precision AS "records_per_second"
FROM sensor_data_1x
WHERE created_at >= (EXTRACT(EPOCH FROM $__timeFrom()::timestamptz) * 1000)::bigint
  AND created_at < (EXTRACT(EPOCH FROM $__timeTo()::timestamptz) * 1000)::bigint
GROUP BY 1
ORDER BY 1
```

**SQL — delay médio:**

```sql
SELECT
  to_timestamp(created_at / 1000.0) AS "time",
  AVG(ingested_at - created_at::bigint)::double precision AS "latency_ms"
FROM sensor_data_1x
WHERE created_at >= (EXTRACT(EPOCH FROM $__timeFrom()::timestamptz) * 1000)::bigint
  AND created_at < (EXTRACT(EPOCH FROM $__timeTo()::timestamptz) * 1000)::bigint
GROUP BY 1
ORDER BY 1
```

**SQL — throughput (carga no Postgres após cron):**

```sql
SELECT
  to_timestamp(ingested_at / 1000.0) AS "time",
  COUNT(*)::double precision AS "throughput"
FROM sensor_data_1x
WHERE ingested_at >= (EXTRACT(EPOCH FROM $__timeFrom()::timestamptz) * 1000)::bigint
  AND ingested_at < (EXTRACT(EPOCH FROM $__timeTo()::timestamptz) * 1000)::bigint
GROUP BY 1
ORDER BY 1
```

---

## Recriar provisioning

Se o Grafana entra em **restart loop** com:

```text
Datasource provisioning error: data source not found
```

isso costuma ser volume `grafana_data` incompatível após upgrade para **Grafana 13+** (`grafana:latest`). O projeto usa **Grafana 10.4.5** fixo no `docker-compose.yml`.

**Reset automático:**

```bash
bash scripts/reset_grafana.sh
```

**Manual:**

```bash
docker compose rm -sf grafana
docker volume rm tcc_comparativo_grafana_data
docker compose up -d grafana
```

Ou só recriar o container (se o volume já estiver limpo):

```bash
docker compose up -d --force-recreate grafana
```
