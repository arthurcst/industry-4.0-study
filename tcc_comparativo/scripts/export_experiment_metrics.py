#!/usr/bin/env python3
"""Exporta resumo pós-experimento: contagens PG/Influx, latência e throughput batch."""

import os
import sys


def _bootstrap_paths():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    os.chdir(project_dir)
    if sys.path and os.path.abspath(sys.path[0]) == script_dir:
        sys.path.pop(0)


_bootstrap_paths()

import csv
import glob
import json
import re
import subprocess
from datetime import datetime, timezone

import psycopg2
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)
load_dotenv(os.path.join(project_dir, "docker.env"))

EXPERIMENT_LABEL = os.getenv("EXPERIMENT_LABEL", "1x")
PG_TABLE = os.getenv("PG_TABLE", "sensor_data")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "my-org")
BATCH_PROCESSED_HOST = os.getenv(
    "BATCH_PROCESSED_HOST", f"./batches_processed_{EXPERIMENT_LABEL}"
)
EXPERIMENT_RUN_DIR = os.getenv("EXPERIMENT_RUN_DIR", "")
METRICS_HOST = os.getenv("METRICS_HOST", "")


def resolve_metrics_dir() -> str:
    if METRICS_HOST:
        return os.path.join(project_dir, METRICS_HOST.lstrip("./"))
    if EXPERIMENT_RUN_DIR:
        return os.path.join(project_dir, EXPERIMENT_RUN_DIR, "metrics")
    return os.path.join(project_dir, "metrics")


def resolve_host(service_host: str) -> str:
    if os.path.exists("/.dockerenv"):
        return service_host
    if service_host in ("postgres", "influxdb", "mosquitto"):
        return "localhost"
    return service_host


PG_HOST = resolve_host(os.getenv("PG_HOST", "localhost"))
PG_PORT = os.getenv(
    "PG_PORT_HOST" if PG_HOST == "localhost" else "PG_PORT",
    "5434" if PG_HOST == "localhost" else "5432",
)
_influx_url = os.getenv("INFLUXDB_URL", "http://localhost:8086")
if not os.path.exists("/.dockerenv"):
    _influx_url = _influx_url.replace("http://influxdb:", "http://localhost:")
INFLUXDB_URL = _influx_url
METRICS_DIR = resolve_metrics_dir()
os.makedirs(METRICS_DIR, exist_ok=True)


