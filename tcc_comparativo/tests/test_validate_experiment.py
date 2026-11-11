import json
import tempfile
import unittest
from pathlib import Path
from scripts.validate_experiment import validate


class ValidateExperimentTest(unittest.TestCase):
    def test_matching_and_missing_confirmations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "generator.log").write_text("2 mensagens em 60s", encoding="utf-8")
            for approach in ("batch", "stream"):
                (root / f"latency_{approach}.csv").write_text("a,1,2,100,200,boot:0:0\nb,2,3,200,300,boot:0:0\n", encoding="utf-8")
            storage = {"total_records": 2, "latency_count": 2, "latency_negative_count": 0}
            summary = {
                "postgres": storage, "influxdb": storage, "batch_files": {"total_rows_in_csvs": 2, "csv_files": 1},
                "batch_throughput": {"total_records_processed": 2, "batches_processed": 1},
                "stream_consumer": {"dropped": 0, "queue_pending": 0, "parse_errors": 0,
                                    "write_errors": 0, "mqtt_total_received": 2, "points_written": 2, "contador": 2},
            }
            (root / "summary_teste.json").write_text(json.dumps(summary), encoding="utf-8")
            validate(root, "teste")
            summary["batch_throughput"]["total_records_processed"] = 4
            (root / "summary_teste.json").write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate(root, "teste")
            summary["batch_throughput"]["total_records_processed"] = 2
            (root / "summary_teste.json").write_text(json.dumps(summary), encoding="utf-8")
            (root / "latency_stream.csv").write_text("a,1,2,100,200,other:0:0\nb,2,3,200,300,other:0:0\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate(root, "teste")
            (root / "latency_stream.csv").write_text("a,1,2,100,200,boot:0:0\na,2,3,200,300,boot:0:0\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate(root, "teste")


if __name__ == "__main__":
    unittest.main()
