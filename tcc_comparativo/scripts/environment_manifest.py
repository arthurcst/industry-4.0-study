#!/usr/bin/env python3
"""Congela, arquiva e confere o ambiente da série experimental."""
import hashlib
import json
import os
import platform
import runpy
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
IMAGES = [
    'tcc_comparativo-batch-consumer:latest', 'tcc_comparativo-stream-consumer:latest',
    'tcc_comparativo-sensor-generator:latest', 'postgres:14', 'influxdb:2.7',
    'eclipse-mosquitto:2.0', 'grafana/grafana:10.4.5',
]
PATTERNS = ['Dockerfile.*', 'requirements.txt', 'docker-compose.yml', 'docker.env.reduzida',
            'docker.env.intermediaria', 'docker.env.completa', 'batch_consumer.py',
            'async_consumer_v2.py', 'cronjob_executor.py', 'start_experiment.sh', 'run_all_experiments.sh', 'batch_crontab', 'script_docker.sh',
            'sensors/*.py', 'utils/*.py', 'scripts/*.py', 'scripts/*.sh', 'scripts/*.ps1',
            'tests/*.py', 'tests/*.ps1', 'tests/integration/*.py', 'tests/integration/*.yaml', 'tests/fixtures/*.csv',
            'grafana/metrics/*.sql', 'grafana/dashboards/*.json',
            'grafana/provisioning/**/*.yaml', 'mosquitto/mosquitto_config/*']
RUNNING = {'batch_consumer': IMAGES[0], 'stream_consumer': IMAGES[1], 'sensor_generator': IMAGES[2],
           'postgres': IMAGES[3], 'influxdb': IMAGES[4], 'mosquitto': IMAGES[5], 'grafana': IMAGES[6]}


def call(*args):
    return subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace').stdout.strip()


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def images():
    return {name: call('docker', 'image', 'inspect', name, '--format', '{{.Id}}') for name in IMAGES}


def host_runtime():
    return {'python': platform.python_version(), 'dependencies': call(sys.executable, '-m', 'pip', 'freeze').splitlines()}


def sources():
    paths = {path for pattern in PATTERNS for path in ROOT.glob(pattern) if path.is_file()}
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(paths)}


def prepare(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    probe = call(sys.executable, '-I', '-X', 'utf8', str(ROOT / 'scripts/clock_probe.py'))
    manifest = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'images': images(), 'sources': sources(),
                'clock_probe': json.loads(probe), 'host_platform': platform.platform(), 'host_cpu': platform.processor(),
                'host_logical_cpus': os.cpu_count(), 'host_runtime': host_runtime(), 'python_dependencies': {}}
    rate_code = "import json,sys;sys.path.insert(0,'/app/sensors');from factory_sensors import SENSORS_01,get_sensors_by_location;print(json.dumps({k:sum(1/s.get('frequency',1.0) for v in get_sensors_by_location(SENSORS_01,active_asset_count=n).values() for s in v) for k,n in [('reduzida',25),('intermediaria',50),('completa',100)]}))"
    rates = json.loads(call('docker', 'run', '--rm', '--entrypoint', 'python', IMAGES[2], '-c', rate_code))
    expected = runpy.run_path(str(ROOT / 'scripts/audit_workload.py'))['RATES']
    if any(abs(rates[name] - expected[name]) > 1e-9 for name in expected):
        raise ValueError('As taxas teóricas dos sensores diferem da auditoria de carga')
    manifest['theoretical_rates'] = rates
    for image in IMAGES[:3]:
        manifest['python_dependencies'][image] = call('docker', 'run', '--rm', '--entrypoint', 'python', image, '-m', 'pip', 'freeze').splitlines()
    manifest['batch_debian_packages'] = call('docker', 'run', '--rm', '--entrypoint', 'dpkg-query', IMAGES[0], '-W').splitlines()
    archive = directory / 'images.tar'
    subprocess.run(['docker', 'save', '-o', str(archive), *IMAGES], cwd=ROOT, check=True)
    with tarfile.open(archive) as source:
        saved = json.load(source.extractfile('manifest.json'))
    tags = {tag for item in saved for tag in (item.get('RepoTags') or [])}
    if not set(IMAGES).issubset(tags):
        raise ValueError(f'Imagens ausentes do arquivo: {set(IMAGES) - tags}')
    manifest['archive_sha256'] = digest(archive)
    source_archive = directory / 'sources.zip'
    with ZipFile(source_archive, 'x', compression=ZIP_DEFLATED) as bundle:
        for relative in manifest['sources']:
            bundle.write(ROOT / relative, relative)
    manifest['source_archive_sha256'] = digest(source_archive)
    if manifest['images'] != images() or manifest['sources'] != sources() or manifest['host_runtime'] != host_runtime():
        raise ValueError('O ambiente mudou durante a preparação')
    path = directory / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Ambiente registrado e imagens preservadas em {directory}')


def check(path, running=False):
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    if manifest['images'] != images():
        raise ValueError('As imagens locais diferem do ambiente registrado')
    if manifest['sources'] != sources():
        raise ValueError('Os arquivos do experimento diferem do ambiente registrado')
    if manifest['host_runtime'] != host_runtime():
        raise ValueError('O Python local ou suas dependências diferem do ambiente registrado')
    if running:
        for name, image in RUNNING.items():
            actual = call('docker', 'inspect', name, '--format', '{{.Image}}')
            if actual != manifest['images'][image]:
                raise ValueError(f'O container {name} usa imagem diferente da registrada')
    print('Ambiente e imagens conferidos')


def snapshot(path):
    script = "$m=Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory; $c=Get-CimInstance Win32_Processor | Select-Object -First 1; @{available_mb=$m.AvailableMBytes; committed_bytes=$m.CommittedBytes; commit_limit_bytes=$m.CommitLimit; cpu_percent=$c.LoadPercentage} | ConvertTo-Json -Compress"
    host = json.loads(call('powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script))
    host['timestamp_utc'] = datetime.now(timezone.utc).isoformat()
    host['running_containers'] = call('docker', 'ps', '--format', '{{.Names}}').splitlines()
    Path(path).write_text(json.dumps(host, indent=2), encoding='utf-8')


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'prepare': prepare(sys.argv[2])
        elif sys.argv[1] == 'check': check(sys.argv[2])
        elif sys.argv[1] == 'check-running': check(sys.argv[2], running=True)
        elif sys.argv[1] == 'snapshot': snapshot(sys.argv[2])
        else: raise ValueError('Comando desconhecido')
    except Exception as exc:
        print(f'Erro no ambiente experimental: {exc}', file=sys.stderr)
        sys.exit(1)
