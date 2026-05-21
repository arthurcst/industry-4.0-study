from datetime import datetime, timezone
from paho.mqtt import client
from collections import deque

from utils.mqtt_conn import MQTTConnection

import json
import time
import os
import csv
import threading

from rich.live import Live
from rich.table import Table
from rich import box

# ------------------ CONFIGS ------------------ #
BUFFER = deque()
THRESHOLD = 10_000
FLUSH_INTERVAL = 60  # segundos
LAST_FLUSH = time.time()
LAST_RECEIVED = time.time()
FILES_CREATED = 0

OUTPUT_DIR = "./batches_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ------------- MÉTRICAS PARA EXIBIÇÃO ------------ #
def build_metrics_table():
    table = Table(title="📊 Métricas do Batch Processor", box=box.ROUNDED)
    table.add_column("Métrica", style="bold cyan")
    table.add_column("Valor", style="bold white")

    table.add_row("Arquivos criados", str(FILES_CREATED))
    table.add_row("Buffer atual", f"{len(BUFFER)} / {THRESHOLD}")
    tempo = f"{int(time.time() - LAST_RECEIVED)}s"
    table.add_row("Tempo desde última entrada", tempo)

    return table


# --------------- FLUSH PARA CSV ------------------ #
def write_batch_to_csv(batch):
    global FILES_CREATED
    if not batch:
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{OUTPUT_DIR}/batch_{timestamp}.csv"

    with open(filename, mode="w", newline="", encoding="utf-8") as csvfile:
        fieldnames = [
            "sensor_id",
            "production_line_id",
            "location",
            "metric",
            "unit",
            "value",
            "created_at",
            "id",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in batch:
            writer.writerow(row)

    FILES_CREATED += 1
    # print(f"✅ Batch salvo: {filename} ({len(batch)} registros)")


# --------------- FLUSH DO BUFFER ------------------ #
def flush_buffer():
    batch = list(BUFFER)
    BUFFER.clear()
    write_batch_to_csv(batch)


# --------------- HANDLER MQTT ------------------ #
def on_message(client, userdata, msg):
    global LAST_FLUSH, LAST_RECEIVED
    payload = json.loads(msg.payload.decode())
    BUFFER.append(payload)
    LAST_RECEIVED = time.time()

    now = time.time()

    if len(BUFFER) >= THRESHOLD:
        flush_buffer()
        LAST_FLUSH = now


# --------------- THREAD: DASHBOARD --------------- #
def start_live_dashboard():
    with Live(build_metrics_table(), refresh_per_second=4) as live:
        while True:
            time.sleep(0.25)
            live.update(build_metrics_table())


# --------------- THREAD: FLUSH TEMPORAL --------------- #
def start_flush_timer():
    global LAST_FLUSH
    while True:
        time.sleep(1)
        now = time.time()
        if BUFFER and now - LAST_FLUSH >= FLUSH_INTERVAL:
            flush_buffer()
            LAST_FLUSH = now


# --------------------- MAIN --------------------- #
def main():
    # Thread 1: Dashboard
    # threading.Thread(target=start_live_dashboard, daemon=True).start()

    # Thread 2: Flush por tempo
    threading.Thread(target=start_flush_timer, daemon=True).start()

    # Conexão MQTT
    mqtt_client = MQTTConnection(on_message=on_message)
    mqtt_client.connect()
    print("🚀 Batch consumer iniciado...")

    # Mantém o script vivo
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
