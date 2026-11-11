import tempfile
import unittest
from pathlib import Path
from scripts.audit_workload import audit


class WorkloadAuditTest(unittest.TestCase):
    def test_load_within_and_outside_planned_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'parameters.env').write_text('EXECUTION_TIME_SECONDS=60\n', encoding='utf-8')
            log = root / 'generator.log'
            log.write_text('3732 mensagens em 62s', encoding='utf-8')
            audit(root, 'reduzida')
            log.write_text('2200 mensagens em 62s', encoding='utf-8')
            with self.assertRaises(ValueError):
                audit(root, 'reduzida')
            log.write_text('5000 mensagens em 62s', encoding='utf-8')
            with self.assertRaises(ValueError):
                audit(root, 'reduzida')


if __name__ == '__main__':
    unittest.main()
