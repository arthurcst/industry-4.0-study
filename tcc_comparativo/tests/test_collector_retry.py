import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class CollectorRetryTest(unittest.TestCase):
    def test_transient_docker_failure_does_not_end_collection(self):
        bash = r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else "bash"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "bin").mkdir()
            shutil.copy(Path(__file__).resolve().parents[1] / "scripts/collect_docker_stats.sh", root / "scripts")
            fake = root / "bin/docker"
            fake.write_text("""#!/usr/bin/env bash
if [[ "$1" == compose ]]; then echo fake-id; exit 0; fi
if [[ "$1" == stats ]]; then
  if [[ ! -f docker_retried ]]; then touch docker_retried; exit 126; fi
  echo 'fake-id,stream_consumer,1%,1MiB / 10GiB,1%,0B / 0B,0B / 0B,1'
  exit 0
fi
exit 1
""", encoding="utf-8")
            fake.chmod(0o755)
            env = os.environ.copy()
            env.update({"PATH": str(root / "bin") + os.pathsep + env["PATH"],
                        "EXPERIMENT_LABEL": "test", "METRICS_HOST": "./metrics",
                        "COLLECT_DURATION_SECONDS": "5", "COLLECT_INTERVAL": "0.2"})
            result = subprocess.run([bash, str(root / "scripts/collect_docker_stats.sh")], cwd=root,
                                    env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("tentativa 1/3", result.stderr)
            self.assertIn("stream_consumer", (root / "metrics/docker_stats_test.csv").read_text())


if __name__ == "__main__":
    unittest.main()
