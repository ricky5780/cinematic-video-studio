#!/usr/bin/env python3
"""Local, evidence-producing video audit. Python 3.10+, FFmpeg/FFprobe 5+.

Exit 0: configured machine checks passed in full; 1: warning/spec failure;
2: execution/input failure. None of these certify visual or listening review.
Every invocation writes a new run directory; input media is never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import statistics
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

VERSION = "1.1.0"
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
SPEC_KEYS = {
    "width", "height", "fps", "duration_s", "audio", "duration_tolerance_s",
    "fps_tolerance", "require_cfr", "max_av_gap_s", "max_true_peak_dbfs",
    "loudness_min_lufs", "loudness_max_lufs", "allowed_events", "key_times_s",
}


class AuditError(RuntimeError):
    """An operation could not produce trustworthy evidence."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def rate(value: Any) -> float | None:
    try:
        result = float(Fraction(str(value)))
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def validate_spec(spec: Any) -> dict:
    if not isinstance(spec, dict):
        raise AuditError("Specification must be a JSON object")
    unknown = set(spec) - SPEC_KEYS
    if unknown:
        raise AuditError(f"Unknown specification fields: {sorted(unknown)}")
    required = {"width", "height", "fps", "duration_s", "audio"}
    if required - set(spec):
        raise AuditError(f"Missing specification fields: {sorted(required - set(spec))}")
    for key in ("width", "height"):
        if type(spec[key]) is not int or spec[key] <= 0:
            raise AuditError(f"{key} must be a positive integer")
    for key in ("fps", "duration_s", "duration_tolerance_s", "fps_tolerance", "max_av_gap_s"):
        if key in spec:
            v = number(spec[key])
            if isinstance(spec[key], bool) or v is None or v < 0 or (key in ("fps", "duration_s") and v == 0):
                raise AuditError(f"Invalid {key}")
    if spec["audio"] not in ("required", "optional", "forbidden"):
        raise AuditError("audio must be required, optional or forbidden")
    if "require_cfr" in spec and type(spec["require_cfr"]) is not bool:
        raise AuditError("require_cfr must be boolean")
    for key in ("max_true_peak_dbfs", "loudness_min_lufs", "loudness_max_lufs"):
        if key in spec and (isinstance(spec[key], bool) or number(spec[key]) is None):
            raise AuditError(f"Invalid {key}")
    if spec.get("loudness_min_lufs", -1000) > spec.get("loudness_max_lufs", 1000):
        raise AuditError("Loudness minimum exceeds maximum")
    events = spec.get("allowed_events", [])
    if not isinstance(events, list):
        raise AuditError("allowed_events must be an array")
    for event in events:
        if not isinstance(event, dict) or set(event) != {"kind", "start_s", "end_s", "reason"}:
            raise AuditError("Each allowed event needs kind, start_s, end_s, reason")
        a, b = number(event["start_s"]), number(event["end_s"])
        if (event["kind"] not in ("black", "freeze", "silence") or a is None or b is None
                or a < 0 or b <= a or not isinstance(event["reason"], str) or not event["reason"].strip()):
            raise AuditError("Invalid allowed event")
    times = spec.get("key_times_s", [])
    if not isinstance(times, list) or len(times) > 18 or any(number(t) is None or float(t) < 0 for t in times):
        raise AuditError("key_times_s must contain at most 18 finite nonnegative times")
    return spec


class Runner:
    """Bounded subprocess execution; shell=False; diagnostic logs stay with run."""
    def __init__(self, root: Path, timeout: float):
        self.root, self.timeout = root, timeout
        self.records: list[dict] = []
        (root / "logs").mkdir()

    def run(self, name: str, args: list[str]) -> tuple[str, str]:
        prefix = f"{len(self.records):02d}_{name}"
        out = self.root / "logs" / f"{prefix}.stdout.txt"
        err = self.root / "logs" / f"{prefix}.stderr.txt"
        record: dict = {"name": name, "argv": args, "stdout": str(out.relative_to(self.root)),
                        "stderr": str(err.relative_to(self.root)), "timeout_s": self.timeout}
        self.records.append(record)
        try:
            with out.open("wb") as stdout, err.open("wb") as stderr:
                result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                        timeout=self.timeout, check=False, shell=False)
            record["returncode"] = result.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            record.update(returncode=None, error=str(exc))
            raise AuditError(f"{name}: {exc}; see {err.name}") from exc
        stdout = out.read_text(encoding="utf-8", errors="replace")
        stderr = err.read_text(encoding="utf-8", errors="replace")
        if result.returncode:
            raise AuditError(f"{name}: exit {result.returncode}; see {err.name}")
        return stdout, stderr


