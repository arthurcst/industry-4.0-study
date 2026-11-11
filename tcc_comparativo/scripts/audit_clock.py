#!/usr/bin/env python3
"""Detecta saltos de relógio que comprometem as latências de uma execução."""
import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


def stream_clock_evidence(path):
    previous = None
    steps = []
    negative_count = 0
    negative_min_ms = 0
    with path.open(newline="", encoding="utf-8") as source:
        for number, row in enumerate(csv.reader(source), 1):
            created = int(row[1])
            confirmed = int(row[2])
            if previous is not None and confirmed < previous:
                steps.append({"row": number, "delta_ms": confirmed - previous})
            if confirmed < created:
                negative_count += 1
                negative_min_ms = min(negative_min_ms, confirmed - created)
            previous = confirmed
    return steps, negative_count, negative_min_ms


def windows_clock_changes(start, end):
    if sys.platform != "win32":
        raise RuntimeError("Auditoria de relógio do host requer Windows")
    command = f"$startMs = {int(start.timestamp() * 1000)}\n$endMs = {int(end.timestamp() * 1000)}\n" + r'''
$ErrorActionPreference = 'Stop'
$start = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$startMs).LocalDateTime
$end = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$endMs).LocalDateTime
try {
    $events = @(Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-General'; Id=1; StartTime=$start; EndTime=$end} -ErrorAction Stop)
} catch {
    if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') { $events = @() } else { throw }
}
$changes = @(foreach ($event in $events) {
    [xml]$xml = $event.ToXml()
    $data = @{}
    foreach ($node in $xml.Event.EventData.Data) { $data[$node.Name] = $node.'#text' }
    $delta = ([datetime]$data.NewTime - [datetime]$data.OldTime).TotalMilliseconds
    if ([math]::Abs($delta) -ge 1) {
        @{time_utc=$event.TimeCreated.ToUniversalTime().ToString('o'); delta_ms=[math]::Round($delta, 3); record_id=$event.RecordId}
    }
})
ConvertTo-Json -InputObject $changes -Compress
'''
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def audit(metrics):
    metrics = Path(metrics)
    started, finished = (metrics / "generator_window.txt").read_text(encoding="utf-8").split()
    start = datetime.fromisoformat(started.replace("Z", "+00:00")) - timedelta(minutes=2)
    end = datetime.fromisoformat(finished.replace("Z", "+00:00")) + timedelta(minutes=12)
    backsteps, negative_count, negative_min_ms = stream_clock_evidence(metrics / "latency_stream.csv")
    with (metrics / "latency_stream.csv").open(newline="", encoding="utf-8") as source:
        first = next(csv.reader(source), [])
    monotonic_format = len(first) == 6
    result = {
        "window_start": start.isoformat(), "window_end": end.isoformat(),
        "stream_backsteps": backsteps,
        "negative_wall_interval_count": negative_count,
        "negative_wall_interval_min_ms": negative_min_ms,
        "latency_clock": "monotonic" if monotonic_format else "wall",
        "windows_clock_changes": windows_clock_changes(start, end),
    }
    (metrics / "clock_audit_v2.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if backsteps or (negative_count and not monotonic_format) or result["windows_clock_changes"]:
        raise ValueError("inconsistência de timestamps ou ajuste de relógio detectado; consulte clock_audit_v2.json")
    print(f"Auditoria: recuos nas confirmações={len(backsteps)}, intervalos de relógio civil negativos={negative_count}, ajustes Windows={len(result['windows_clock_changes'])}")


if __name__ == "__main__":
    try:
        audit(sys.argv[1])
    except Exception as exc:
        print(f"Auditoria de relógio falhou: {exc}", file=sys.stderr)
        sys.exit(1)
