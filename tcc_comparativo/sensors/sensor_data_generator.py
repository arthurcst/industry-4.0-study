from paho.mqtt import client
from factory_sensors import SENSORS_01, get_sensors_by_location
from clock_context import CLOCK_ID
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
import sys

load_dotenv()

# MQTT
BROKER = os.getenv("MQTT_BROKER")
PORT = int(os.getenv("MQTT_PORT", 1883))
TOPIC = os.getenv("MQTT_TOPIC")
CLIENT_ID = os.getenv("MQTT_CLIENT_ID")
ACTIVE_ASSET_COUNT = int(os.getenv("ACTIVE_ASSET_COUNT", "100"))
EXPERIMENT_LABEL = os.getenv("EXPERIMENT_LABEL", "completa")
EXPERIMENT_SEED = os.getenv("EXPERIMENT_SEED", "20261101")

# Execução
EXECUTION_TIME = int(os.getenv("EXECUTION_TIME_SECONDS", 3600))
START_TIME = time.time()

# Métricas compartilhadas
metrics = {
    "total": 0,
    "por_maquina": {},
    "conexoes_mqtt": {},
    "threads": 0,
    "erros_publicacao": 0,
    "erros_threads": 0,
}
metrics_lock = threading.Lock()


def build_metrics_table():
    with metrics_lock:
        table = Table(
            title=f"📡 Gerador de Dados [{EXPERIMENT_LABEL}]", box=box.ROUNDED
        )
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

        table.add_row("Experimento", EXPERIMENT_LABEL)
        table.add_row("Mensagens enviadas", str(metrics["total"]))
        table.add_row("Mensagens por segundo", f"{mensagens_por_segundo:.2f} msg/s")
        table.add_row("Mensagens por minuto", f"{mensagens_por_minuto:.2f} msg/min")
        table.add_row("Ativos ativos", str(maquinas_ativas))
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


def sensor_randomness(sensor):
    seed = f"{EXPERIMENT_SEED}:{sensor['location']}:{sensor['metric']}"
    value_random = random.Random(seed)
    value_faker = Faker()
    value_faker.seed_instance(seed)
    phase_seconds = random.Random(f"{seed}:phase").uniform(
        0, sensor.get("frequency", 1.0)
    )
    return value_random, value_faker, phase_seconds


async def generate_sensor_data(sensor, value_random, value_faker):
    created_mono_ns = time.monotonic_ns()
    ts = int(time.time() * 1000)

    if "range" in sensor:
        value = round(value_random.uniform(*sensor["range"]), 2)
    elif "values" in sensor:
        value = value_random.choices(sensor["values"], sensor["weight"])[0]
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
        "created_mono_ns": created_mono_ns,
        "clock_id": CLOCK_ID,
        "id": value_faker.uuid4(),
    }


async def sensor_task(sensor, end_time, mqtt_client):
    maquina = sensor["location"]
    metric = sensor["metric"]
    value_random, value_faker, phase_seconds = sensor_randomness(sensor)
    with metrics_lock:
        metrics["por_maquina"].setdefault(maquina, {})
        metrics["por_maquina"][maquina].setdefault(metric, 0)

    await asyncio.sleep(phase_seconds)

    while True:
        now = asyncio.get_event_loop().time()
        if now >= end_time:
            break

        data = await generate_sensor_data(sensor, value_random, value_faker)
        payload = json.dumps(data)

        if TOPIC:
            result = mqtt_client.publish(TOPIC, payload, qos=1)
            if result[0] == 0:
                with metrics_lock:
                    metrics["total"] += 1
                    metrics["por_maquina"][maquina][metric] += 1
            else:
                with metrics_lock:
                    metrics["erros_publicacao"] += 1

        await asyncio.sleep(sensor.get("frequency", 1.0))


def generate_machine_thread(machine_name, sensors, execution_time):
    mqtt_client = client.Client(client_id=f"{CLIENT_ID}_{machine_name}")

    try:
        mqtt_client.connect(BROKER, PORT)  # type: ignore
        mqtt_client.loop_start()
        with metrics_lock:
            metrics["conexoes_mqtt"][machine_name] = True
    except Exception:
        with metrics_lock:
            metrics["conexoes_mqtt"][machine_name] = False
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    end_time = loop.time() + execution_time
    tasks = [sensor_task(sensor, end_time, mqtt_client) for sensor in sensors]

    try:
        loop.run_until_complete(asyncio.gather(*tasks))
    except Exception as exc:
        with metrics_lock:
            metrics["erros_threads"] += 1
        print(f"❌ Falha no gerador de {machine_name}: {exc}", flush=True)
    finally:
        loop.close()
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


def main():
    print(
        f"🔧 Iniciando gerador [{EXPERIMENT_LABEL}] "
        f"(ativos={ACTIVE_ASSET_COUNT}, seed={EXPERIMENT_SEED}, "
        f"duração={EXECUTION_TIME}s)..."
    )
    threads = []

    dashboard_thread = threading.Thread(target=start_live_dashboard, daemon=True)
    dashboard_thread.start()

    for location, sensors in get_sensors_by_location(
        SENSORS_01, active_asset_count=ACTIVE_ASSET_COUNT
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

    elapsed = time.time() - START_TIME
    print(
        f"✅ Geração finalizada [{EXPERIMENT_LABEL}]: "
        f"{metrics['total']} mensagens em {elapsed:.0f}s."
    )
    if (len(metrics["conexoes_mqtt"]) != ACTIVE_ASSET_COUNT
            or not all(metrics["conexoes_mqtt"].values())
            or len(metrics["por_maquina"]) != ACTIVE_ASSET_COUNT
            or any(not count for sensors in metrics["por_maquina"].values() for count in sensors.values())
            or metrics["erros_publicacao"] or metrics["erros_threads"]):
        print(f"❌ Falha no gerador: publicações={metrics['erros_publicacao']}, threads={metrics['erros_threads']}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