def timeline_from_frames(frames: list[dict], nominal_fps: float | None) -> dict:
    """Use decoded frame timestamps, never container duration to locate images."""
    if not frames:
        raise AuditError("No decoded video frames")
    pts = [number(f.get("best_effort_timestamp_time", f.get("pts_time"))) for f in frames]
    if any(x is None for x in pts):
        raise AuditError("Decoded video has missing timestamps")
    times = [float(x) for x in pts]
    deltas = [b - a for a, b in zip(times, times[1:])]
    if any(d <= 0 for d in deltas):
        raise AuditError("Video timestamps are duplicate or non-monotonic")
    typical = statistics.median(deltas) if deltas else (1 / nominal_fps if nominal_fps else None)
    last = number(frames[-1].get("duration_time")) or number(frames[-1].get("pkt_duration_time"))
    estimated = not last or last <= 0
    last = last if last and last > 0 else typical
    if not last or last <= 0:
        raise AuditError("Cannot determine final video-frame duration")
    relative = [t - times[0] for t in times]
    duration = relative[-1] + last
    return {"start_s": times[0], "duration_s": duration, "end_s": times[0] + duration,
            "frame_count": len(frames), "last_frame_s": relative[-1],
            "last_frame_duration_estimated": estimated, "median_frame_interval_s": typical,
            "observed_fps": 1 / typical if typical else None,
            "max_interval_deviation_s": max((abs(d - typical) for d in deltas), default=0),
            "timestamps": relative}


def selected_indices(times: list[float], key_times: list[float] | None = None) -> list[int]:
    count = min(9, len(times))
    indices = {round(i * (len(times) - 1) / max(1, count - 1)) for i in range(count)}
    for second in key_times or []:
        indices.add(min(range(len(times)), key=lambda i: abs(times[i] - second)))
    return sorted(indices)


def parse_events(text: str, duration: float, audio: bool = False) -> list[dict]:
    """Close open-ended events at audited coverage end, including an EOF freeze."""
    pending: dict[str, float] = {}
    events = []
    if audio:
        pattern = re.compile(rf"silence_(start|end):\s*({NUMBER})")
    else:
        pattern = re.compile(rf"lavfi\.(black|freezedetect\.freeze)_(start|end)=({NUMBER})")
    for match in pattern.finditer(text):
        if audio:
            kind, edge, raw = "silence", match.group(1), match.group(2)
        else:
            kind, edge, raw = match.group(1).replace("freezedetect.", ""), match.group(2), match.group(3)
        value = min(duration, max(0.0, float(raw)))
        if edge == "start":
            pending[kind] = value
        elif kind in pending:
            start = pending.pop(kind)
            if value > start:
                events.append({"kind": kind, "start_s": start, "end_s": value, "open_at_end": False})
    for kind, start in pending.items():
        if duration > start:
            events.append({"kind": kind, "start_s": start, "end_s": duration, "open_at_end": True})
    minimum = {"black": .2, "freeze": 1.0, "silence": .5}
    return sorted([e for e in events if e["end_s"] - e["start_s"] + 1e-6 >= minimum[e["kind"]]],
                  key=lambda e: (e["start_s"], e["kind"]))


def review_events(events: list[dict], allowed: list[dict]) -> None:
    for event in events:
        match = next((a for a in allowed if a["kind"] == event["kind"]
                      and float(a["start_s"]) - .05 <= event["start_s"]
                      and float(a["end_s"]) + .05 >= event["end_s"]), None)
        event["status"] = "allowed" if match else "review_required"
        event["reason"] = match["reason"] if match else None


def check_spec(meta: dict, video: dict, audio: dict | None, timeline: dict, spec: dict) -> list[str]:
    failures = []
    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)
    require(video.get("width") == spec["width"], f"width: expected {spec['width']}, got {video.get('width')}")
    require(video.get("height") == spec["height"], f"height: expected {spec['height']}, got {video.get('height')}")
    avg = rate(video.get("avg_frame_rate")) or timeline["observed_fps"]
    require(avg is not None and abs(avg - float(spec["fps"])) <= float(spec.get("fps_tolerance", .02)),
            f"average fps: expected {spec['fps']}, got {avg}")
    require(abs(timeline["duration_s"] - float(spec["duration_s"])) <= float(spec.get("duration_tolerance_s", .1)),
            f"decoded video duration: expected {spec['duration_s']}, got {timeline['duration_s']:.6f}")
    if spec.get("require_cfr", True):
        target = 1 / float(spec["fps"])
        intervals = [b - a for a, b in zip(timeline["timestamps"], timeline["timestamps"][1:])]
        require(bool(intervals) and all(abs(d - target) <= max(.002, target * .02) for d in intervals),
                "constant frame cadence is not verified against target fps")
    require(spec["audio"] != "required" or audio is not None, "required audio track is missing")
    require(spec["audio"] != "forbidden" or audio is None, "unexpected audio track")
    return failures


