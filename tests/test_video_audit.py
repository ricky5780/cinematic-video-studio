import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scripts import video_audit as qa

SPEC = {"width": 96, "height": 64, "fps": 10, "duration_s": 2, "audio": "forbidden"}


class UnitTests(unittest.TestCase):
    def test_rates(self):
        self.assertAlmostEqual(qa.rate("30000/1001"), 29.97003, places=4)
        for bad in ("0/0", "0", "nan", "inf", None):
            self.assertIsNone(qa.rate(bad))

    def test_numeric_nonfinite(self):
        for bad in ("nan", "inf", "-inf", None):
            self.assertIsNone(qa.number(bad))

    def test_spec_validation(self):
        self.assertEqual(qa.validate_spec(SPEC), SPEC)
        for change in ({"width": True}, {"fps": 0}, {"duration_s": float("nan")},
                       {"audio": "yes"}, {"require_cfr": "yes"}, {"unknown": 1},
                       {"key_times_s": [-1]}, {"loudness_min_lufs": -10, "loudness_max_lufs": -20}):
            with self.subTest(change=change), self.assertRaises(qa.AuditError):
                qa.validate_spec({**SPEC, **change})

    def test_missing_spec_field(self):
        with self.assertRaises(qa.AuditError):
            qa.validate_spec({"width": 100})

    def test_eof_freeze(self):
        events = qa.parse_events("lavfi.freezedetect.freeze_start=4.2", 6)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["open_at_end"])
        self.assertEqual(events[0]["end_s"], 6)

    def test_short_black_filtered(self):
        self.assertEqual(qa.parse_events("lavfi.black_start=0\nlavfi.black_end=0.1", 2), [])

    def test_allowed_requires_full_containment(self):
        event = {"kind": "black", "start_s": 1, "end_s": 3}
        allowed = [{"kind": "black", "start_s": 1, "end_s": 2, "reason": "fade"}]
        qa.review_events([event], allowed)
        self.assertEqual(event["status"], "review_required")
        allowed[0]["end_s"] = 3
        qa.review_events([event], allowed)
        self.assertEqual(event["status"], "allowed")

    def test_representative_indices_use_real_frames(self):
        self.assertEqual(qa.selected_indices([0, .1]), [0, 1])
        values = qa.selected_indices([i * .1 for i in range(20)])
        self.assertEqual(len(values), 9)
        self.assertEqual(values[-1], 19)

    def test_timeline_ignores_container_duration(self):
        frames = [{"best_effort_timestamp_time": str(4 + n / 10), "pkt_duration_time": ".1"} for n in range(20)]
        result = qa.timeline_from_frames(frames, 10)
        self.assertAlmostEqual(result["duration_s"], 2)
        self.assertAlmostEqual(result["start_s"], 4)

    def test_bad_timestamps(self):
        with self.assertRaises(qa.AuditError):
            qa.timeline_from_frames([{"best_effort_timestamp_time": "0"}] * 2, 10)

    def test_loudness_parser(self):
        result = qa.parse_loudness('{"input_i":"-inf","input_tp":"-inf","input_lra":"0"}')
        self.assertTrue(result["nonfinite_measurement"])
        self.assertIsNone(result["integrated_lufs"])

    def test_command_timeout(self):
        import sys
        with tempfile.TemporaryDirectory() as name:
            runner = qa.Runner(Path(name), .05)
            with self.assertRaises(qa.AuditError):
                runner.run("sleep", [sys.executable, "-c", "import time; time.sleep(2)"])
            self.assertIsNone(runner.records[0]["returncode"])

    def test_failed_command(self):
        import sys
        with tempfile.TemporaryDirectory() as name:
            runner = qa.Runner(Path(name), 5)
            with self.assertRaises(qa.AuditError):
                runner.run("fail", [sys.executable, "-c", "raise SystemExit(7)"])
            self.assertEqual(runner.records[0]["returncode"], 7)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg integration tools unavailable")
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.ff = shutil.which("ffmpeg")
        cls.make("normal", "testsrc2=size=96x64:rate=10:duration=2")
        cls.make("black", "color=black:size=96x64:rate=10:duration=2")
        cls.make("late_black", "testsrc2=size=96x64:rate=5:duration=126",
                 ["-vf", "drawbox=color=black:t=fill:enable='between(t,123,125)'"])
        cls.make("tail_freeze", "testsrc2=size=96x64:rate=10:duration=1", ["-vf", "tpad=stop_mode=clone:stop_duration=2"])
        cls.make("with_audio", "testsrc2=size=96x64:rate=10:duration=2", audio="sine=frequency=440:duration=2")
        cls.make("long_audio", "testsrc2=size=96x64:rate=10:duration=2", audio="sine=frequency=440:duration=4")
        cls.make("silent_audio", "testsrc2=size=96x64:rate=10:duration=2", audio="anullsrc=r=48000:cl=stereo:d=2")
        cls.make("vfr", "testsrc2=size=96x64:rate=10:duration=2",
                 ["-vf", "select='not(eq(n,5))'", "-vsync", "vfr"])

    @classmethod
    def make(cls, name, video, extra=None, audio=None):
        args = [cls.ff, "-hide_banner", "-loglevel", "error", "-y", "-filter_threads", "1", "-f", "lavfi", "-i", video]
        if audio:
            args += ["-f", "lavfi", "-i", audio, "-c:a", "aac"]
        args += (extra or []) + ["-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p", "-threads", "1", str(cls.root / (name + ".mp4"))]
        subprocess.run(args, check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_audit(self, name="normal", spec=SPEC, **kwargs):
        report, root = qa.audit(self.root / (name + ".mp4"), self.root / "qa", spec, **kwargs)
        self.assertTrue((root / "report.json").is_file())
        return report, root

    def test_normal_pass_and_reviews_unchecked(self):
        r, _ = self.run_audit()
        self.assertEqual(r["exit_code"], 0, r["findings"])
        self.assertEqual(r["manual_reviews"]["visual"], "not_checked")
        self.assertEqual(len(r["frames"]), 9)
        self.assertEqual(r["frames"][-1]["frame_index"], 19)

    def test_old_output_never_reused(self):
        a, first = self.run_audit()
        (first / "frames/frame_001.png").write_bytes(b"old-corrupt-image")
        b, second = self.run_audit()
        self.assertNotEqual(first, second)
        self.assertEqual(b["exit_code"], 0, b["findings"])
        self.assertNotEqual(qa.sha256(first / "frames/frame_001.png"), qa.sha256(second / "frames/frame_001.png"))

    def test_black_not_pass(self):
        r, _ = self.run_audit("black")
        self.assertEqual(r["execution_status"], "success")
        self.assertEqual(r["exit_code"], 1)
        self.assertIn("black", [e["kind"] for e in r["events"]])

    def test_planned_black_and_freeze(self):
        spec = {**SPEC, "allowed_events": [{"kind": k, "start_s": 0, "end_s": 2, "reason": "deliberate test card"} for k in ("black", "freeze")]}
        r, _ = self.run_audit("black", spec)
        self.assertEqual(r["exit_code"], 0, r["findings"])

    def test_late_black_full_scan(self):
        spec = {**SPEC, "fps": 5, "duration_s": 126}
        r, _ = self.run_audit("late_black", spec)
        self.assertTrue(r["coverage"]["video_scan_complete"])
        self.assertTrue(any(e["kind"] == "black" and e["start_s"] >= 120 for e in r["events"]), r["events"])

    def test_late_black_partial_never_pass(self):
        spec = {**SPEC, "fps": 5, "duration_s": 126}
        r, _ = self.run_audit("late_black", spec, scan_seconds=120)
        self.assertEqual(r["exit_code"], 1)
        self.assertFalse(r["coverage"]["video_scan_complete"])
        self.assertFalse(any(e["kind"] == "black" for e in r["events"]))

    def test_eof_freeze_real_media(self):
        r, _ = self.run_audit("tail_freeze", {**SPEC, "duration_s": 3})
        self.assertTrue(any(e["kind"] == "freeze" and e["open_at_end"] for e in r["events"]), r["events"])

    def test_audio_analysis(self):
        r, _ = self.run_audit("with_audio", {**SPEC, "audio": "required"})
        self.assertEqual(r["exit_code"], 0, r["findings"])
        self.assertIsNotNone(r["audio_measurements"]["integrated_lufs"])

    def test_audio_outlasts_video(self):
        r, _ = self.run_audit("long_audio", {**SPEC, "audio": "required"})
        self.assertEqual(r["execution_status"], "success", r["findings"])
        self.assertEqual(r["technical_verdict"], "fail")
        self.assertEqual(len(r["frames"]), 9)
        self.assertAlmostEqual(r["timeline"]["duration_s"], 2)

    def test_silent_audio(self):
        r, _ = self.run_audit("silent_audio", {**SPEC, "audio": "required"})
        self.assertEqual(r["exit_code"], 1, r["findings"])
        self.assertTrue(any(e["kind"] == "silence" for e in r["events"]))

    def test_vfr_rejects_cfr_spec(self):
        r, _ = self.run_audit("vfr")
        self.assertEqual(r["technical_verdict"], "fail", r["findings"])

    def test_missing_spec(self):
        r, _ = self.run_audit(spec=None)
        self.assertEqual(r["exit_code"], 1)
        self.assertEqual(r["checks"]["delivery_specification"], "not_checked")

    def test_bad_dimensions_and_required_audio(self):
        r, _ = self.run_audit(spec={**SPEC, "width": 1080, "audio": "required"})
        self.assertEqual(r["technical_verdict"], "fail")

    def test_missing_tools(self):
        with patch.object(qa.shutil, "which", return_value=None):
            r, _ = self.run_audit()
        self.assertEqual(r["exit_code"], 2)
        self.assertEqual(r["execution_status"], "failed")

    def test_invalid_media(self):
        (self.root / "invalid.mp4").write_bytes(b"not video")
        r, _ = self.run_audit("invalid")
        self.assertEqual(r["exit_code"], 2)

    def test_input_change_invalidates_run(self):
        original = qa.sha256
        calls = 0
        def changed(path):
            nonlocal calls
            if Path(path).name == "normal.mp4":
                calls += 1
                if calls > 1:
                    return "changed"
            return original(path)
        with patch.object(qa, "sha256", side_effect=changed):
            r, _ = self.run_audit()
        self.assertEqual(r["exit_code"], 2)
        self.assertEqual(r["technical_verdict"], "not_verified")

    def test_no_input_mutation(self):
        before = qa.sha256(self.root / "normal.mp4")
        self.run_audit()
        self.assertEqual(before, qa.sha256(self.root / "normal.mp4"))


if __name__ == "__main__":
    unittest.main()
