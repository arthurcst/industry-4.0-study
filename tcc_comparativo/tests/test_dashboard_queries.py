"""Validação das consultas do dashboard contra o banco auxiliar de teste."""

import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTAINER = os.getenv("METRICS_TEST_CONTAINER")


@unittest.skipUnless(CONTAINER, "defina METRICS_TEST_CONTAINER para executar os testes SQL")
class DashboardQueriesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dashboard = json.loads((ROOT / "grafana/dashboards/tcc-pipelines.json").read_text(encoding="utf-8"))
        cls.panels = {panel["id"]: panel for panel in dashboard["panels"] if "targets" in panel}

    def query(self, panel_id, scenario="reduzida"):
        sql = self.panels[panel_id]["targets"][0]["rawSql"]
        sql = (sql.replace("${bucket}", "iot_stream_" + scenario)
               .replace("${pg_table}", "sensor_data_" + scenario)
               .replace("$__timeFrom()", "to_timestamp(1699999999)")
               .replace("$__timeTo()", "to_timestamp(1700000004)"))
        result = subprocess.run(
            ["docker", "exec", CONTAINER, "psql", "-X", "-A", "-t", "-F", "|", "-v", "ON_ERROR_STOP=1", "-U", "grafana", "-d", "experiment_metrics", "-c", sql],
            check=True, capture_output=True, text=True,
        )
        return [line.split("|") for line in result.stdout.splitlines() if line.strip()]

    def test_stream_and_batch_rates_include_empty_seconds(self):
        for panel in (1, 4):
            with self.subTest(panel=panel):
                self.assertEqual([float(row[1]) for row in self.query(panel)], [2, 0, 1])

    def test_latency_uses_confirmation_not_prewrite_time(self):
        self.assertEqual([float(row[1]) for row in self.query(2)], [150, 100])
        self.assertEqual([float(row[1]) for row in self.query(5)], [600, 2100])

    def test_batch_minute_rate(self):
        self.assertAlmostEqual(float(self.query(6)[0][1]), 3 / 60)

    def test_other_scenarios_do_not_show_active_data(self):
        for panel in (1, 2, 3, 4, 5, 6):
            with self.subTest(panel=panel):
                self.assertEqual(self.query(panel, "completa"), [])


if __name__ == "__main__":
    unittest.main()
