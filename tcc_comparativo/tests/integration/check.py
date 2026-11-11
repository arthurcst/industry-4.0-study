"""Confronta confirmações, arquivos batch e registros em bancos de teste reais."""

import csv
import glob
import json
import os
import runpy
import statistics
from collections import Counter

import psycopg2
from influxdb_client import InfluxDBClient


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as source:
        return list(csv.reader(source))


def main():
    confirmed = {}
    for approach in ("batch", "stream"):
        rows = read_csv(f"/app/metrics/latency_{approach}.csv")
        assert rows, f"Nenhuma confirmação para {approach}"
        assert all(len(row) == 6 and row[0] for row in rows), f"CSV inválido em {approach}"
        latencies = [(int(row[4]) - int(row[3])) / 1_000_000 for row in rows]
        assert all(value >= 0 for value in latencies), f"Latência negativa em {approach}"
        ids = [row[0] for row in rows]
        assert len(ids) == len(set(ids)), f"IDs duplicados em {approach}"
        confirmed[approach] = {"rows": rows, "ids": set(ids), "latencies": latencies}

    assert confirmed["batch"]["ids"] == confirmed["stream"]["ids"], "IDs confirmados diferem entre abordagens"

    processed = []
    for path in glob.glob("/app/batches_processed/*.csv"):
        with open(path, newline="", encoding="utf-8") as source:
            processed.extend(csv.DictReader(source))
    assert len(processed) == len(confirmed["batch"]["rows"]), "CSV processados diferem das confirmações batch"
    assert {row["id"] for row in processed} == confirmed["batch"]["ids"], "IDs batch processados diferem das confirmações"

    conn = psycopg2.connect(dbname="iot_batch", user="grafana", password="grafana", host="postgres")
    with conn, conn.cursor() as cur:
        cur.execute("SELECT created_at, sensor_id, location, metric, value, ingested_at FROM sensor_data_reduzida")
        pg_rows = cur.fetchall()
    conn.close()
    assert len(pg_rows) == len(processed), "Total no PostgreSQL difere dos arquivos processados"
    pg_keys = Counter((str(t), sensor, location, metric, str(value)) for t, sensor, location, metric, value, _ in pg_rows)
    csv_keys = Counter((r["created_at"], r["sensor_id"], r["location"], r["metric"], r["value"]) for r in processed)
    assert pg_keys == csv_keys, "Registros no PostgreSQL diferem dos arquivos processados"

    keys_to_ids = {(r["created_at"], r["sensor_id"], r["location"], r["metric"]): r["id"] for r in processed}
    assert len(keys_to_ids) == len(processed), "Chaves de correspondência ambíguas"
    ack_by_id = {row[0]: int(row[2]) for row in confirmed["batch"]["rows"]}
    for created, sensor, location, metric, _, prewrite in pg_rows:
        record_id = keys_to_ids[(str(created), sensor, location, metric)]
        assert ack_by_id[record_id] >= prewrite, "Confirmação batch anterior à preparação da escrita"

    client = InfluxDBClient(url="http://influxdb:8086", token="my-super-token", org="my-org")
    query = 'from(bucket: "iot_stream_reduzida") |> range(start: -1h) |> filter(fn: (r) => r._field == "value") |> count() |> group() |> sum(column: "_value")'
    influx_total = sum(int(record.get_value()) for table in client.query_api().query(query) for record in table.records)
    assert influx_total == len(confirmed["stream"]["rows"]), f"InfluxDB contém {influx_total} pontos, mas há {len(confirmed['stream']['rows'])} confirmações"
    timestamp_query = '''from(bucket: "iot_stream_reduzida") |> range(start: -1h)
      |> filter(fn: (r) => r._field == "created_at" or r._field == "ingested_at")
      |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")'''
    stream_acks = {row[0]: int(row[2]) for row in confirmed["stream"]["rows"]}
    matched = set()
    for table in client.query_api().query(timestamp_query):
        for record in table.records:
            values = record.values
            key = (str(values["created_at"]), values["sensor_id"], values["location"], values["_measurement"])
            record_id = keys_to_ids[key]
            assert stream_acks[record_id] >= values["ingested_at"], "Confirmação stream anterior à preparação da escrita"
            matched.add(record_id)
    client.close()
    assert matched == confirmed["stream"]["ids"], "Registros InfluxDB não correspondem a todas as confirmações"

    exporter = runpy.run_path("/app/scripts/export_experiment_metrics.py")
    latency_stats = {}
    for approach in ("batch", "stream"):
        values, stats = exporter["confirmed_latency_metrics"](approach)
        assert values == confirmed[approach]["latencies"], f"Exportação incorreta de {approach}"
        assert stats["latency_count"] == len(values)
        assert stats["latency_avg_ms"] == round(statistics.mean(values), 2)
        assert stats["latency_stddev_ms"] == round(statistics.pstdev(values), 2)
        latency_stats[approach] = stats

    print(json.dumps({
        "batch_confirmed": len(confirmed["batch"]["rows"]),
        "stream_confirmed": len(confirmed["stream"]["rows"]),
        "postgres_records": len(pg_rows),
        "influx_points": influx_total,
        "matched_influx_records": len(matched),
        "confirmations_after_prewrite": True,
        "exported_statistics_match": True,
        "batch_latency_ms": latency_stats["batch"],
        "stream_latency_ms": latency_stats["stream"],
    }, indent=2))


if __name__ == "__main__":
    main()
