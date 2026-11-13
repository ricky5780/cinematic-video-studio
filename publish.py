#!/usr/bin/env python3
"""Publish a verified release to a NEW public GitHub repository via local gh.

Requires --public, authenticated GitHub CLI, and an owner matching that login.
No tokens are collected. Refuses existing repositories and never force-pushes.
Uses only files listed in RELEASE_MANIFEST.json and a clean temporary git repo.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile


def run(args: list[str], cwd: Path | None = None, timeout: int = 120, check: bool = True):
    result = subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"Command failed: {args[0]} {args[1]}\n{result.stderr[-3000:]}")
    return result


def verify_release(root: Path) -> dict[str, str]:
    manifest_path = root / "RELEASE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest["files"]
    if not files or not all(name in files for name in ("SKILL.md", "LICENSE", "README.md", "scripts/video_audit.py")):
        raise ValueError("Incomplete release manifest")
    for name, expected in files.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or ".git" in relative.parts:
            raise ValueError(f"Unsafe release path: {name}")
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError(f"Missing or unsafe release file: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Release checksum mismatch: {name}")
    return files


def publish(root: Path, owner: str, name: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name):
        raise ValueError("Invalid owner or repository name")
    gh, git = shutil.which("gh"), shutil.which("git")
    if not gh or not git:
        raise RuntimeError("Install Git and GitHub CLI first. Authenticate locally with gh auth login; never paste tokens into chat.")
    files = verify_release(root)
    profile = json.loads(run([gh, "api", "user"]).stdout)
    if profile["login"].lower() != owner.lower():
        raise ValueError(f"Authenticated account is {profile['login']}, not requested owner {owner}")
    full_name = f"{owner}/{name}"
    lookup = run([gh, "api", f"repos/{full_name}"], check=False)
    if lookup.returncode == 0:
        raise ValueError("Repository already exists. Refusing to replace or push into an existing repository.")
    if "404" not in lookup.stderr + lookup.stdout:
        raise RuntimeError("Cannot safely verify repository absence; no remote changes made.")
    tests = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=root, timeout=300)
    if re.search(r"\bskipped=\d+", tests.stderr):
        raise RuntimeError("Some tests were skipped; install prerequisites and rerun before publishing.")
    version = (root / "VERSION").read_text().strip()
    with tempfile.TemporaryDirectory(prefix="cvs-publish-") as temp:
        staging = Path(temp)
        for name_in_release in [*files, "RELEASE_MANIFEST.json"]:
            target = staging / name_in_release
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name_in_release, target)
        run([git, "init", "-b", "main"], cwd=staging)
        run([git, "add", "--", *files, "RELEASE_MANIFEST.json"], cwd=staging)
        identity = ["-c", f"user.name={profile['login']}", "-c",
                    f"user.email={profile['id']}+{profile['login']}@users.noreply.github.com"]
        run([git, *identity, "commit", "-m", f"Release Cinematic Video Studio v{version}"], cwd=staging)
        run([git, "tag", f"v{version}"], cwd=staging)
        local_sha = run([git, "rev-parse", "HEAD"], cwd=staging).stdout.strip()
        run([gh, "repo", "create", full_name, "--public", "--description",
             "Codex video direction skill: concept-to-render workflow, resumable production and evidence-based video QA."])
        url = f"https://github.com/{full_name}"
        try:
            run([git, "remote", "add", "origin", url + ".git"], cwd=staging)
            run([git, "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential", "push", "--atomic",
                 "origin", "main", f"refs/tags/v{version}"], cwd=staging)
            remote = json.loads(run([gh, "api", f"repos/{full_name}"]).stdout)
            remote_sha = run([gh, "api", f"repos/{full_name}/commits/main", "--jq", ".sha"]).stdout.strip()
            if remote.get("private") is not False or remote_sha != local_sha:
                raise RuntimeError("Remote visibility or commit verification did not match")
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Repository was created at {url}, but publication is incomplete: {exc}. Do not claim release success.") from exc
    result = {"repository": url, "visibility": "public", "commit": local_sha, "tag": f"v{version}",
              "github_actions": "not_verified", "codex_lemo_e2e": "not_tested"}
    (root / "PUBLISH_RESULT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", action="store_true", help="Explicitly authorize creation of a public repository")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--name", default="cinematic-video-studio")
    args = parser.parse_args()
    if not args.public:
        parser.error("--public is required; no remote changes were made")
    try:
        result = publish(Path(__file__).resolve().parent, args.owner, args.name)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