def parse_loudness(text: str) -> dict:
    matches = re.findall(r'\{\s*"input_i".*?\}', text, flags=re.S)
    if not matches:
        raise AuditError("Audio analysis produced no loudness measurements")
    raw = json.loads(matches[-1])
    return {"integrated_lufs": number(raw.get("input_i")), "true_peak_dbfs": number(raw.get("input_tp")),
            "loudness_range_lu": number(raw.get("input_lra")),
            "nonfinite_measurement": any(number(raw.get(k)) is None for k in ("input_i", "input_tp"))}


def write_report(root: Path, report: dict) -> None:
    (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# 视频技术检查 / Video technical audit", "",
             f"- Execution: **{report['execution_status']}**", f"- Machine verdict: **{report['technical_verdict']}**",
             f"- Exit code: `{report['exit_code']}`", f"- Input SHA-256: `{report.get('input_sha256', 'unavailable')}`",
             "- Visual / listening / facts & licenses: **NOT CHECKED**", "",
             "机器检查通过不代表成片验收。未审内容不可宣称通过。", "", "## Checks", ""]
    for key, value in report.get("checks", {}).items():
        lines.append(f"- {key}: **{value}**")
    lines += ["", "## Findings", ""]
    for item in report.get("findings", []):
        lines.append(f"- [{item['severity']}] {item['message']}")
    for event in report.get("events", []):
        lines.append(f"- {event['kind']} {event['start_s']:.3f}–{event['end_s']:.3f}s: {event['status']}"
                     + (f" ({event['reason']})" if event.get("reason") else ""))
    if report.get("contact_sheet"):
        lines += ["", "## Representative frames (not complete visual coverage)", "", "![Contact sheet](contact_sheet.png)"]
    lines += ["", "## Review still required", "", "- [ ] Watch risk shots, transitions and full pacing.",
              "- [ ] Read subtitles; check safe areas, artifacts and factual claims.",
              "- [ ] Listen to speech/music/effects and check synchronization.",
              "- [ ] Record reviewer, coverage, version, timecodes and remaining P0/P1/P2 issues.", ""]
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")