def export_postgres_metrics() -> dict:
    conn = psycopg2.connect(
        dbname=os.getenv("PG_DB", "iot_batch"),
        user=os.getenv("PG_USER", "grafana"),
        password=os.getenv("PG_PASSWORD", "grafana"),
        host=PG_HOST,
        port=PG_PORT,
    )
    cursor = conn.cursor()

    cursor.execute(f"SELECT COUNT(*) FROM {PG_TABLE}")
    total = cursor.fetchone()[0]

    cursor.execute(
        f"""
        SELECT
            AVG(ingested_at - created_at::bigint),
            MIN(ingested_at - created_at::bigint),
            MAX(ingested_at - created_at::bigint),
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ingested_at - created_at::bigint),
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ingested_at - created_at::bigint)
        FROM {PG_TABLE}
        WHERE ingested_at IS NOT NULL AND created_at IS NOT NULL
        """
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    return {
        "table": PG_TABLE,
        "total_records": total,
        "latency_avg_ms": round(float(row[0]), 2) if row[0] is not None else None,
        "latency_min_ms": row[1],
        "latency_max_ms": row[2],
        "latency_p50_ms": round(float(row[3]), 2) if row[3] is not None else None,
        "latency_p95_ms": round(float(row[4]), 2) if row[4] is not None else None,
    }


def export_influx_metrics() -> dict:
    if not INFLUXDB_BUCKET or not INFLUXDB_TOKEN:
        return {"bucket": INFLUXDB_BUCKET, "total_records": None, "error": "token/bucket ausente"}

    client = InfluxDBClient(
        url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG
    )
    # Fix 1 (range): -7d → -30d para cobrir runs com mais de uma semana
    count_query = f'''
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: -30d)
  |> filter(fn: (r) => r._field == "value")
  |> count()
  |> group()
  |> sum(column: "_value")
'''
    try:
        tables = client.query_api().query(count_query, org=INFLUXDB_ORG)
        total = 0
        for table in tables:
            for record in table.records:
                total += record.get_value() or 0

        # Fix 2 (pivot rowKey): inclui _measurement + sensor_id para evitar colisão
        # quando múltiplas métricas chegam no mesmo _time.
        # Fix 3 (percentis): exporta p50 e p95 além da média.
        # Fix 4 (exceção silenciosa): loga o erro real em vez de engolir.
        latency_result = {
            "latency_avg_ms": None,
            "latency_p50_ms": None,
            "latency_p95_ms": None,
            "latency_min_ms": None,
            "latency_max_ms": None,
        }
        # Calcula cada estatística via Flux para evitar trazer milhões de pontos ao Python.
        # O pivot usa _time + _measurement + sensor_id como chave única por ponto.
        # Após o map, a coluna de interesse é "latency_ms" (não "_value").
        _lat_base = f'''
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: -30d)
  |> filter(fn: (r) => r._field == "ingested_at" or r._field == "created_at")
  |> pivot(
      rowKey: ["_time", "_measurement", "sensor_id"],
      columnKey: ["_field"],
      valueColumn: "_value"
     )
  |> filter(fn: (r) => exists r.ingested_at and exists r.created_at)
  |> map(fn: (r) => ({{latency_ms: float(v: r.ingested_at) - float(v: r.created_at)}}))
'''
        _lat_stats = {
            "latency_avg_ms": f'{_lat_base} |> mean(column: "latency_ms")',
            "latency_min_ms": f'{_lat_base} |> min(column: "latency_ms")',
            "latency_max_ms": f'{_lat_base} |> max(column: "latency_ms")',
            "latency_p50_ms": f'{_lat_base} |> quantile(q: 0.50, column: "latency_ms")',
            "latency_p95_ms": f'{_lat_base} |> quantile(q: 0.95, column: "latency_ms")',
        }
        try:
            for key, q in _lat_stats.items():
                for table in client.query_api().query(q, org=INFLUXDB_ORG):
                    for record in table.records:
                        v = record.values.get("latency_ms")
                        if v is not None:
                            latency_result[key] = round(float(v), 2)
            if latency_result["latency_avg_ms"] is not None:
                print(f"   InfluxDB latência: avg={latency_result['latency_avg_ms']}ms "
                      f"p50={latency_result['latency_p50_ms']}ms "
                      f"p95={latency_result['latency_p95_ms']}ms")
        except Exception as exc:
            latency_result["latency_error"] = str(exc)
            print(f"   ⚠️ InfluxDB latência query falhou: {exc}")

        client.close()
        return {
            "bucket": INFLUXDB_BUCKET,
            "total_records": total,
            **latency_result,
        }
    except Exception as exc:
        client.close()
        return {"bucket": INFLUXDB_BUCKET, "total_records": None, "error": str(exc)}


def export_batch_files_metrics() -> dict:
    processed_dir = os.path.join(project_dir, BATCH_PROCESSED_HOST.lstrip("./"))
    pattern = os.path.join(processed_dir, "*.csv")
    files = sorted(glob.glob(pattern))
    total_rows = 0
    for filepath in files:
        with open(filepath, encoding="utf-8") as f:
            total_rows += max(0, sum(1 for _ in f) - 1)

    return {
        "processed_dir": BATCH_PROCESSED_HOST,
        "csv_files": len(files),
        "total_rows_in_csvs": total_rows,
    }


STREAM_METRICS_PATTERN = re.compile(
    r"STREAM_METRICS recebidas=(?P<contador>\d+) descartadas=(?P<dropped>\d+)"
    r"(?: fila=(?P<fila>\d+) maxsize=(?P<maxsize>\d+))?"
    r"(?: escritos=(?P<escritos>\d+) erros_parse=(?P<erros_parse>\d+)"
    r"(?: erros_write=(?P<erros_write>\d+) mqtt_total=(?P<mqtt_total>\d+))?)?"
)

SHUTDOWN_V2_PATTERN = re.compile(
    r"Worker v2 encerrado\. Enfileiradas=(?P<contador>\d+), "
    r"Descartadas=(?P<dropped>\d+), Escritos=(?P<escritos>\d+), "
    r"ErrosParse=(?P<erros_parse>\d+), ErrosWrite=(?P<erros_write>\d+)"
)


def export_stream_log_metrics() -> dict:
    """Último snapshot dos logs do stream_consumer (contador/descartadas)."""
    result = {
        "contador": None,
        "dropped": None,
        "queue_pending": None,
        "queue_maxsize": int(os.getenv("STREAM_QUEUE_MAXSIZE", "200000")),
        "points_written": None,
        "parse_errors": None,
        "write_errors": None,
        "mqtt_total_received": None,
        "source": None,
    }

    try:
        proc = subprocess.run(
            ["docker", "logs", "stream_consumer", "--tail", "all"],
            capture_output=True,
            text=True,
            check=False,
        )
        log_text = proc.stdout + proc.stderr
    except FileNotFoundError:
        result["error"] = "docker não encontrado"
        return result

    last_match = None
    for line in log_text.splitlines():
        match = STREAM_METRICS_PATTERN.search(line)
        if match:
            last_match = match

    if last_match is None:
        shutdown_v1 = re.compile(
            r"Worker encerrado\. Recebidas=(?P<contador>\d+), "
            r"Descartadas=(?P<dropped>\d+)"
        )
        for line in log_text.splitlines():
            match = shutdown_v1.search(line)
            if match:
                last_match = match
                result["source"] = "shutdown_log_v1"
                break

    if last_match is None:
        for line in log_text.splitlines():
            match = SHUTDOWN_V2_PATTERN.search(line)
            if match:
                last_match = match
                result["source"] = "shutdown_log_v2"

    if last_match is None:
        result["error"] = "nenhum STREAM_METRICS nos logs do stream_consumer"
        return result

    if result["source"] is None:
        result["source"] = "periodic_log"

    result["contador"] = int(last_match.group("contador"))
    result["dropped"] = int(last_match.group("dropped"))
    if last_match.groupdict().get("fila") is not None:
        result["queue_pending"] = int(last_match.group("fila"))
    if last_match.groupdict().get("maxsize") is not None:
        result["queue_maxsize"] = int(last_match.group("maxsize"))
    if last_match.groupdict().get("escritos") is not None:
        result["points_written"] = int(last_match.group("escritos"))
    if last_match.groupdict().get("erros_parse") is not None:
        result["parse_errors"] = int(last_match.group("erros_parse"))
    if last_match.groupdict().get("erros_write") is not None:
        result["write_errors"] = int(last_match.group("erros_write"))
    if last_match.groupdict().get("mqtt_total") is not None:
        result["mqtt_total_received"] = int(last_match.group("mqtt_total"))

    return result


def export_batch_log_throughput() -> list:
    pattern = re.compile(
        r"✅ (?P<batch_id>batch_\d+_\d+) processado: (?P<records>\d+) registros "
        r"em (?P<seconds>[\d.]+)s \((?P<throughput>[\d.]+) records/s\)"
    )
    entries = []

    try:
        result = subprocess.run(
            ["docker", "logs", "batch_consumer", "--tail", "all"],
            capture_output=True,
            text=True,
            check=False,
        )
        log_text = result.stdout + result.stderr
    except FileNotFoundError:
        return entries

    for line in log_text.splitlines():
        match = pattern.search(line)
        if match:
            entries.append(
                {
                    "batch_id": match.group("batch_id"),
                    "records": int(match.group("records")),
                    "processing_seconds": float(match.group("seconds")),
                    "throughput_records_per_s": float(match.group("throughput")),
                }
            )

    return entries


# ── Configuração dos histogramas ──────────────────────────────────────────────
BATCH_HIST_BINS = 60
BATCH_HIST_MIN_S = 0
BATCH_HIST_MAX_S = 400

STREAM_HIST_BINS = 50
STREAM_HIST_MIN_MS = 0
STREAM_HIST_MAX_MS = 30   # cobre ~99.95% dos pontos


def _make_hist_from_values(values, n_bins, v_min, v_max):
    """Computa histograma sem dependências externas. Retorna (edges, counts, n_clipped)."""
    bin_width = (v_max - v_min) / n_bins
    counts = [0] * n_bins
    clipped = 0
    for v in values:
        if v < v_min or v > v_max:
            clipped += 1
            continue
        idx = int((v - v_min) / bin_width)
        counts[min(idx, n_bins - 1)] += 1
    edges = [round(v_min + i * bin_width, 6) for i in range(n_bins + 1)]
    return edges, counts, clipped


def export_latency_histograms() -> dict:
    """Exporta histogramas pré-computados de latência batch (PG) e stream (InfluxDB)."""
    result = {"batch": None, "stream": None}

    # ── Batch: width_bucket no PG evita trazer todas as linhas para Python ────
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("PG_DB", "iot_batch"),
            user=os.getenv("PG_USER", "grafana"),
            password=os.getenv("PG_PASSWORD", "grafana"),
            host=PG_HOST,
            port=PG_PORT,
        )
        cur = conn.cursor()
        cur.execute(f"""
            SELECT
                width_bucket(
                    (ingested_at - created_at::bigint) / 1000.0,
                    %(lo)s, %(hi)s, %(bins)s
                ) AS bucket,
                count(*) AS cnt
            FROM {PG_TABLE}
            WHERE ingested_at IS NOT NULL AND created_at IS NOT NULL
              AND (ingested_at - created_at::bigint) / 1000.0
                  BETWEEN %(lo)s AND %(hi)s
            GROUP BY bucket ORDER BY bucket
        """, {"lo": BATCH_HIST_MIN_S, "hi": BATCH_HIST_MAX_S, "bins": BATCH_HIST_BINS})
        rows = cur.fetchall()

        # Conta registros fora do range (capped)
        cur.execute(f"""
            SELECT count(*) FROM {PG_TABLE}
            WHERE ingested_at IS NOT NULL AND created_at IS NOT NULL
              AND (ingested_at - created_at::bigint) / 1000.0
                  NOT BETWEEN %(lo)s AND %(hi)s
        """, {"lo": BATCH_HIST_MIN_S, "hi": BATCH_HIST_MAX_S})
        clipped = cur.fetchone()[0]
        cur.close(); conn.close()

        bin_width = (BATCH_HIST_MAX_S - BATCH_HIST_MIN_S) / BATCH_HIST_BINS
        counts = [0] * BATCH_HIST_BINS
        for bucket, cnt in rows:
            if bucket is not None and 1 <= bucket <= BATCH_HIST_BINS:
                counts[bucket - 1] = int(cnt)
        edges = [round(BATCH_HIST_MIN_S + i * bin_width, 6) for i in range(BATCH_HIST_BINS + 1)]

        result["batch"] = {
            "bin_edges_s": edges,
            "counts": counts,
            "n_bins": BATCH_HIST_BINS,
            "range_s": [BATCH_HIST_MIN_S, BATCH_HIST_MAX_S],
            "clipped_count": int(clipped),
            "total_in_range": sum(counts),
        }
        print(f"   Histograma batch: {sum(counts):,} registros em {BATCH_HIST_BINS} bins "
              f"[{BATCH_HIST_MIN_S}–{BATCH_HIST_MAX_S}s], fora do range: {clipped}")
    except Exception as exc:
        result["batch"] = {"error": str(exc)}
        print(f"   ⚠️ Histograma batch falhou: {exc}")

    # ── Stream: pull dos valores do InfluxDB e computa em Python ─────────────
    if not INFLUXDB_BUCKET or not INFLUXDB_TOKEN:
        result["stream"] = {"error": "token/bucket ausente"}
        return result
    try:
        client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
        lat_q = f"""
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: -30d)
  |> filter(fn: (r) => r._field == "ingested_at" or r._field == "created_at")
  |> pivot(
      rowKey: ["_time", "_measurement", "sensor_id"],
      columnKey: ["_field"],
      valueColumn: "_value"
     )
  |> filter(fn: (r) => exists r.ingested_at and exists r.created_at)
  |> map(fn: (r) => ({{latency_ms: float(v: r.ingested_at) - float(v: r.created_at)}}))
  |> keep(columns: ["latency_ms"])
"""
        values = []
        for table in client.query_api().query(lat_q, org=INFLUXDB_ORG):
            for record in table.records:
                v = record.values.get("latency_ms")
                if v is not None:
                    values.append(float(v))
        client.close()

        negatives = sum(1 for v in values if v < 0)
        pos_values = [v for v in values if v >= 0]
        edges, counts, clipped = _make_hist_from_values(
            pos_values, STREAM_HIST_BINS, STREAM_HIST_MIN_MS, STREAM_HIST_MAX_MS
        )
        result["stream"] = {
            "bin_edges_ms": edges,
            "counts": counts,
            "n_bins": STREAM_HIST_BINS,
            "range_ms": [STREAM_HIST_MIN_MS, STREAM_HIST_MAX_MS],
            "total_positive": len(pos_values),
            "negative_count": negatives,
            "clipped_count": clipped,
        }
        print(f"   Histograma stream: {len(pos_values):,} pontos em {STREAM_HIST_BINS} bins "
              f"[{STREAM_HIST_MIN_MS}–{STREAM_HIST_MAX_MS}ms], "
              f"negativos: {negatives}, fora do range: {clipped}")
    except Exception as exc:
        result["stream"] = {"error": str(exc)}
        print(f"   ⚠️ Histograma stream falhou: {exc}")

    return result


