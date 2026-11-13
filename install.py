#!/usr/bin/env python3
"""Install the skill locally. No network. Existing installation needs --replace.
Backups are outside the skills search directory, avoiding duplicate skill names.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import sys
import uuid

PAYLOAD = ("SKILL.md", "agents", "scripts", "references", "templates", "VERSION", "LICENSE")


def install(source: Path, destination: Path, replace: bool = False) -> Path | None:
    source = source.resolve()
    destination = destination.expanduser().absolute()
    if destination.is_symlink():
        raise ValueError("Refusing to replace a symlink installation")
    if destination.exists() and not replace:
        raise ValueError("Installation already exists. Inspect it, then use --replace to back it up and upgrade.")
    for name in PAYLOAD:
        if not (source / name).exists():
            raise ValueError(f"Missing package member: {name}")
    if destination.resolve().is_relative_to(source) or source.is_relative_to(destination.resolve()):
        raise ValueError("Source and destination must not overlap")
    destination.parent.mkdir(parents=True, exist_ok=True)
    scratch = destination.parent.parent / (".cvs-install-" + uuid.uuid4().hex)
    backup = None
    try:
        scratch.mkdir()
        for name in PAYLOAD:
            item = source / name
            if item.is_dir():
                shutil.copytree(item, scratch / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copy2(item, scratch / name)
        if destination.exists():
            backup = destination.parent.parent / "skill-backups" / (destination.name + "-" + uuid.uuid4().hex[:12])
            backup.parent.mkdir(parents=True, exist_ok=True)
            destination.rename(backup)
        try:
            scratch.rename(destination)
        except OSError:
            if backup and not destination.exists():
                backup.rename(destination)
            raise
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path.home() / ".agents/skills/cinematic-video-studio")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    try:
        backup = install(Path(__file__).resolve().parent, args.destination, args.replace)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Installed: {args.destination}")
    if backup:
        print(f"Previous installation backup: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
