import json
import time
import sys
from paho.mqtt import publish
sys.path.insert(0, '/app')
from sensors.clock_context import CLOCK_ID

payload = {
    "id": "shutdown-buffer-test", "created_at": int(time.time() * 1000),
    "created_mono_ns": time.monotonic_ns(), "clock_id": CLOCK_ID,
    "sensor_id": "test", "production_line_id": "test", "location": "test",
    "metric": "temperature", "unit": "C", "value": 1,
}
publish.single("factory/sensors", json.dumps(payload), hostname="mosquitto", qos=1)
print("Mensagem de teste publicada")
