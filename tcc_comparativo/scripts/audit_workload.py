#!/usr/bin/env python3
"""Confere o volume produzido contra a carga teórica do cenário."""
import json
import re
import sys
from pathlib import Path

RATES = {'reduzida': 62.2, 'intermediaria': 124.4, 'completa': 248.8}


def audit(metrics, label):
    metrics = Path(metrics)
    params = dict(line.split('=', 1) for line in (metrics / 'parameters.env').read_text(encoding='utf-8').splitlines() if '=' in line)
    duration = int(params['EXECUTION_TIME_SECONDS'])
    matches = re.findall(r'(\d+) mensagens em \d+s', (metrics / 'generator.log').read_text(encoding='utf-8', errors='replace'))
    if not matches or duration <= 0:
        raise ValueError('volume produzido ou duração indisponível')
    produced = int(matches[-1])
    nominal = RATES[label]
    realized = produced / duration
    ratio = realized / nominal
    result = {'theoretical_messages_per_second': nominal, 'nominal_duration_seconds': duration,
              'messages_produced': produced, 'messages_per_nominal_second': realized,
              'ratio_to_theoretical': ratio, 'accepted_ratio': [0.95, 1.05]}
    (metrics / 'workload_audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if not 0.95 <= ratio <= 1.05:
        raise ValueError(f'volume produzido equivale a {ratio:.1%} do teórico; consulte workload_audit.json')
    print(f'Carga conferida: {realized:.2f} mensagens por segundo nominal ({ratio:.1%} da taxa teórica)')


if __name__ == '__main__':
    try:
        audit(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print(f'Auditoria de carga falhou: {exc}', file=sys.stderr)
        sys.exit(1)
