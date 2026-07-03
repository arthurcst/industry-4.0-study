from paho.mqtt import client as mqtt_client
from dotenv import load_dotenv

import logging
import uuid
import os

load_dotenv()

logging.basicConfig(level=logging.INFO)


def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    topic = os.getenv("MQTT_TOPIC", "factory/sensors")
    qos = int(os.getenv("MQTT_QOS", "1"))
    client.subscribe(topic, qos=qos)


def on_disconnect(client, userdata, rc):
    print(f"🔌 Disconnected with result code {rc}")


class MQTTConnection:
    def __init__(
        self,
        client_id=None,
        broker: str | None = None,
        port: int | None = None,
        on_message=None,
        use_background_loop: bool = False,
    ):
        self.client_id = client_id or f"mqtt-stream-consumer-{uuid.uuid4()}"
        self.topic = os.getenv("MQTT_TOPIC", "factory/sensors")
        self.broker = broker or os.getenv("MQTT_BROKER", "localhost")
        self.PORT = port or int(os.getenv("MQTT_PORT", 1883))
        self.use_background_loop = use_background_loop

        print(
            f"MQTT broker: {self.broker}, port: {self.PORT}, "
            f"client_id: {self.client_id}, background_loop: {use_background_loop}"
        )

        self.client = mqtt_client.Client(client_id=self.client_id, clean_session=False)
        self.client.on_connect = on_connect
        self.client.on_message = on_message
        self.client.on_disconnect = on_disconnect
        self.client.enable_logger()

        if use_background_loop:
            inflight = int(os.getenv("MQTT_MAX_INFLIGHT", "20"))
            self.client.max_inflight_messages_set(inflight)
            self.client.max_queued_messages_set(0)

    def connect(self):
        self.client.reconnect_delay_set(1, 120)
        self.client.connect(self.broker, self.PORT)

        if self.use_background_loop:
            self.client.loop_start()
            print(
                f"MQTT loop em background — {self.broker}:{self.PORT} "
                f"(client_id={self.client_id})"
            )
            return

        self.client.loop_forever()
        print(
            f"Connected to MQTT broker at {self.broker}:{self.PORT} "
            f"with client ID {self.client_id}"
        )

    def stop(self):
        try:
            self.client.loop_stop()
        except Exception:
            pass
        try:
            self.client.disconnect()
        except Exception:
            pass
