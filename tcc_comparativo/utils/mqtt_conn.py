from paho.mqtt import client as mqtt_client
from dotenv import load_dotenv

import logging
import uuid
import os

load_dotenv()  # Carrega as variáveis do .env para os envs do sistema

logging.basicConfig(level=logging.INFO)


def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    client.subscribe(os.getenv("MQTT_TOPIC", "factory/sensors"))


def on_disconnect(client, userdata, rc):
    print(f"🔌 Disconnected with result code {rc}")


class MQTTConnection:
    def __init__(
        self,
        client_id=None,
        broker: str | None = None,
        port: int | None = None,
        on_message=None,
    ):
        self.client_id = client_id or f"mqtt-stream-consumer-{uuid.uuid4()}"
        self.topic = os.getenv("MQTT_TOPIC", "factory/sensors")
        self.broker = broker or os.getenv("MQTT_BROKER", "localhost")
        self.PORT = port or int(os.getenv("MQTT_PORT", 1883))

        print(
            f"MQTT broker: {self.broker}, port: {self.PORT}, client_id: {self.client_id}"
        )

        self.client = mqtt_client.Client(client_id=self.client_id)
        self.client.on_connect = on_connect
        self.client.on_message = on_message
        self.client.on_disconnect = on_disconnect
        self.client.enable_logger()

    def connect(self):
        self.client.reconnect_delay_set(1, 120)
        self.client.connect(self.broker, self.PORT)
        self.client.loop_forever()

        print(
            f"Connected to MQTT broker at {self.broker}:{self.PORT} with client ID {self.client_id}"
        )
