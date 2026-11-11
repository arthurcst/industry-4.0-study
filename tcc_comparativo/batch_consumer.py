from datetime import datetime, timezone
from collections import deque
from dotenv import load_dotenv
from utils.mqtt_conn import MQTTConnection

import json
import time
import os
import csv
import threading
import signal

from rich.live import Live
from rich.table import Table
from rich import box

load_dotenv()

# ------------------ CONFIGS ------------------ #
EXPERIMENT_LABEL = os.getenv("EXPERIMENT_LABEL", "completa")
THRESHOLD = int(os.getenv("BATCH_THRESHOLD", 10_000))
FLUSH_INTERVAL = int(os.getenv("BATCH_FLUSH_INTERVAL", 60))
OUTPUT_DIR = os.getenv("BATCH_OUTPUT_DIR", "./batches_output")

BUFFER = deque()
BUFFER_LOCK = threading.Lock()
FLUSH_LOCK = threading.Lock()
STOP_EVENT = threading.Event()
LAST_FLUSH = time.time()
LAST_RECEIVED = time.time()
FILES_CREATED = 0

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ------------- MÉTRICAS PARA EXIBIÇÃO ------------ #
def build_metrics_table():
    table = Table(
        title=f"📊 Batch Processor [{EXPERIMENT_LABEL}]", box=box.ROUNDED
    )
    table.add_column("Métrica", style="bold cyan")
    table.add_column("Valor", style="bold white")

    with BUFFER_LOCK:
        buffer_size = len(BUFFER)

    table.add_row("Experimento", EXPERIMENT_LABEL)
    table.add_row("Diretório de saída", OUTPUT_DIR)
    table.add_row("Arquivos criados", str(FILES_CREATED))
    table.add_row("Buffer atual", f"{buffer_size} / {THRESHOLD}")
    tempo = f"{int(time.time() - LAST_RECEIVED)}s"
    table.add_row("Tempo desde última entrada", tempo)

    return table


# --------------- FLUSH PARA CSV ------------------ #
def write_batch_to_csv(batch):
    global FILES_CREATED
    if not batch:
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S%f")
    filename = f"{OUTPUT_DIR}/batch_{timestamp}.csv"

    with open(filename + ".tmp", mode="x", newline="", encoding="utf-8") as csvfile:
        fieldnames = [
            "sensor_id",
            "production_line_id",
            "location",
            "metric",
            "unit",
            "value",
            "created_at",
            "created_mono_ns",
            "clock_id",
            "id",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in batch:
            writer.writerow(row)

    os.replace(filename + ".tmp", filename)
    FILES_CREATED += 1


# --------------- FLUSH DO BUFFER ------------------ #
def flush_buffer(blocking=False):
    global LAST_FLUSH

    if not FLUSH_LOCK.acquire(blocking=blocking):
        return

    try:
        with BUFFER_LOCK:
            if not BUFFER:
                return
            batch = list(BUFFER)
            BUFFER.clear()

        try:
            write_batch_to_csv(batch)
        except Exception:
            with BUFFER_LOCK:
                BUFFER.extendleft(reversed(batch))
            raise
        LAST_FLUSH = time.time()
    finally:
        FLUSH_LOCK.release()


# --------------- HANDLER MQTT ------------------ #
def on_message(client, userdata, msg):
    global LAST_RECEIVED

    payload = json.loads(msg.payload.decode())

    with BUFFER_LOCK:
        BUFFER.append(payload)
        should_flush = len(BUFFER) >= THRESHOLD

    LAST_RECEIVED = time.time()

    if should_flush:
        threading.Thread(target=flush_buffer, daemon=True).start()


# --------------- THREAD: DASHBOARD --------------- #
def start_live_dashboard():
    with Live(build_metrics_table(), refresh_per_second=4) as live:
        while True:
            time.sleep(0.25)
            live.update(build_metrics_table())


# --------------- THREAD: FLUSH TEMPORAL --------------- #
def start_flush_timer():
    while not STOP_EVENT.wait(1):
        now = time.time()
        with BUFFER_LOCK:
            has_data = bool(BUFFER)
        if has_data and now - LAST_FLUSH >= FLUSH_INTERVAL:
            flush_buffer()


# --------------------- MAIN --------------------- #
def main():
    print(
        f"🚀 Batch consumer [{EXPERIMENT_LABEL}] → {OUTPUT_DIR} "
        f"(threshold={THRESHOLD}, flush={FLUSH_INTERVAL}s)"
    )

    # threading.Thread(target=start_live_dashboard, daemon=True).start()
    timer = threading.Thread(target=start_flush_timer, daemon=True)
    timer.start()

    mqtt_client = MQTTConnection(on_message=on_message, use_background_loop=True)

    def handle_shutdown(signum, frame):
        STOP_EVENT.set()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        mqtt_client.connect()
        STOP_EVENT.wait()
    finally:
        mqtt_client.stop()
        timer.join()
        flush_buffer(blocking=True)
        print("✅ Batch consumer encerrado; buffer gravado.", flush=True)


if __name__ == "__main__":
    main()
