"""Uma falha real na conexão com o InfluxDB não deve produzir confirmação."""

import sys
import time

sys.path.insert(0, "/app")
import async_consumer_v2 as stream
from sensors.clock_context import CLOCK_ID


def main():
    payload = {
        "id": "failure-check-stream", "created_at": int(time.time() * 1000),
        "created_mono_ns": time.monotonic_ns(), "clock_id": CLOCK_ID,
        "sensor_id": "test", "location": "test", "production_line_id": "test",
        "metric": "test", "unit": "C", "value": 1,
    }
    stream.write_points([stream.payload_to_point(payload)], [payload])
    assert stream.write_errors == 1, "Falha de conexão não foi registrada"
    with open("/app/metrics/latency_stream.csv", encoding="utf-8") as source:
        assert payload["id"] not in source.read(), "Confirmação falsa após erro do InfluxDB"
    assert stream.pending_files(), "Mensagem não foi preservada para reprocessamento"
    print("Indisponibilidade real do InfluxDB não gerou confirmação falsa e preservou a mensagem.")


if __name__ == "__main__":
    main()
