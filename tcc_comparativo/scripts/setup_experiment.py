#!/usr/bin/env python3
"""Cria tabela PostgreSQL e bucket InfluxDB conforme o .env ativo."""

import os
import sys


def _bootstrap_paths():
    """Evita KeyError/FileNotFoundError ao importar deps no WSL (/mnt/*)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    os.chdir(project_dir)
    if sys.path and os.path.abspath(sys.path[0]) == script_dir:
        sys.path.pop(0)


_bootstrap_paths()

import argparse

import psycopg2
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)
load_dotenv(os.path.join(project_dir, "docker.env"))

EXPERIMENT_LABEL = os.getenv("EXPERIMENT_LABEL", "1x")
PG_TABLE = os.getenv("PG_TABLE", "sensor_data")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "my-org")


def resolve_host(service_host: str) -> str:
    """Host: mapeia serviços Docker → localhost. Container: usa hostname da rede."""
    if os.path.exists("/.dockerenv"):
        return service_host
    if service_host in ("postgres", "influxdb", "mosquitto"):
        return "localhost"
    return service_host


_influx_url = os.getenv("INFLUXDB_URL", "http://localhost:8086")
if not os.path.exists("/.dockerenv"):
    _influx_url = _influx_url.replace("http://influxdb:", "http://localhost:")
INFLUXDB_URL = _influx_url
PG_HOST = resolve_host(os.getenv("PG_HOST", "localhost"))
PG_PORT = os.getenv(
    "PG_PORT_HOST" if PG_HOST == "localhost" else "PG_PORT",
    "5434" if PG_HOST == "localhost" else "5432",
)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    id SERIAL PRIMARY KEY,
    sensor_id VARCHAR(50),
    production_line_id VARCHAR(50),
    location VARCHAR(100),
    metric VARCHAR(50),
    unit VARCHAR(20),
    ingested_at BIGINT,
    value TEXT,
    created_at BIGINT,
    batch_id VARCHAR(100)
);
"""


def setup_postgres():
    conn = psycopg2.connect(
        dbname=os.getenv("PG_DB", "iot_batch"),
        user=os.getenv("PG_USER", "grafana"),
        password=os.getenv("PG_PASSWORD", "grafana"),
        host=PG_HOST,
        port=PG_PORT,
    )
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute(CREATE_TABLE_SQL.format(table=PG_TABLE))
    cursor.close()
    conn.close()
    print(f"✅ PostgreSQL: tabela '{PG_TABLE}' pronta")


def setup_influx():
    if not INFLUXDB_BUCKET or not INFLUXDB_TOKEN:
        print("⚠️ InfluxDB: bucket/token não configurados, pulando")
        return

    client = InfluxDBClient(
        url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG
    )
    buckets_api = client.buckets_api()
    org = client.organizations_api().find_organizations(org=INFLUXDB_ORG)
    if not org:
        client.close()
        raise RuntimeError(f"Organização InfluxDB '{INFLUXDB_ORG}' não encontrada")

    org_id = org[0].id
    existing = buckets_api.find_bucket_by_name(INFLUXDB_BUCKET)
    if existing:
        print(f"ℹ️ InfluxDB: bucket '{INFLUXDB_BUCKET}' já existe")
    else:
        buckets_api.create_bucket(bucket_name=INFLUXDB_BUCKET, org_id=org_id)
        print(f"✅ InfluxDB: bucket '{INFLUXDB_BUCKET}' criado")

    client.close()


def truncate_postgres():
    conn = psycopg2.connect(
        dbname=os.getenv("PG_DB", "iot_batch"),
        user=os.getenv("PG_USER", "grafana"),
        password=os.getenv("PG_PASSWORD", "grafana"),
        host=PG_HOST,
        port=PG_PORT,
    )
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute(f"TRUNCATE TABLE {PG_TABLE} RESTART IDENTITY")
    cursor.close()
    conn.close()
    print(f"🗑️  PostgreSQL: tabela '{PG_TABLE}' truncada")


def truncate_influx():
    if not INFLUXDB_BUCKET or not INFLUXDB_TOKEN:
        print("⚠️ InfluxDB: bucket/token não configurados, pulando truncate")
        return

    client = InfluxDBClient(
        url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG
    )
    buckets_api = client.buckets_api()
    org = client.organizations_api().find_organizations(org=INFLUXDB_ORG)
    if not org:
        client.close()
        raise RuntimeError(f"Organização InfluxDB '{INFLUXDB_ORG}' não encontrada")

    org_id = org[0].id
    existing = buckets_api.find_bucket_by_name(INFLUXDB_BUCKET)
    if existing:
        buckets_api.delete_bucket(existing)
        print(f"🗑️  InfluxDB: bucket '{INFLUXDB_BUCKET}' removido")

    buckets_api.create_bucket(bucket_name=INFLUXDB_BUCKET, org_id=org_id)
    client.close()
    print(f"✅ InfluxDB: bucket '{INFLUXDB_BUCKET}' recriado (vazio)")


def main():
    parser = argparse.ArgumentParser(description="Cria ou limpa recursos do experimento.")
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Esvazia a tabela PG e recria o bucket Influx do perfil ativo",
    )
    args = parser.parse_args()

    print(f"🔧 Setup experimento [{EXPERIMENT_LABEL}]")
    print(f"   PG_TABLE={PG_TABLE}")
    print(f"   INFLUXDB_BUCKET={INFLUXDB_BUCKET}")

    try:
        setup_postgres()
        if args.truncate:
            truncate_postgres()
    except Exception as exc:
        print(f"❌ PostgreSQL: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.truncate:
            truncate_influx()
        else:
            setup_influx()
    except Exception as exc:
        print(f"❌ InfluxDB: {exc}", file=sys.stderr)
        print("   (confira se o container influxdb está no ar em localhost:8086)", file=sys.stderr)
        sys.exit(1)

    if args.truncate:
        print("✅ Truncate concluído (PG vazio + bucket Influx recriado)")
    else:
        print("✅ Setup concluído")


if __name__ == "__main__":
    main()
