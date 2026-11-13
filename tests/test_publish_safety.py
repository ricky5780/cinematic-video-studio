import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cvs_publish", ROOT / "publish.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class PublicationSafetyTests(unittest.TestCase):
    """Offline guard tests only. These do not create a remote repository."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.files = {}
        for name in ("SKILL.md", "LICENSE", "README.md", "scripts/video_audit.py"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("test", encoding="utf-8")
            self.files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.write_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        (self.root / "RELEASE_MANIFEST.json").write_text(json.dumps({"files": self.files}), encoding="utf-8")

    def test_valid_manifest(self):
        self.assertEqual(publisher.verify_release(self.root), self.files)

    def test_modified_payload_refused(self):
        (self.root / "SKILL.md").write_text("tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            publisher.verify_release(self.root)

    def test_path_traversal_refused(self):
        self.files["../private.txt"] = "x"
        self.write_manifest()
        with self.assertRaises(ValueError):
            publisher.verify_release(self.root)

    def test_missing_cli_stops_before_network(self):
        with patch.object(publisher.shutil, "which", return_value=None), patch.object(publisher, "run") as run:
            with self.assertRaises(RuntimeError):
                publisher.publish(self.root, "test-owner", "test-repo")
            run.assert_not_called()

    def test_owner_mismatch_stops_before_creation(self):
        import subprocess
        response = subprocess.CompletedProcess([], 0, json.dumps({"login": "different-owner", "id": 1}), "")
        with patch.object(publisher.shutil, "which", side_effect=lambda n: n), patch.object(publisher, "run", return_value=response) as run:
            with self.assertRaises(ValueError):
                publisher.publish(self.root, "requested-owner", "test-repo")
            self.assertEqual(run.call_count, 1)

    def test_existing_repo_never_overwritten(self):
        import subprocess
        responses = [subprocess.CompletedProcess([], 0, json.dumps({"login": "test-owner", "id": 1}), ""),
                     subprocess.CompletedProcess([], 0, "{}", "")]
        with patch.object(publisher.shutil, "which", side_effect=lambda n: n), patch.object(publisher, "run", side_effect=responses) as run:
            with self.assertRaises(ValueError):
                publisher.publish(self.root, "test-owner", "test-repo")
            self.assertEqual(run.call_count, 2)

    def test_connection_failure_is_not_missing_repo(self):
        import subprocess
        responses = [subprocess.CompletedProcess([], 0, json.dumps({"login": "test-owner", "id": 1}), ""),
                     subprocess.CompletedProcess([], 1, "", "network error")]
        with patch.object(publisher.shutil, "which", side_effect=lambda n: n), patch.object(publisher, "run", side_effect=responses) as run:
            with self.assertRaises(RuntimeError):
                publisher.publish(self.root, "test-owner", "test-repo")
            self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