def audit(video_path: Path, output: Path, spec: dict | None = None, *,
          scan_seconds: float | None = None, timeout: float = 120) -> tuple[dict, Path]:
    output.mkdir(parents=True, exist_ok=True)
    root = output / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:8])
    root.mkdir(exist_ok=False)
    runner = Runner(root, timeout)
    report: dict = {"schema_version": 1, "tool_version": VERSION, "generated_utc": datetime.now(timezone.utc).isoformat(),
                    "input_name": video_path.name, "execution_status": "running", "technical_verdict": "not_checked",
                    "checks": {}, "findings": [], "events": [], "commands": runner.records,
                    "manual_reviews": {"visual": "not_checked", "listening": "not_checked", "facts_and_licenses": "not_checked"}}
    def finding(level: str, message: str) -> None:
        report["findings"].append({"severity": level, "message": message})
    try:
        if timeout <= 0 or not math.isfinite(timeout) or (scan_seconds is not None and (scan_seconds <= 0 or not math.isfinite(scan_seconds))):
            raise AuditError("Timeout and optional scan limit must be finite and positive")
        video_path = video_path.resolve(strict=True)
        if not video_path.is_file():
            raise AuditError("Input must be a local file")
        if spec is not None:
            validate_spec(spec)
        report["specification"] = spec
        report["input_sha256"] = sha256(video_path)
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise AuditError("ffmpeg and ffprobe must be installed and present in PATH")
        report["tools"] = {}
        for name, executable in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
            stdout, _ = runner.run(name + "_version", [executable, "-version"])
            report["tools"][name] = stdout.splitlines()[0]
        report["checks"]["toolchain"] = "pass"
        probe = [ffprobe, "-v", "error", "-threads", "1", "-protocol_whitelist", "file,pipe"]
        raw, errors = runner.run("metadata", probe + ["-show_format", "-show_streams", "-of", "json", str(video_path)])
        if errors.strip():
            raise AuditError("ffprobe emitted errors reading metadata")
        meta = json.loads(raw)
        videos = [s for s in meta.get("streams", []) if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
        audios = [s for s in meta.get("streams", []) if s.get("codec_type") == "audio"]
        if not videos:
            raise AuditError("No primary video stream")
        video, audio = videos[0], audios[0] if audios else None
        report["streams"] = {"video": video, "audio": audio, "video_count": len(videos), "audio_count": len(audios)}
        if len(videos) > 1 or len(audios) > 1:
            finding("warning", "Only the first non-cover video and first audio stream are audited; additional streams remain unchecked")
        raw, errors = runner.run("timeline", probe + ["-select_streams", "V:0", "-show_frames", "-show_entries",
            "frame=best_effort_timestamp_time,pts_time,duration_time,pkt_duration_time", "-of", "json", str(video_path)])
        if errors.strip():
            raise AuditError("ffprobe emitted decoding errors; timeline is not accepted")
        timeline = timeline_from_frames(json.loads(raw).get("frames", []), rate(video.get("avg_frame_rate")) or rate(video.get("r_frame_rate")))
        times = timeline["timestamps"]
        report["timeline"] = {k: v for k, v in timeline.items() if k != "timestamps"}
        report["checks"]["decoded_timeline"] = "pass"
        if timeline["last_frame_duration_estimated"]:
            finding("warning", "Final frame duration was estimated from cadence; exact end duration is unverified")
        rotation = number(video.get("tags", {}).get("rotate")) or next((number(s.get("rotation")) for s in video.get("side_data_list", []) if "rotation" in s), 0)
        if rotation and rotation % 360:
            finding("warning", "Rotation metadata is present; specification dimensions refer to coded pixels, not displayed orientation")
        if spec is None:
            report["checks"]["delivery_specification"] = "not_checked"
            finding("warning", "No delivery specification supplied; conformance cannot be certified")
        else:
            failures = check_spec(meta, video, audio, timeline, spec)
            for message in failures:
                finding("fail", message)
            report["checks"]["delivery_specification"] = "fail" if failures else "pass"
        full = scan_seconds is None or scan_seconds >= timeline["duration_s"]
        limit = timeline["duration_s"] if full else float(scan_seconds)
        report["coverage"] = {"timeline": "all decoded video frames", "video_scan_start_s": 0,
                              "video_scan_end_s": limit, "video_scan_complete": full,
                              "visual_review": "not_checked"}
        if not full:
            finding("warning", f"Pixel anomaly scan covers only 0–{limit:.3f}s; remainder is unscanned")
        base = [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-y", "-threads", "1", "-filter_threads", "1"]
        source = ["-xerror", "-err_detect", "explode", "-protocol_whitelist", "file,pipe", "-i", str(video_path)]
        duration_args = [] if full else ["-t", str(limit)]
        _, logs = runner.run("video_scan", base + source + ["-map", f"0:{video['index']}", "-vf",
            "setpts=PTS-STARTPTS,blackdetect=d=0.20:pix_th=0.08,freezedetect=n=-50dB:d=1.0,metadata=mode=print",
            *duration_args, "-an", "-sn", "-dn", "-f", "null", "-"])
        report["events"] += parse_events(logs, limit)
        report["checks"]["video_scan"] = "pass" if full else "partial"
        indices = selected_indices(times, [float(t) for t in (spec or {}).get("key_times_s", [])])
        frames_dir = root / "frames"
        frames_dir.mkdir()
        select = "+".join(f"eq(n\\,{i})" for i in indices)
        runner.run("frames", base + ["-loglevel", "error"] + source + ["-map", f"0:{video['index']}",
            "-vf", f"select={select},scale=360:-2:flags=lanczos", "-vsync", "0", "-frames:v", str(len(indices)),
            "-threads", "1", str(frames_dir / "frame_%03d.png")])
        report["frames"] = []
        for i, frame_number in enumerate(indices, 1):
            path = frames_dir / f"frame_{i:03d}.png"
            if not path.is_file() or not path.stat().st_size:
                raise AuditError(f"Frame extraction missing fresh output: {path.name}")
            report["frames"].append({"frame_index": frame_number, "time_s": times[frame_number],
                                     "path": str(path.relative_to(root)), "sha256": sha256(path)})
        report["checks"]["representative_frames"] = "pass"
        rows = math.ceil(len(indices) / 3)
        runner.run("contact_sheet", base + ["-loglevel", "error", "-framerate", "1", "-start_number", "1", "-i",
            str(frames_dir / "frame_%03d.png"), "-vf", f"tile=3x{rows}:padding=6:margin=6", "-frames:v", "1",
            "-threads", "1", str(root / "contact_sheet.png")])
        if not (root / "contact_sheet.png").is_file() or not (root / "contact_sheet.png").stat().st_size:
            raise AuditError("No fresh contact sheet was produced")
        report["contact_sheet"] = "contact_sheet.png"
        report["checks"]["contact_sheet"] = "pass"
        if audio:
            audio_duration = number(audio.get("duration"))
            audio_start = number(audio.get("start_time"))
            if audio_duration is None and audio.get("duration_ts") is not None and rate(audio.get("time_base")):
                audio_duration = float(audio["duration_ts"]) * rate(audio["time_base"])
            if audio_duration is None or audio_start is None:
                finding("warning", "Audio start/end timestamps unavailable; audio/video boundary alignment remains unverified")
                report["checks"]["audio_boundaries"] = "not_checked"
            else:
                gap = max(abs(audio_start - timeline["start_s"]), abs(audio_start + audio_duration - timeline["end_s"]))
                report["av_boundary_gap_s"] = gap
                bad = gap > float((spec or {}).get("max_av_gap_s", .15))
                report["checks"]["audio_boundaries"] = "fail" if bad else "pass"
                if bad:
                    finding("fail", f"Audio/video start or end gap is {gap:.3f}s (not a content-sync test)")
            audio_full = scan_seconds is None or (audio_duration is not None and scan_seconds >= audio_duration)
            audio_limit = audio_duration if audio_full else scan_seconds
            _, logs = runner.run("audio_scan", base + source + ["-map", f"0:{audio['index']}", "-af",
                "asetpts=PTS-STARTPTS,silencedetect=n=-50dB:d=0.5,loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
                *([] if audio_full else ["-t", str(scan_seconds)]), "-vn", "-sn", "-dn", "-f", "null", "-"])
            report["audio_measurements"] = parse_loudness(logs)
            if audio_limit is not None:
                report["events"] += parse_events(logs, audio_limit, audio=True)
            else:
                finding("warning", "Cannot bound silence events without audio duration; silence intervals not certified")
            report["coverage"]["audio_scan_complete"] = audio_full
            report["checks"]["audio_scan"] = "pass" if audio_full else "partial"
            if not audio_full:
                finding("warning", "Audio anomaly analysis is partial")
            measurements = report["audio_measurements"]
            if measurements["nonfinite_measurement"]:
                finding("warning", "Audio loudness/peak is nonfinite (for example silence); requires review")
            for key, observed, compare in (("max_true_peak_dbfs", measurements["true_peak_dbfs"], "max"),
                                           ("loudness_min_lufs", measurements["integrated_lufs"], "min"),
                                           ("loudness_max_lufs", measurements["integrated_lufs"], "max")):
                if spec and key in spec:
                    if observed is None or (observed > spec[key] if compare == "max" else observed < spec[key]):
                        finding("fail", f"{key}: expected {spec[key]}, got {observed}")
        else:
            report["checks"]["audio_scan"] = "not_applicable"
        review_events(report["events"], (spec or {}).get("allowed_events", []))
        for event in report["events"]:
            if event["status"] == "review_required":
                finding("warning", f"Unreviewed {event['kind']} interval: {event['start_s']:.3f}–{event['end_s']:.3f}s")
        if sha256(video_path) != report["input_sha256"]:
            raise AuditError("Input changed during audit; all generated evidence is invalid")
        report["checks"]["input_stable"] = "pass"
        report["execution_status"] = "success"
        severities = {f["severity"] for f in report["findings"]}
        report["technical_verdict"] = "fail" if "fail" in severities else ("warning" if "warning" in severities else "pass")
        report["exit_code"] = 0 if report["technical_verdict"] == "pass" else 1
    except (AuditError, OSError, ValueError, KeyError, TypeError) as exc:
        finding("error", str(exc))
        report.update(execution_status="failed", technical_verdict="not_verified", exit_code=2)
    write_report(root, report)
    return report, root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="Parent directory; each run gets a fresh child")
    parser.add_argument("--spec", type=Path, help="JSON delivery specification; missing spec prevents exit 0")
    parser.add_argument("--scan-seconds", type=float, help="Limit pixel/audio anomaly scans; default is complete media")
    parser.add_argument("--timeout", type=float, default=120, help="Per-command timeout in seconds, not a total budget")
    args = parser.parse_args()
    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8")) if args.spec else None
        report, root = audit(args.video, args.output, spec, scan_seconds=args.scan_seconds, timeout=args.timeout)
    except (OSError, ValueError) as exc:
        print(f"Cannot start audit: {exc}", file=sys.stderr)
        return 2
    print(f"Execution: {report['execution_status']}; machine verdict: {report['technical_verdict']}")
    print(f"Report: {root / 'report.md'}")
    print(f"JSON: {root / 'report.json'}")
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
