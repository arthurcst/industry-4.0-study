"""Validação do provisionamento e das consultas pela API do Grafana de teste."""

import base64
import json
import os
import unittest
from pathlib import Path
from urllib.request import Request, urlopen


URL = os.getenv("GRAFANA_TEST_URL")
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(URL, "defina GRAFANA_TEST_URL para testar o Grafana")
class GrafanaIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dashboard = json.loads((ROOT / "grafana/dashboards/tcc-pipelines.json").read_text(encoding="utf-8"))
        cls.panels = {p["id"]: p for p in dashboard["panels"] if "targets" in p}
        cls.auth = "Basic " + base64.b64encode(b"admin:admin").decode()

    def api(self, path, body=None):
        data = json.dumps(body).encode() if body else None
        request = Request(URL + path, data=data, headers={"Authorization": self.auth, "Content-Type": "application/json"})
        with urlopen(request, timeout=15) as response:
            return json.load(response)

    def query(self, panel):
        sql = (self.panels[panel]["targets"][0]["rawSql"]
               .replace("${bucket}", "iot_stream_reduzida")
               .replace("${pg_table}", "sensor_data_reduzida"))
        result = self.api("/api/ds/query", {
            "queries": [{"refId": "A", "datasource": {"type": "postgres", "uid": "confirmed-metrics"},
                         "rawSql": sql, "format": "time_series", "intervalMs": 1000, "maxDataPoints": 1000}],
            "from": "1699999999000", "to": "1700000004000",
        })
        query_result = result["results"]["A"]
        self.assertNotIn("error", query_result)
        return query_result["frames"][0]["data"]["values"][1]

    def test_dashboard_is_provisioned(self):
        self.assertEqual(self.api("/api/dashboards/uid/tcc-stream-batch")["dashboard"]["uid"], "tcc-stream-batch")

    def test_queries_through_grafana(self):
        for panel, expected in ((1, [2, 0, 1]), (2, [150, 100]), (4, [2, 0, 1]), (5, [600, 2100])):
            with self.subTest(panel=panel):
                self.assertEqual(self.query(panel), expected)
        self.assertAlmostEqual(self.query(6)[0], 0.05)


if __name__ == "__main__":
    unittest.main()
