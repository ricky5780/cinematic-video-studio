#!/usr/bin/env python3
"""Create resumable project state and verify explicitly registered artifact caches.

Cache validity is NOT creative approval. Only declared dependencies are hashed;
include source, assets, config, lockfiles and an environment/version manifest.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

STATE = "PROJECT_STATE.json"
MODES = ("explore", "prototype", "produce", "refine", "audit")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def local_file(root: Path, name: str) -> Path:
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Dependency must be a file inside the project: {name}")
    return path


@contextmanager
def state_lock(root: Path):
    lock = root / ".cvs-state.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("Project state is locked; inspect active writers before removing a stale lock") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def save(root: Path, state: dict) -> None:
    temp = root / (".state-" + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, root / STATE)
    finally:
        temp.unlink(missing_ok=True)


def init(root: Path, mode: str) -> dict:
    if mode not in MODES:
        raise ValueError(f"Unsupported mode: {mode}")
    root.mkdir(parents=True, exist_ok=True)
    with state_lock(root):
        if (root / STATE).exists():
            raise ValueError("State already exists; read it instead of overwriting")
        state = {"schema_version": 1, "skill_version": "1.1.0", "mode": mode, "phase": "brief",
                 "selected_direction": None, "style_lock": None,
                 "gates": {"A": "not_checked", "B": "not_checked", "C": "not_checked"},
                 "capabilities": {"image_generation": "unknown", "image_review": "unknown",
                                  "audio_review": "unknown", "lemo_opuscar": "unknown"},
                 "budget": {"concept_directions": 4, "render_candidates": 2, "repair_rounds_per_issue": 2,
                            "paid_calls_authorized": False, "remaining_account_quota": "unknown"},
                 "artifacts": {}, "issues": [], "next_action": "Resolve brief and probe available tools"}
        save(root, state)
    return state


def record(root: Path, key: str, inputs: list[str], output: str, seed: str) -> dict:
    if not inputs or not key.strip():
        raise ValueError("A key and at least one explicit input dependency are required")
    root = root.resolve()
    with state_lock(root):
        state = json.loads((root / STATE).read_text(encoding="utf-8"))
        dependencies = {str(local_file(root, item).relative_to(root)): digest(local_file(root, item)) for item in inputs}
        out = local_file(root, output)
        manifest = {"inputs": dependencies, "seed": seed}
        fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        artifact = {**manifest, "fingerprint": fingerprint, "output": str(out.relative_to(root)),
                    "output_sha256": digest(out), "recorded_utc": datetime.now(timezone.utc).isoformat(),
                    "creative_approval": "not_checked"}
        state["artifacts"][key] = artifact
        save(root, state)
    return artifact


def verify(root: Path) -> dict:
    state = json.loads((root / STATE).read_text(encoding="utf-8"))
    result = {}
    for key, entry in state.get("artifacts", {}).items():
        changed = []
        for name, expected in {**entry["inputs"], entry["output"]: entry["output_sha256"]}.items():
            try:
                if digest(local_file(root, name)) != expected:
                    changed.append(name)
            except (OSError, ValueError):
                changed.append(name)
        manifest = {"inputs": entry["inputs"], "seed": entry["seed"]}
        expected_fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        if expected_fingerprint != entry["fingerprint"]:
            changed.append("<seed_or_dependency_manifest>")
        result[key] = {"cache_status": "stale" if changed else "valid_for_declared_inputs", "changed": changed,
                       "creative_approval": entry.get("creative_approval", "not_checked")}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("init")
    create.add_argument("--mode", choices=MODES, default="explore")
    register = sub.add_parser("record")
    register.add_argument("--key", required=True)
    register.add_argument("--input", action="append", required=True, dest="inputs")
    register.add_argument("--output", required=True)
    register.add_argument("--seed", default="unspecified")
    sub.add_parser("verify")
    sub.add_parser("show")
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = init(args.project, args.mode)
        elif args.command == "record":
            result = record(args.project, args.key, args.inputs, args.output, args.seed)
        elif args.command == "verify":
            result = verify(args.project)
        else:
            result = json.loads((args.project / STATE).read_text(encoding="utf-8"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if args.command == "verify" and any(x["cache_status"] == "stale" for x in result.values()) else 0
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
