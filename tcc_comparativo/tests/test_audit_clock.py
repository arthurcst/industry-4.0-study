import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.audit_clock import audit, stream_clock_evidence


class ClockAuditTest(unittest.TestCase):
    def test_backstep_and_host_adjustment_stop_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "generator_window.txt").write_text("2026-11-03T12:00:00Z 2026-11-03T13:00:00Z", encoding="utf-8")
            stream = root / "latency_stream.csv"
            stream.write_text("a,1,5\nb,2,4\n", encoding="utf-8")
            self.assertEqual(stream_clock_evidence(stream), ([{"row": 2, "delta_ms": -1}], 0, 0))
            with patch("scripts.audit_clock.windows_clock_changes", return_value=[]):
                with self.assertRaises(ValueError):
                    audit(root)
            stream.write_text("a,1,5\nb,2,6\n", encoding="utf-8")
            with patch("scripts.audit_clock.windows_clock_changes", return_value=[{"delta_ms": 10}]):
                with self.assertRaises(ValueError):
                    audit(root)
            with patch("scripts.audit_clock.windows_clock_changes", return_value=[]):
                audit(root)
                stream.write_text("a,1,5\nb,7,6\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    audit(root)
            evidence = json.loads((root / "clock_audit_v2.json").read_text())
            self.assertEqual(evidence["stream_backsteps"], [])
            self.assertEqual(evidence["negative_wall_interval_count"], 1)
            stream.write_text("a,7,6,100,200,boot:0:0\n", encoding="utf-8")
            with patch("scripts.audit_clock.windows_clock_changes", return_value=[]):
                audit(root)


if __name__ == "__main__":
    unittest.main()