def write_batch_throughput_csv(entries: list, path: str) -> None:
    if not entries:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "batch_id",
                "records",
                "processing_seconds",
                "throughput_records_per_s",
            ],
        )
        writer.writeheader()
        writer.writerows(entries)


def main():
    print(f"📤 Exportando métricas [{EXPERIMENT_LABEL}]...")

    summary = {
        "experiment": EXPERIMENT_LABEL,
        "experiment_run_dir": EXPERIMENT_RUN_DIR or None,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "postgres": {},
        "influxdb": {},
        "batch_files": {},
        "batch_throughput": {},
        "stream_consumer": {},
    }

    try:
        summary["postgres"] = export_postgres_metrics()
        print(f"   PostgreSQL: {summary['postgres']['total_records']} registros em {PG_TABLE}")
    except Exception as exc:
        summary["postgres"] = {"error": str(exc)}
        print(f"   ⚠️ PostgreSQL: {exc}")

    try:
        summary["influxdb"] = export_influx_metrics()
        print(
            f"   InfluxDB: {summary['influxdb'].get('total_records', '?')} pontos em {INFLUXDB_BUCKET}"
        )
    except Exception as exc:
        summary["influxdb"] = {"error": str(exc)}
        print(f"   ⚠️ InfluxDB: {exc}")

    try:
        summary["stream_consumer"] = export_stream_log_metrics()
        sc = summary["stream_consumer"]
        if sc.get("contador") is not None:
            extra = ""
            if sc.get("points_written") is not None:
                extra = f", escritos={sc['points_written']}"
            print(
                f"   Stream logs: recebidas={sc['contador']}, "
                f"descartadas={sc.get('dropped', 0)}{extra} "
                f"(fila max={sc.get('queue_maxsize', '?')})"
            )
        else:
            print(f"   ⚠️ Stream logs: {sc.get('error', 'indisponível')}")
    except Exception as exc:
        summary["stream_consumer"] = {"error": str(exc)}
        print(f"   ⚠️ Stream logs: {exc}")

    sc = summary.get("stream_consumer", {})
    influx_total = summary.get("influxdb", {}).get("total_records")
    if (
        sc.get("contador") is not None
        and influx_total is not None
        and isinstance(influx_total, int)
    ):
        sc["mqtt_enqueued"] = sc["contador"]
        if sc.get("mqtt_total_received") is None:
            sc["mqtt_total_received"] = sc["contador"] + (sc.get("dropped") or 0)
        sc["influx_gap_vs_enqueued"] = sc["contador"] - influx_total
        if sc.get("points_written") is not None:
            sc["write_gap_vs_enqueued"] = sc["contador"] - sc["points_written"]

    try:
        summary["batch_files"] = export_batch_files_metrics()
        print(
            f"   Batch CSVs: {summary['batch_files']['csv_files']} arquivos, "
            f"{summary['batch_files']['total_rows_in_csvs']} linhas"
        )
    except Exception as exc:
        summary["batch_files"] = {"error": str(exc)}

    throughput_entries = export_batch_log_throughput()
    if throughput_entries:
        # Fix 5: média ponderada — total_records / total_seconds evita viés de batches pequenos
        total_records_tp = sum(e["records"] for e in throughput_entries)
        total_seconds_tp = sum(e["processing_seconds"] for e in throughput_entries)
        avg_tp = total_records_tp / total_seconds_tp if total_seconds_tp > 0 else 0
        summary["batch_throughput"] = {
            "batches_processed": len(throughput_entries),
            "total_records_processed": total_records_tp,
            "total_processing_seconds": round(total_seconds_tp, 2),
            "avg_throughput_records_per_s": round(avg_tp, 2),
        }
        throughput_csv = os.path.join(
            METRICS_DIR, f"batch_throughput_{EXPERIMENT_LABEL}.csv"
        )
        write_batch_throughput_csv(throughput_entries, throughput_csv)
        print(f"   Batch throughput: {len(throughput_entries)} lotes → {throughput_csv}")

    try:
        hist_data = export_latency_histograms()
        summary["latency_histograms"] = hist_data
        hist_path = os.path.join(METRICS_DIR, f"latency_hist_{EXPERIMENT_LABEL}.json")
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(hist_data, f, indent=2, ensure_ascii=False)
        print(f"   Histogramas → {hist_path}")
    except Exception as exc:
        summary["latency_histograms"] = {"error": str(exc)}
        print(f"   ⚠️ Histogramas: {exc}")

    json_path = os.path.join(METRICS_DIR, f"summary_{EXPERIMENT_LABEL}.json")
    csv_path = os.path.join(METRICS_DIR, f"summary_{EXPERIMENT_LABEL}.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    flat_rows = [
        ("experiment", EXPERIMENT_LABEL),
        ("experiment_run_dir", EXPERIMENT_RUN_DIR or ""),
        ("exported_at", summary["exported_at"]),
        ("pg_table", summary["postgres"].get("table", "")),
        ("pg_total_records", summary["postgres"].get("total_records", "")),
        ("pg_latency_avg_ms", summary["postgres"].get("latency_avg_ms", "")),
        ("pg_latency_p50_ms", summary["postgres"].get("latency_p50_ms", "")),
        ("pg_latency_p95_ms", summary["postgres"].get("latency_p95_ms", "")),
        ("influx_bucket", summary["influxdb"].get("bucket", "")),
        ("influx_total_records", summary["influxdb"].get("total_records", "")),
        ("influx_latency_avg_ms", summary["influxdb"].get("latency_avg_ms", "")),
        ("influx_latency_p50_ms", summary["influxdb"].get("latency_p50_ms", "")),
        ("influx_latency_p95_ms", summary["influxdb"].get("latency_p95_ms", "")),
        ("influx_latency_min_ms", summary["influxdb"].get("latency_min_ms", "")),
        ("influx_latency_max_ms", summary["influxdb"].get("latency_max_ms", "")),
        ("batch_csv_files", summary["batch_files"].get("csv_files", "")),
        ("batch_csv_rows", summary["batch_files"].get("total_rows_in_csvs", "")),
        (
            "batch_avg_throughput_rps",
            summary["batch_throughput"].get("avg_throughput_records_per_s", ""),
        ),
        ("stream_contador", summary["stream_consumer"].get("contador", "")),
        ("stream_dropped", summary["stream_consumer"].get("dropped", "")),
        (
            "stream_queue_maxsize",
            summary["stream_consumer"].get("queue_maxsize", ""),
        ),
        (
            "stream_queue_pending",
            summary["stream_consumer"].get("queue_pending", ""),
        ),
        (
            "stream_mqtt_total_received",
            summary["stream_consumer"].get("mqtt_total_received", ""),
        ),
        (
            "stream_influx_gap_vs_enqueued",
            summary["stream_consumer"].get("influx_gap_vs_enqueued", ""),
        ),
        (
            "stream_points_written",
            summary["stream_consumer"].get("points_written", ""),
        ),
        (
            "stream_write_gap_vs_enqueued",
            summary["stream_consumer"].get("write_gap_vs_enqueued", ""),
        ),
        (
            "stream_parse_errors",
            summary["stream_consumer"].get("parse_errors", ""),
        ),
        (
            "stream_write_errors",
            summary["stream_consumer"].get("write_errors", ""),
        ),
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        writer.writerows(flat_rows)

    print("✅ Resumo salvo:")
    print(f"   {json_path}")
    print(f"   {csv_path}")


if __name__ == "__main__":
    main()
