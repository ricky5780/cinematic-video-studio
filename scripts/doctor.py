#!/usr/bin/env python3
"""Probe local executables without installing software, networking, or spending."""
import json
import platform
import shutil
import subprocess
import sys


def inspect() -> dict:
    report = {"python": platform.python_version(), "platform": platform.system(), "tools": {},
              "agent_capabilities": {k: "must_be_verified_in_agent_session" for k in
                                     ("image_generation", "image_review", "audio_review", "lemo_opuscar")}}
    for name, flag in (("ffmpeg", "-version"), ("ffprobe", "-version"), ("node", "--version"), ("blender", "--version")):
        path = shutil.which(name)
        item = {"available": False, "path": path, "required_for_audit": name in ("ffmpeg", "ffprobe")}
        if path:
            try:
                result = subprocess.run([path, flag], stdin=subprocess.DEVNULL, capture_output=True,
                                        text=True, encoding="utf-8", errors="replace", timeout=10)
                item.update(available=result.returncode == 0, version=(result.stdout or result.stderr).splitlines()[:1])
            except (OSError, subprocess.TimeoutExpired) as exc:
                item["error"] = str(exc)
        report["tools"][name] = item
    return report


if __name__ == "__main__":
    result = inspect()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if all(v["available"] for v in result["tools"].values() if v["required_for_audit"]) else 1)
