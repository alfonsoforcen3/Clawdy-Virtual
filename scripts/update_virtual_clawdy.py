#!/usr/bin/env python3
"""Check and stage tested Virtual Clawdy source previews without replacing the running app."""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
from urllib.request import Request, urlopen


REPOSITORY = "alfonsoforcen3/Clawdy-Virtual"
REPOSITORY_ID = 1448167503
API = f"https://api.github.com/repos/{REPOSITORY}"
REMOTE = f"https://github.com/{REPOSITORY}.git"
SHA = re.compile(r"[a-f0-9]{40}\Z")


class UpdateUnavailable(Exception):
    pass


def github(path):
    request = Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Virtual-Clawdy-Updater",
    })
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def candidate_revision(current):
    if not SHA.fullmatch(current):
        raise UpdateUnavailable("Rebuild from the public Clawdy-Virtual checkout to enable updates.")
    latest = github("/git/ref/heads/main")["object"]["sha"]
    if not SHA.fullmatch(latest):
        raise UpdateUnavailable("GitHub returned an invalid revision.")
    if latest == current:
        return None
    comparison = github(f"/compare/{current}...{latest}")
    if comparison["status"] != "ahead" or comparison["merge_base_commit"]["sha"] != current:
        raise UpdateUnavailable("The installed revision is outside the Clawdy-Virtual main history.")
    runs = github(f"/actions/workflows/checks.yml/runs?branch=main&event=push&head_sha={latest}&per_page=20")
    for run in runs["workflow_runs"]:
        if (run.get("head_sha") == latest and run.get("head_branch") == "main"
                and run.get("event") == "push" and run.get("conclusion") == "success"
                and (run.get("head_repository") or {}).get("id") == REPOSITORY_ID):
            return latest
    raise UpdateUnavailable("The latest revision is waiting for GitHub checks to pass.")


def run(args, *, env=None, timeout=900):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.check_output(
        args, env=env, timeout=timeout, stderr=subprocess.STDOUT, **options
    ).decode("utf-8", errors="replace").strip()


def git_env():
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.hooksPath", GIT_CONFIG_VALUE_0=os.devnull)
    return env


def record_pending(root, current, revision):
    pending = root / "pending"
    pending.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clawdy-", dir=pending) as temporary:
        marker = Path(temporary) / "revision"
        marker.write_bytes((revision + "\n").encode("ascii"))
        marker.replace(pending / current)


def stage_update(revision, current, app):
    if platform.system() == "Darwin" and app.name == "VirtualClawdy.app":
        root = Path.home() / "Library/Caches/ClawdyPrototype/Updates"
        entry = Path("VirtualClawdy.app")
        executable = entry / "Contents/MacOS/VirtualClawdy"
    elif platform.system() == "Windows" and app.name == "Clawdy.Windows.exe":
        root = Path(os.environ["LOCALAPPDATA"]) / "ClawdyPrototype" / "Updates"
        entry = executable = Path("Clawdy.Windows.exe")
    else:
        raise UpdateUnavailable("Updates require the native Clawdy desktop app.")
    git = shutil.which("git")
    if git is None:
        raise UpdateUnavailable("Install Git for your platform, then retry.")
    root.mkdir(parents=True, exist_ok=True)
    target = root / revision
    if (target / executable).is_file():
        record_pending(root, current, revision)
        return str(target / entry)

    with tempfile.TemporaryDirectory(prefix="clawdy-", dir=root) as temporary:
        work = Path(temporary)
        source = work / "source"
        build = work / "build"
        env = git_env()
        run([git, "clone", "--quiet", "--no-checkout", "--single-branch", "--branch", "main",
             "--no-tags", REMOTE, str(source)], env=env, timeout=180)
        git_at_source = [git, "-C", str(source)]
        if run(git_at_source + ["rev-parse", "HEAD"], env=env, timeout=15) != revision:
            raise UpdateUnavailable("Clawdy changed on GitHub during the update. Try again shortly.")
        run(git_at_source + ["merge-base", "--is-ancestor", current, revision], env=env, timeout=15)
        run(git_at_source + ["checkout", "--quiet", "--detach", revision], env=env, timeout=60)
        if platform.system() == "Darwin":
            run(["/bin/bash", str(source / "desktop/macos/build.sh")],
                env={**env, "CLAWDY_BUILD_DIR": str(build)})
            run([str(build / executable), "--self-test"], timeout=90)
        else:
            powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                 str(source / "desktop/windows/build.ps1"), "-Output", str(build)], env=env)
        if not (build / executable).is_file():
            raise UpdateUnavailable("The build did not produce a Clawdy app.")
        try:
            build.rename(target)
        except OSError:
            if not (target / executable).is_file():
                raise
    record_pending(root, current, revision)
    return str(target / entry)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "install"))
    parser.add_argument("--current", required=True)
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    try:
        revision = candidate_revision(args.current)
        if revision is None:
            result = {"status": "current"}
        elif args.command == "check":
            result = {"status": "available", "revision": revision}
        else:
            path = stage_update(revision, args.current, args.app)
            result = {"status": "ready", "revision": revision, "path": path}
    except UpdateUnavailable as error:
        result = {"status": "unavailable", "message": str(error)}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        result = {"status": "unavailable", "message":
                  "Clawdy could not finish the update. Check your connection and build tools, then retry."}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
