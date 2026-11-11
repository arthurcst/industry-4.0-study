import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from scripts.audit_resource_coverage import audit


class ResourceCoverageTest(unittest.TestCase):
    def test_complete_coverage_and_missing_intervals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start = datetime(2026, 11, 4, tzinfo=timezone.utc)
            end = start + timedelta(seconds=90)
            (root / "generator_window.txt").write_text(f"{start.isoformat()} {end.isoformat()}")
            target = root / "docker_stats_test.csv"

            def write(seconds):
                with target.open("w", newline="") as output:
                    writer = csv.writer(output)
                    writer.writerow(["timestamp", "name", "cpu_perc", "mem_usage"])
                    for second in seconds:
                        for name in ("batch_consumer", "stream_consumer", "sensor_generator"):
                            writer.writerow([(start + timedelta(seconds=second)).isoformat(), name, "1.5%", "5MiB / 10GiB"])

            write([0, 30, 60, 90])
            audit(root, "test")
            write([0, 30, 90])
            with self.assertRaises(ValueError):
                audit(root, "test")
            write([0, 30])
            with self.assertRaises(ValueError):
                audit(root, "test")


if __name__ == "__main__":
    unittest.main()
