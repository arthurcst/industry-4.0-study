"""Stream consumer v2 — fila de bytes, drain em lote, WriteAPI único (sem double-batch)."""

from time import time
from influxdb_client.client.influxdb_client import InfluxDBClient
from influxdb_client.client.write.point import Point
from influxdb_client.client.write_api import SYNCHRONOUS
from dotenv import load_dotenv
from utils.mqtt_conn import MQTTConnection

import atexit
import json
import os
import queue
import random
import signal
import threading
import time as std_time

load_dotenv()

STREAM_QUEUE_MAXSIZE = int(os.getenv("STREAM_QUEUE_MAXSIZE", "200000"))
STREAM_DRAIN_BATCH_SIZE = int(os.getenv("STREAM_DRAIN_BATCH_SIZE", "3000"))
STREAM_DRAIN_TIMEOUT_S = float(os.getenv("STREAM_DRAIN_TIMEOUT_S", "0.05"))
STREAM_WORKER_COUNT = max(1, int(os.getenv("STREAM_WORKER_COUNT", "1")))
STREAM_METRICS_LOG_INTERVAL_S = int(
    os.getenv("STREAM_METRICS_LOG_INTERVAL_S", "60")
)

STOP_EVENT = threading.Event()
MESSAGE_QUEUE: queue.Queue[bytes] = queue.Queue(maxsize=STREAM_QUEUE_MAXSIZE)
_STATS_LOCK = threading.Lock()

mqtt_received = 0
enqueued = 0
dropped = 0
parse_errors = 0
write_errors = 0
points_written = 0
write_batches = 0

INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_URL = os.getenv("INFLUXDB_URL")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG")
EXPERIMENT_LABEL = os.getenv("EXPERIMENT_LABEL", "1x")
INFLUX_BATCH_SIZE = int(os.getenv("INFLUX_BATCH_SIZE", "5000"))
INFLUX_FLUSH_INTERVAL_MS = int(os.getenv("INFLUX_FLUSH_INTERVAL_MS", "500"))

if not (INFLUXDB_TOKEN and INFLUXDB_ORG and INFLUXDB_BUCKET):
    raise ValueError("InfluxDB variables not found or not set correctly.")

client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
write_api = client.write_api(write_options=SYNCHRONOUS)


def shutdown_influx() -> None:
    client.close()


atexit.register(shutdown_influx)


def payload_to_point(payload: dict) -> Point:
    return (
        Point(payload["metric"])
        .tag("sensor_id", payload["sensor_id"])
        .tag("location", payload["location"])
        .tag("production_line_id", payload["production_line_id"])
        .tag("unit", payload["unit"])
        .tag("experiment", EXPERIMENT_LABEL)
        .field("value", payload["value"])
        .field("ingested_at", int(time() * 1000))
        .field("created_at", int(payload["created_at"]))
    )


def drain_queue(max_items: int, timeout_s: float) -> list[bytes]:
    items: list[bytes] = []
    deadline = std_time.monotonic() + timeout_s

    while len(items) < max_items:
        try:
            items.append(MESSAGE_QUEUE.get_nowait())
        except queue.Empty:
            if items:
                break
            remaining = deadline - std_time.monotonic()
            if remaining <= 0:
                break
            try:
                items.append(MESSAGE_QUEUE.get(timeout=remaining))
            except queue.Empty:
                break

    return items


def parse_payloads(raw_batch: list[bytes]) -> list[dict]:
    global parse_errors

    parsed: list[dict] = []
    local_errors = 0
    for raw in raw_batch:
        try:
            parsed.append(json.loads(raw.decode()))
        except (json.JSONDecodeError, UnicodeDecodeError):
            local_errors += 1
    if local_errors:
        with _STATS_LOCK:
            parse_errors += local_errors
    return parsed


