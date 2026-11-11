#!/usr/bin/env python3
"""Verifica a continuidade das amostras de CPU e memória durante a geração."""
import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path


def audit(metrics, label):
    metrics = Path(metrics)
    parse_time = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    start, end = map(parse_time, (metrics / "generator_window.txt").read_text(encoding="utf-8").split())
    if end <= start:
        raise ValueError("janela de geração inválida")
    names = ("batch_consumer", "stream_consumer", "sensor_generator")
    samples = {name: [] for name in names}
    with (metrics / f"docker_stats_{label}.csv").open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if row["name"] not in samples:
                continue
            timestamp = parse_time(row["timestamp"])
            if not start - timedelta(seconds=30) <= timestamp <= end + timedelta(seconds=30):
                continue
            if not re.fullmatch(r"\d+(?:\.\d+)?%", row["cpu_perc"].strip()):
                raise ValueError(f"CPU inválida para {row['name']}")
            if not re.fullmatch(r"\d+(?:\.\d+)?(?:B|KiB|MiB|GiB|TiB)", row["mem_usage"].split("/")[0].strip(), re.I):
                raise ValueError(f"memória inválida para {row['name']}")
            samples[row["name"]].append(timestamp)
    result = {}
    for name, times in samples.items():
        times.sort()
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
        result[name] = {
            "samples": len(times),
            "start_gap_seconds": max(0, (times[0] - start).total_seconds()) if times else None,
            "end_gap_seconds": max(0, (end - times[-1]).total_seconds()) if times else None,
            "max_gap_seconds": max(gaps, default=0) if times else None,
        }
    (metrics / "resource_coverage_audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    # shortcut: lacunas de até 30 s podem ocultar picos; reduza o limite se a análise exigir maior resolução.
    for name, info in result.items():
        if not info["samples"] or any(info[key] > 30 for key in ("start_gap_seconds", "end_gap_seconds", "max_gap_seconds")):
            raise ValueError(f"cobertura de recursos incompleta para {name}; consulte resource_coverage_audit.json")
    print("Cobertura de CPU e memória verificada durante toda a geração")


if __name__ == "__main__":
    try:
        audit(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print(f"Auditoria de recursos falhou: {exc}", file=sys.stderr)
        sys.exit(1)
