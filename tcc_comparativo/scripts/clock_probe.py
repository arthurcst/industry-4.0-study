#!/usr/bin/env python3
"""Confere a referência e a ordem monotônica entre os três containers."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ["tcc_comparativo-sensor-generator:latest", "tcc_comparativo-batch-consumer:latest", "tcc_comparativo-stream-consumer:latest"]
SOURCE = """import json,time,os
from sensors.clock_context import CLOCK_ID
with open('/probe/sample.json','w') as f: json.dump({'clock_id':CLOCK_ID,'monotonic_ns':time.monotonic_ns(),'namespace':os.readlink('/proc/self/ns/time')},f)
"""
TARGET = """import json,time,os
from sensors.clock_context import CLOCK_ID
with open('/probe/sample.json') as f: s=json.load(f)
print(json.dumps({'clock_id':CLOCK_ID,'namespace':os.readlink('/proc/self/ns/time'),'delta_ns':time.monotonic_ns()-s['monotonic_ns'],'same_clock':CLOCK_ID==s['clock_id']}))
"""


def probe():
    with tempfile.TemporaryDirectory(dir=ROOT / 'tests') as directory:
        mount = f"{directory}:/probe"
        base = ['docker', 'run', '--rm', '--entrypoint', 'python', '-v', mount]
        subprocess.run(base + [IMAGES[0], '-c', SOURCE], check=True, capture_output=True, text=True)
        source = json.loads((Path(directory) / 'sample.json').read_text(encoding='utf-8'))
        results = []
        for image in IMAGES[1:]:
            process = subprocess.run(base + [image, '-c', TARGET], check=True, capture_output=True, text=True)
            result = json.loads(process.stdout)
            if not result['same_clock'] or not 0 < result['delta_ns'] < 120_000_000_000:
                raise ValueError(f'Relógio incompatível em {image}: {result}')
            results.append({'image': image, **result})
        return {'generator': source, 'consumers': results}


if __name__ == '__main__':
    try:
        print(json.dumps(probe(), indent=2))
    except Exception as exc:
        print(f'Teste de relógio falhou: {exc}', file=sys.stderr)
        sys.exit(1)
