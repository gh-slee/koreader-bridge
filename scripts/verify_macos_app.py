#!/usr/bin/env python3
"""Launch the actual native app with isolated synthetic data and retain its captures."""
from __future__ import annotations
import argparse
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def verify(app, output_root):
    app = Path(app).resolve()
    executable = app / "Contents/MacOS/KOReaderBridge"
    if not executable.is_file():
        raise ValueError("Choose a built KOReader Bridge.app.")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    base = Path(output_root).resolve()
    if base == Path("/Volumes") or Path("/Volumes") in base.parents:
        raise ValueError("Synthetic verification output must be on the Mac, not a reader volume.")
    output = base / stamp
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(Path.home()),
           "TMPDIR": os.environ.get("TMPDIR", "/tmp"), "LC_CTYPE": "UTF-8"}
    with (output / "native-process.log").open("w") as log:
        process = subprocess.Popen([str(executable), "--test-root", str(output), "--integration-test"],
                                   stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        try:
            code = process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)  # Only this isolated synthetic test app.
            process.wait(timeout=10)
            raise ValueError("The synthetic native test timed out; inspect the retained local log.")
    result_file = output / "NATIVE_TEST_RESULTS.json"
    if code != 0 or not result_file.is_file():
        raise ValueError("Native launch failed; inspect " + str(output))
    result = json.loads(result_file.read_text())
    if not result.get("passed"):
        raise ValueError("Native workflow checks failed: " + str(result.get("error", "unknown")))
    for name in result["screenshots"]:
        path = output / name
        if not path.is_file() or path.stat().st_size < 1000:
            raise ValueError("The rendered app capture is missing.")
    (ROOT / ".local/latest-desktop-qa.txt").write_text(str(output) + "\n")
    print(json.dumps({"app": str(app), "results": str(result_file),
                      "cases_passed": len(result["cases"]), "screenshots": result["screenshots"],
                      "physical_readers_accessed": False,
                      "capture_method": "NSView fallback" if (output / "CAPTURE_LIMITATION.txt").exists() else "own-process window capture"}), flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--output-root", type=Path, default=ROOT / ".local/desktop-qa")
    args = parser.parse_args()
    verify(args.app, args.output_root)


if __name__ == "__main__":
    main()
