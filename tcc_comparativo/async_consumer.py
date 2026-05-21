from time import time
from influxdb_client.client.influxdb_client import InfluxDBClient
from influxdb_client.client.write.point import Point
from influxdb_client.client.write_api import WriteOptions, SYNCHRONOUS
from paho.mqtt import client as mqtt_client
from dotenv import load_dotenv
from utils.mqtt_conn import MQTTConnection
from datetime import datetime
from rich.live import Live
from rich.table import Table
from rich import box

import threading
import json
import os
import time as std_time

# ========== VARIÁVEIS GLOBAIS ========== #
contador = 0
LAST_RECEIVED = std_time.time()
LIVE_START_TIME = std_time.time()

# ========== CONFIGURAÇÃO INFLUXDB ========== #
load_dotenv()

INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_URL = os.getenv("INFLUXDB_URL")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG")

if INFLUXDB_TOKEN and INFLUXDB_ORG:
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)
else:
    raise ValueError("InfluxDB variables not found or not set correctly.")


# ========== FUNÇÃO DE INTERFACE ==========
def build_metrics_table():
    table = Table(title="🌊 Métricas do Stream Processor", box=box.ROUNDED)
    table.add_column("Métrica", style="bold cyan")
    table.add_column("Valor", style="bold white")

    tempo_desde_ultima = int(std_time.time() - LAST_RECEIVED)
    tempo_total = int(std_time.time() - LIVE_START_TIME)

    table.add_row("Mensagens processadas", str(contador))
    table.add_row("Tempo desde última mensagem", f"{tempo_desde_ultima}s")
    table.add_row("Tempo total de conexão", f"{tempo_total}s")

    return table


def start_live_dashboard():
    with Live(build_metrics_table(), refresh_per_second=4) as live:
        while True:
            std_time.sleep(0.25)
            live.update(build_metrics_table())


# ========== CALLBACK MQTT ==========
def on_message(client, userdata, msg):
    global contador, LAST_RECEIVED

    payload = json.loads(msg.payload.decode())

    point = (
        Point(payload["metric"])
        .tag("sensor_id", payload["sensor_id"])
        .tag("location", payload["location"])
        .tag("production_line_id", payload["production_line_id"])
        .tag("unit", payload["unit"])
        .field("value", payload["value"])
        .field("ingested_at", int(time() * 1000))
        .field("created_at", int(payload["created_at"]))
    )

    if INFLUXDB_TOKEN and INFLUXDB_ORG and INFLUXDB_BUCKET:
        write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
        contador += 1
        LAST_RECEIVED = std_time.time()


# ========== FUNÇÃO PRINCIPAL ==========
def main():
    # threading.Thread(target=start_live_dashboard, daemon=True).start()

    mqtt = MQTTConnection()
    mqtt.client.on_message = on_message
    mqtt.connect()


if __name__ == "__main__":
    main()
