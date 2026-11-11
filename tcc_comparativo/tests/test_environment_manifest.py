import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.environment_manifest import check


class EnvironmentManifestTest(unittest.TestCase):
    def test_rejects_image_or_source_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text(json.dumps({'images': {'img': 'sha256:a'}, 'sources': {'file': 'hash'}, 'host_runtime': {'python': 'x'}}))
            with patch('scripts.environment_manifest.images', return_value={'img': 'sha256:a'}), \
                 patch('scripts.environment_manifest.sources', return_value={'file': 'hash'}), \
                 patch('scripts.environment_manifest.host_runtime', return_value={'python': 'x'}):
                check(path)
            with patch('scripts.environment_manifest.images', return_value={'img': 'sha256:b'}):
                with self.assertRaises(ValueError):
                    check(path)
            with patch('scripts.environment_manifest.images', return_value={'img': 'sha256:a'}), \
                 patch('scripts.environment_manifest.sources', return_value={'file': 'changed'}):
                with self.assertRaises(ValueError):
                    check(path)


if __name__ == '__main__':
    unittest.main()
