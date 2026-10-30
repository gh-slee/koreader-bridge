#!/usr/bin/env python3
"""Launch the actual native app with isolated synthetic data and retain its captures."""
from __future__ import annotations
import argparse
import datetime
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def verify(app, output_root, launch_method="direct"):
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
    # Direct execution keeps development own-window capture in the invoking
    # desktop context. Launch Services remains available for normal-open checks,
    # but can yield only a window thumbnail on some macOS configurations.
    if launch_method not in {"direct", "services"}:
        raise ValueError("Choose direct or services application launch.")
    log_path = output / "native-process.log"
    log_path.touch(mode=0o600)
    if launch_method == "services":
        command = ["/usr/bin/open", "-n", "-W", "-a", str(app),
                   "--stdout", str(log_path), "--stderr", str(log_path)]
        for key, value in env.items():
            command += ["--env", key + "=" + value]
        command += ["--args", "--test-root", str(output), "--integration-test"]
    else:
        command = [str(executable), "--test-root", str(output), "--integration-test"]
    with (output / ("launcher.log" if launch_method == "services" else "native-process.log")).open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        try:
            code = process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            # Terminate only an app with this exact fresh synthetic test root.
            rows = subprocess.check_output(["/bin/ps", "-axo", "pid=,command="], text=True)
            marker = "--test-root " + str(output) + " --integration-test"
            for row in rows.splitlines():
                parts = row.strip().split(None, 1)
                if len(parts) == 2 and parts[1].startswith(str(executable) + " ") and marker in parts[1]:
                    try:
                        os.kill(int(parts[0]), signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            if launch_method == "direct":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                process.terminate()
            process.wait(timeout=10)
            raise ValueError("The synthetic native test timed out; inspect the retained local log.")
    result_file = output / "NATIVE_TEST_RESULTS.json"
    if code != 0 or not result_file.is_file():
        raise ValueError("Native launch failed; inspect " + str(output))
    result = json.loads(result_file.read_text())
    if not result.get("passed"):
        raise ValueError("Native workflow checks failed: " + str(result.get("error", "unknown")))
    layouts = {item["capture"]: item for item in result.get("layouts", [])}
    for name in result["screenshots"]:
        path = output / name
        if not path.is_file() or path.stat().st_size < 1000:
            raise ValueError("The rendered app capture is missing.")
        header = path.read_bytes()[:24]
        if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("The rendered app capture is invalid.")
        width, height = struct.unpack(">II", header[16:24])
        layout = layouts.get(name)
        if layout and (width < layout["width"] * 0.9 or height < layout["height"] * 0.9):
            raise ValueError("A window thumbnail cannot count as visual verification.")
    (ROOT / ".local/latest-desktop-qa.txt").write_text(str(output) + "\n")
    print(json.dumps({"app": str(app), "results": str(result_file),
                      "cases_passed": len(result["cases"]), "screenshots": result["screenshots"],
                      "physical_readers_accessed": False, "launch_method": launch_method,
                      "visual_capture_complete": not (output / "CAPTURE_LIMITATION.txt").exists(),
                      "capture_method": "NSView fallback" if (output / "CAPTURE_LIMITATION.txt").exists() else "own-process window capture"}), flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--output-root", type=Path, default=ROOT / ".local/desktop-qa")
    parser.add_argument("--launch-method", choices=["direct", "services"], default="direct",
                        help="Direct app execution (default), or normal macOS Launch Services.")
    args = parser.parse_args()
    verify(args.app, args.output_root, args.launch_method)


if __name__ == "__main__":
    main()
