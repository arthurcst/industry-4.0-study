from paho.mqtt import client
from datetime import datetime
from factory_sensors import SENSORS_01, get_sensors_by_location
from dotenv import load_dotenv
from faker import Faker
from rich.live import Live
from rich.table import Table
from rich import box

import threading
import asyncio
import random
import time
import json
import os

faker = Faker()
load_dotenv()

# MQTT
BROKER = os.getenv("MQTT_BROKER")
PORT = int(os.getenv("MQTT_PORT", 1883))
TOPIC = os.getenv("MQTT_TOPIC")
CLIENT_ID = os.getenv("MQTT_CLIENT_ID")
RATE_MODIFIER = int(os.getenv("RATE_MODIFIER", 1))

# Execução
EXECUTION_TIME = 30 * 60  # segundos
START_TIME = time.time()

# Métricas compartilhadas
metrics = {
    "total": 0,
    "por_maquina": {},  # { "triturador_01": {"temperatura": 10, "pressao": 5} }
    "conexoes_mqtt": {},
    "threads": 0,
}
metrics_lock = threading.Lock()


def build_metrics_table():
    with metrics_lock:
        table = Table(title="📡 Gerador de Dados", box=box.ROUNDED)
        table.add_column("Métrica", style="bold cyan")
        table.add_column("Valor", style="bold white")

        tempo_restante = max(0, int(EXECUTION_TIME - (time.time() - START_TIME)))
        sensores_ativos = sum(
            len(sensores) for sensores in metrics["por_maquina"].values()
        )
        maquinas_ativas = len(metrics["por_maquina"])
        conexoes_on = sum(1 for status in metrics["conexoes_mqtt"].values() if status)

        elapsed_time = max(1, time.time() - START_TIME)
        mensagens_por_segundo = metrics["total"] / elapsed_time
        mensagens_por_minuto = mensagens_por_segundo * 60

        table.add_row("Mensagens enviadas", str(metrics["total"]))
        table.add_row("Mensagens por segundo", f"{mensagens_por_segundo:.2f} msg/s")
        table.add_row("Mensagens por minuto", f"{mensagens_por_minuto:.2f} msg/min")
        table.add_row("Máquinas ativas", str(maquinas_ativas))
        table.add_row("Sensores ativos", str(sensores_ativos))
        table.add_row("Threads ativas", str(metrics["threads"]))
        table.add_row("MQTT status", f"{conexoes_on}/{maquinas_ativas} ON")
        table.add_row("Tempo restante", f"{tempo_restante}s")

        return table


def start_live_dashboard():
    with Live(build_metrics_table(), refresh_per_second=2) as live:
        while time.time() - START_TIME < EXECUTION_TIME:
            time.sleep(0.5)
            live.update(build_metrics_table())


async def generate_sensor_data(sensor):
    ts = int(time.time() * 1000)

    if "range" in sensor:
        value = round(random.uniform(*sensor["range"]), 2)
    elif "values" in sensor:
        value = random.choices(sensor["values"], sensor["weight"])[0]
    else:
        value = None

    return {
        "sensor_id": sensor["sensor_id"],
        "production_line_id": sensor["production_line_id"],
        "location": sensor["location"],
        "metric": sensor["metric"],
        "unit": sensor["unit"],
        "value": value,
        "created_at": ts,
        "id": faker.uuid4(),
    }


async def sensor_task(sensor, end_time, mqtt_client):
    maquina = sensor["location"]
    metric = sensor["metric"]
    with metrics_lock:
        metrics["por_maquina"].setdefault(maquina, {})
        metrics["por_maquina"][maquina].setdefault(metric, 0)

    while True:
        now = asyncio.get_event_loop().time()
        if now >= end_time:
            break

        data = await generate_sensor_data(sensor)
        payload = json.dumps(data)

        if TOPIC:
            result = mqtt_client.publish(TOPIC, payload, qos=1)
            if result[0] == 0:  # sucesso
                with metrics_lock:
                    metrics["total"] += 1
                    metrics["por_maquina"][maquina][metric] += 1

        await asyncio.sleep(sensor.get("frequency", 1.0))


def generate_machine_thread(machine_name, sensors, execution_time):
    mqtt_client = client.Client(client_id=f"{CLIENT_ID}_{machine_name}")

    try:
        mqtt_client.connect(BROKER, PORT)  # type: ignore
        mqtt_client.loop_start()
        with metrics_lock:
            metrics["conexoes_mqtt"][machine_name] = True
    except:
        with metrics_lock:
            metrics["conexoes_mqtt"][machine_name] = False
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    end_time = loop.time() + execution_time
    tasks = [sensor_task(sensor, end_time, mqtt_client) for sensor in sensors]

    loop.run_until_complete(asyncio.gather(*tasks))
    loop.close()
    mqtt_client.loop_stop()


def main():
    print("🔧 Iniciando o gerador de dados...")
    threads = []

    # Dashboard
    dashboard_thread = threading.Thread(target=start_live_dashboard, daemon=True)
    dashboard_thread.start()

    for location, sensors in get_sensors_by_location(
        SENSORS_01, rate_modifier=RATE_MODIFIER
    ).items():
        thread = threading.Thread(
            target=generate_machine_thread,
            args=(location, sensors, EXECUTION_TIME),
        )
        thread.start()
        threads.append(thread)

    with metrics_lock:
        metrics["threads"] = len(threads)

    for thread in threads:
        thread.join()

    print("✅ Geração de dados finalizada.")


if __name__ == "__main__":
    main()
    while True:
        time.sleep(1)
