import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from scripts import project_state as ps

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cvs_install", ROOT / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        ps.init(self.root, "produce")
        (self.root / "source.js").write_text("first", encoding="utf-8")
        (self.root / "render.bin").write_bytes(b"render")

    def tearDown(self):
        self.temp.cleanup()

    def register(self):
        return ps.record(self.root, "shot01", ["source.js"], "render.bin", "42")

    def test_init_refuses_overwrite(self):
        with self.assertRaises(ValueError):
            ps.init(self.root, "explore")
        self.assertEqual(json.loads((self.root / ps.STATE).read_text())["mode"], "produce")

    def test_fresh_cache_is_not_approval(self):
        self.register()
        result = ps.verify(self.root)["shot01"]
        self.assertEqual(result["cache_status"], "valid_for_declared_inputs")
        self.assertEqual(result["creative_approval"], "not_checked")

    def test_source_change_invalidates(self):
        self.register()
        (self.root / "source.js").write_text("changed", encoding="utf-8")
        self.assertEqual(ps.verify(self.root)["shot01"]["cache_status"], "stale")

    def test_output_change_invalidates(self):
        self.register()
        (self.root / "render.bin").write_bytes(b"changed")
        self.assertEqual(ps.verify(self.root)["shot01"]["changed"], ["render.bin"])

    def test_missing_file_invalidates(self):
        self.register()
        (self.root / "source.js").unlink()
        self.assertEqual(ps.verify(self.root)["shot01"]["cache_status"], "stale")

    def test_no_implicit_dependencies(self):
        with self.assertRaises(ValueError):
            ps.record(self.root, "shot", [], "render.bin", "42")

    def test_path_escape_refused(self):
        outside = self.root.parent / "private.txt"
        outside.write_text("private", encoding="utf-8")
        with self.assertRaises(ValueError):
            ps.record(self.root, "shot", ["../private.txt"], "render.bin", "42")

    def test_external_symlink_refused(self):
        outside = self.root.parent / "private.txt"
        outside.write_text("private", encoding="utf-8")
        try:
            (self.root / "linked.txt").symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        with self.assertRaises(ValueError):
            ps.local_file(self.root, "linked.txt")

    def test_state_lock(self):
        with ps.state_lock(self.root):
            with self.assertRaises(ValueError):
                self.register()
        self.assertFalse((self.root / ".cvs-state.lock").exists())

    def test_edited_seed_invalidates_manifest(self):
        self.register()
        state = json.loads((self.root / ps.STATE).read_text())
        state["artifacts"]["shot01"]["seed"] = "43"
        ps.save(self.root, state)
        self.assertEqual(ps.verify(self.root)["shot01"]["cache_status"], "stale")

    def test_seed_in_fingerprint(self):
        first = self.register()
        second = ps.record(self.root, "shot01", ["source.js"], "render.bin", "43")
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dest = Path(self.temp.name) / ".agents/skills/cinematic-video-studio"

    def tearDown(self):
        self.temp.cleanup()

    def test_install(self):
        self.assertIsNone(installer.install(ROOT, self.dest))
        self.assertTrue((self.dest / "SKILL.md").is_file())
        self.assertFalse((self.dest / "tests").exists())

    def test_existing_protected(self):
        self.dest.mkdir(parents=True)
        (self.dest / "SKILL.md").write_text("old")
        with self.assertRaises(ValueError):
            installer.install(ROOT, self.dest)
        self.assertEqual((self.dest / "SKILL.md").read_text(), "old")

    def test_backup_outside_discovery(self):
        self.dest.mkdir(parents=True)
        (self.dest / "SKILL.md").write_text("old")
        backup = installer.install(ROOT, self.dest, replace=True)
        self.assertEqual((backup / "SKILL.md").read_text(), "old")
        self.assertFalse(backup.is_relative_to(self.dest.parent))
        self.assertEqual((self.dest / "VERSION").read_text().strip(), "1.1.0")

    def test_symlink_destination_refused(self):
        target = Path(self.temp.name) / "target"
        target.mkdir()
        self.dest.parent.mkdir(parents=True)
        try:
            self.dest.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        with self.assertRaises(ValueError):
            installer.install(ROOT, self.dest, replace=True)

    def test_overlapping_source_refused(self):
        with self.assertRaises(ValueError):
            installer.install(ROOT, ROOT / "install-inside-source")


class InstructionContractTests(unittest.TestCase):
    """Static text/structure checks, NOT model behavior evaluations."""
    def test_routing_contract(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for mode in ("explore", "prototype", "produce", "refine", "audit"):
            self.assertIn(f"`{mode}`", text)
        self.assertIn("不重渲染", text)
        self.assertIn("跳过四选一", text)
        self.assertIn("not_checked", text)

    def test_metadata_consistency(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: cinematic-video-studio\n"))
        interface = (ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
        self.assertIn("$cinematic-video-studio", interface)
        self.assertNotIn("先做四套", interface)

    def test_reference_files_exist(self):
        for name in ("production.md", "quality.md"):
            self.assertTrue((ROOT / "references" / name).is_file())
        for name in ("delivery-spec.json", "STYLE_LOCK.md"):
            self.assertTrue((ROOT / "templates" / name).is_file())

    def test_example_spec_valid(self):
        from scripts.video_audit import validate_spec
        validate_spec(json.loads((ROOT / "templates/delivery-spec.json").read_text()))


if __name__ == "__main__":
    unittest.main()
