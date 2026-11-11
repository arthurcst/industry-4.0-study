"""Verifica dados confirmados depois da interrupção forçada dos bancos isolados."""
import sys
import psycopg2
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

mode = sys.argv[1]
conn = psycopg2.connect(host="postgres", dbname="iot_batch", user="grafana", password="grafana")
influx = InfluxDBClient(url="http://influxdb:8086", token="my-super-token", org="my-org")
if mode == "write":
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS confirmed_test (id integer PRIMARY KEY)")
        cur.execute("INSERT INTO confirmed_test VALUES (42) ON CONFLICT DO NOTHING")
    conn.commit()
    influx.write_api(write_options=SYNCHRONOUS).write(bucket="crash_test", record=Point("confirmed_test").field("value", 42))
elif mode == "read":
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM confirmed_test WHERE id = 42")
        assert cur.fetchone()[0] == 1
    query = 'from(bucket: "crash_test") |> range(start: -1h) |> filter(fn: (r) => r._measurement == "confirmed_test" and r._field == "value")'
    records = [r.get_value() for table in influx.query_api().query(query) for r in table.records]
    assert records == [42], records
else:
    raise ValueError(mode)
conn.close()
influx.close()
print(f"{mode}: PostgreSQL e InfluxDB verificados")