def write_points(points: list[Point]) -> None:
    global write_batches, points_written, write_errors

    if not points:
        return

    delay = 0.05
    for attempt in range(1, 6):
        try:
            write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=points)
            with _STATS_LOCK:
                write_batches += 1
                points_written += len(points)
            return
        except Exception as exc:
            if attempt == 5:
                with _STATS_LOCK:
                    write_errors += len(points)
                print(f"[WRITE ERROR] batch descartado após 5 tentativas "
                      f"({len(points)} pontos, worker={threading.current_thread().name}): {exc}")
                return
            jitter = random.uniform(0.8, 1.2)
            std_time.sleep(delay * jitter)
            delay *= 2


def log_stream_metrics_snapshot() -> None:
    with _STATS_LOCK:
        snap = (
            enqueued,
            dropped,
            MESSAGE_QUEUE.qsize(),
            points_written,
            parse_errors,
            write_errors,
            mqtt_received,
        )
    print(
        f"STREAM_METRICS recebidas={snap[0]} descartadas={snap[1]} "
        f"fila={snap[2]} maxsize={STREAM_QUEUE_MAXSIZE} "
        f"escritos={snap[3]} erros_parse={snap[4]} "
        f"erros_write={snap[5]} mqtt_total={snap[6]} "
        f"workers={STREAM_WORKER_COUNT}"
    )


def start_metrics_logger() -> None:
    def _loop() -> None:
        while not STOP_EVENT.wait(STREAM_METRICS_LOG_INTERVAL_S):
            log_stream_metrics_snapshot()

    threading.Thread(target=_loop, daemon=True).start()


def influx_worker_loop() -> None:
    while not STOP_EVENT.is_set() or not MESSAGE_QUEUE.empty():
        raw_batch = drain_queue(STREAM_DRAIN_BATCH_SIZE, STREAM_DRAIN_TIMEOUT_S)
        if not raw_batch:
            continue

        payloads = parse_payloads(raw_batch)
        if not payloads:
            continue

        points = [payload_to_point(p) for p in payloads]
        write_points(points)

    while True:
        raw_batch = drain_queue(STREAM_DRAIN_BATCH_SIZE, 0.01)
        if not raw_batch:
            break
        payloads = parse_payloads(raw_batch)
        if payloads:
            write_points([payload_to_point(p) for p in payloads])


def on_message(client, userdata, msg) -> None:
    global mqtt_received, enqueued, dropped

    with _STATS_LOCK:
        mqtt_received += 1
    try:
        MESSAGE_QUEUE.put_nowait(msg.payload)
        with _STATS_LOCK:
            enqueued += 1
    except queue.Full:
        with _STATS_LOCK:
            dropped += 1


def main() -> None:
    print(
        f"🌊 Stream consumer v2 [{EXPERIMENT_LABEL}] → bucket={INFLUXDB_BUCKET} "
        f"(workers={STREAM_WORKER_COUNT}, influx_batch={INFLUX_BATCH_SIZE}, "
        f"flush={INFLUX_FLUSH_INTERVAL_MS}ms, drain={STREAM_DRAIN_BATCH_SIZE}, "
        f"fila max={STREAM_QUEUE_MAXSIZE})"
    )

    start_metrics_logger()

    mqtt = MQTTConnection(on_message=on_message, use_background_loop=True)

    def _handle_shutdown(signum, frame) -> None:
        print("🛑 Sinal recebido, encerrando stream consumer v2...")
        STOP_EVENT.set()
        mqtt.stop()

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    workers = [
        threading.Thread(
            target=influx_worker_loop,
            name=f"influx-worker-{i}",
            daemon=False,
        )
        for i in range(STREAM_WORKER_COUNT)
    ]
    for worker in workers:
        worker.start()

    mqtt.connect()

    try:
        while not STOP_EVENT.is_set():
            std_time.sleep(0.25)
    finally:
        STOP_EVENT.set()
        mqtt.stop()
        for worker in workers:
            worker.join()
        shutdown_influx()
        atexit.unregister(shutdown_influx)

    log_stream_metrics_snapshot()
    print(
        f"✅ Worker v2 encerrado. Enfileiradas={enqueued}, Descartadas={dropped}, "
        f"Escritos={points_written}, ErrosParse={parse_errors}, ErrosWrite={write_errors}"
    )


if __name__ == "__main__":
    main()
