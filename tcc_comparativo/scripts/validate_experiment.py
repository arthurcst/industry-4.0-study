#!/usr/bin/env python3
"""Interrompe a série se a execução não puder ser reconciliada."""
import csv
import json
import re
import sys
from pathlib import Path


def validate(metrics, label):
    metrics = Path(metrics)
    summary = json.loads((metrics / f"summary_{label}.json").read_text(encoding="utf-8"))
    generator = (metrics / "generator.log").read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"(\d+) mensagens em \d+s", generator)
    if not matches or int(matches[-1]) == 0:
        raise ValueError("total produzido não encontrado no log do gerador")
    expected = int(matches[-1])
    batch_records = {}
    clocks = set()
    for approach, storage in (("batch", "postgres"), ("stream", "influxdb")):
        data = summary[storage]
        if data.get("total_records") != expected or data.get("latency_count") != expected:
            raise ValueError(f"{approach}: contagens não correspondem ao total produzido ({expected}): {data}")
        if data.get("latency_negative_count") != 0:
            raise ValueError(f"{approach}: latência negativa")
        with (metrics / f"latency_{approach}.csv").open(newline="", encoding="utf-8") as source:
            seen = set()
            for row in csv.reader(source):
                if len(row) != 6 or not row[5] or int(row[3]) <= 0 or int(row[4]) < int(row[3]):
                    raise ValueError(f"{approach}: confirmação monotônica inválida")
                if not row[0] or row[0] in seen:
                    raise ValueError(f"{approach}: identificador ausente ou duplicado")
                seen.add(row[0])
                clocks.add(row[5])
                origin = (row[1], row[3], row[5])
                if approach == "batch":
                    batch_records[row[0]] = origin
                elif batch_records.pop(row[0], None) != origin:
                    raise ValueError("identificador ou timestamps de origem diferem entre as abordagens")
        if len(seen) != expected:
            raise ValueError(f"{approach}: confirmações ausentes ou duplicadas")
    if batch_records:
        raise ValueError("os identificadores confirmados nas abordagens diferem")
    if len(clocks) != 1:
        raise ValueError("as confirmações usam referências de relógio diferentes")
    if summary["batch_files"].get("total_rows_in_csvs") != expected:
        raise ValueError("o total de registros nos lotes processados difere do gerador")
    if (summary["batch_throughput"].get("total_records_processed") != expected
            or summary["batch_throughput"].get("batches_processed") != summary["batch_files"].get("csv_files")):
        raise ValueError("o log de processamento dos lotes está incompleto ou duplicado")
    batch_pending = list((metrics.parent / f"batches_output_{label}").glob("*"))
    if batch_pending:
        raise ValueError(f"batch possui {len(batch_pending)} arquivos não processados")
    pending = list((metrics / "stream_pending").glob("*"))
    if pending:
        raise ValueError(f"stream possui {len(pending)} arquivos pendentes")
    stream = summary["stream_consumer"]
    for field in ("dropped", "queue_pending", "parse_errors", "write_errors"):
        if stream.get(field) != 0:
            raise ValueError(f"stream: {field}={stream.get(field)}")
    if (stream.get("mqtt_total_received") != expected or stream.get("points_written") != expected
            or stream.get("contador") != expected):
        raise ValueError("as contagens do consumidor stream diferem do gerador")
    print(f"Validação: {expected} registros produzidos e confirmados em cada abordagem")


if __name__ == "__main__":
    try:
        validate(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print(f"Validação da execução falhou: {exc}", file=sys.stderr)
        sys.exit(1)
