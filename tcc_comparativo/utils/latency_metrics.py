"""Registra a confirmação recebida pelo cliente após uma escrita bem-sucedida."""

import csv
import os
from sensors.clock_context import CLOCK_ID


def record_confirmed_batch(approach, records, confirmed_at_ms, confirmed_mono_ns):
    path = os.path.join(os.environ.get("EXPERIMENT_METRICS_DIR", "/app/metrics"), f"latency_{approach}.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        for message_id, created_at, created_mono_ns, clock_id in records:
            if clock_id != CLOCK_ID or int(created_mono_ns) > confirmed_mono_ns:
                raise ValueError('Relógios monotônicos incompatíveis ou intervalo negativo')
            writer.writerow((message_id, created_at, confirmed_at_ms, created_mono_ns, confirmed_mono_ns, clock_id))
