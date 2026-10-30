#!/usr/bin/env python3
"""Build an isolated local SwiftUI .app with a checksum-pinned Python runtime."""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import posixpath
import shutil
import subprocess
import tarfile
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
BACKEND_INPUTS = [
    "bridge_desktop_helper.py", "bridge_devices.py", "koreader-bridge.py", "kobo-koreader-migrate.py", "LICENSE",
    "README.md", "ACCEPTANCE.md",
    "locales/registry.json", "locales/en.json", "locales/zh-Hant.json", "locales/zh-Hans.json",
    "docs/USAGE.md", "docs/RECOVERY.md", "docs/TROUBLESHOOTING.md", "docs/MACOS.md",
    "docs/DESKTOP_ARCHITECTURE.md", "docs/DEVELOPMENT.md", "docs/MAINTAINING.md",
]
SWIFT_INPUTS = ["macos/KOReaderBridgeApp.swift", "macos/NativeChecks.swift", "macos/Icon.swift", "macos/WindowCapture.h", "macos/WindowCapture.c"]
MACHO = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
         b"\xfe\xed\xfa\xce", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def run(*args):
    subprocess.run([str(x) for x in args], check=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_extract(archive, destination):
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            p = PurePosixPath(member.name)
            if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != "python":
                raise ValueError("Unsafe runtime archive path.")
            if not (member.isdir() or member.isfile() or member.issym() or member.islnk()):
                raise ValueError("Unsupported runtime archive member.")
            if member.issym() or member.islnk():
                target = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname)
                                           if member.issym() else member.linkname)
                if not target.startswith("python/"):
                    raise ValueError("Runtime link escapes its prefix.")
        try:
            tar.extractall(destination, filter="data")
        except TypeError:  # Older build Python; all members were checked above.
            tar.extractall(destination)


def build(output_root, runtime_archive=None):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("This build targets Apple Silicon macOS only. Intel runtime packaging is not implemented.")
    from check_publication import inspect_blob
    for name in BACKEND_INPUTS + SWIFT_INPUTS + ["desktop/runtime-lock.json"]:
        path = ROOT / name
        if path.is_symlink() or not path.is_file() or inspect_blob(name, path.read_bytes()):
            raise ValueError("A required source input is missing or failed publication checks: " + name)
    lock = json.loads((ROOT / "desktop/runtime-lock.json").read_text())
    if lock["architecture"] != "arm64" or not lock["url"].startswith("https://github.com/astral-sh/python-build-standalone/releases/download/"):
        raise ValueError("Unsupported runtime manifest.")
    cache = ROOT / ".local/runtime-cache"
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = Path(runtime_archive).resolve() if runtime_archive else cache / ("python-" + lock["sha256"][:16] + ".tar.gz")
    if not archive.exists():
        if runtime_archive:
            raise ValueError("The supplied runtime archive does not exist.")
        partial = cache / (uuid.uuid4().hex + ".download")
        print("Downloading checksum-pinned CPython runtime...", flush=True)
        run("/usr/bin/curl", "--fail", "--location", "--connect-timeout", "20", "--max-time", "240",
            "--output", partial, lock["url"])
        if partial.stat().st_size != lock["bytes"] or sha(partial) != lock["sha256"]:
            raise ValueError("Runtime checksum mismatch; nothing was bundled.")
        partial.rename(archive)
    if archive.is_symlink() or archive.stat().st_size != lock["bytes"] or sha(archive) != lock["sha256"]:
        raise ValueError("Runtime archive differs from the pinned manifest.")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    output = Path(output_root).resolve() / stamp
    output.mkdir(parents=True, exist_ok=False)
    app = output / "KOReader Bridge.app"
    contents = app / "Contents"
    resources = contents / "Resources"
    binary_dir = contents / "MacOS"
    binary_dir.mkdir(parents=True)
    resources.mkdir()
    backend = resources / "backend"
    for name in BACKEND_INPUTS:
        target = backend / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    with tempfile.TemporaryDirectory(prefix="koreader-runtime-") as temp:
        safe_extract(archive, Path(temp))
        shutil.copytree(Path(temp) / "python", resources / "python", symlinks=True)
    runtime = resources / "python"
    # These are build/interactive extras; the complete operational stdlib stays bundled.
    lib = runtime / ("lib/python" + ".".join(lock["python_version"].split(".")[:2]))
    for name in ["site-packages", "ensurepip", "idlelib", "tkinter", "turtledemo", "test", "__pycache__"]:
        path = lib / name
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
    for p in list(runtime.rglob("__pycache__")):
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
    for p in (runtime / "bin").iterdir():
        if p.name.startswith(("pip", "idle", "pydoc", "python3-config")) and not p.is_dir():
            p.unlink()
    run(runtime / "bin/python3", "-I", "-B", "-c",
        "import sys,sqlite3,ssl,hashlib,zipfile,plistlib; assert sys.version.startswith('" + lock["python_version"] + "')")
    modules = output / "module-cache"
    modules.mkdir()
    executable = binary_dir / "KOReaderBridge"
    print("Compiling native macOS app...", flush=True)
    capture_object = output / "WindowCapture.o"
    run("/usr/bin/xcrun", "clang", "-arch", "arm64", "-mmacosx-version-min=14.0", "-c",
        ROOT / "macos/WindowCapture.c", "-o", capture_object)
    run("/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-O", "-target", "arm64-apple-macos14.0",
        "-module-cache-path", modules, "-module-name", "KOReaderBridge",
        "-import-objc-header", ROOT / "macos/WindowCapture.h", ROOT / SWIFT_INPUTS[0], ROOT / SWIFT_INPUTS[1], capture_object, "-o", executable)
    icon_png = output / "icon.png"
    run("/usr/bin/xcrun", "swift", "-module-cache-path", modules, ROOT / "macos/Icon.swift", icon_png)
    iconset = output / "Bridge.iconset"; iconset.mkdir()
    for size in [16, 32, 128, 256, 512]:
        for scale in [1, 2]:
            filename = "icon_" + str(size) + "x" + str(size) + ("@2x" if scale == 2 else "") + ".png"
            run("/usr/bin/sips", "-z", str(size * scale), str(size * scale), icon_png, "--out", iconset / filename)
    run("/usr/bin/iconutil", "-c", "icns", iconset, "-o", resources / "Bridge.icns")
    info = {
        "CFBundleExecutable": "KOReaderBridge", "CFBundleIdentifier": "io.github.gh-slee.koreader-bridge",
        "CFBundleName": "KOReader Bridge", "CFBundleDisplayName": "KOReader Bridge",
        "CFBundleShortVersionString": "1.1.0", "CFBundleVersion": "2",
        "CFBundlePackageType": "APPL", "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleIconFile": "Bridge", "LSMinimumSystemVersion": "14.0",
        "NSHighResolutionCapable": True, "NSPrincipalClass": "NSApplication",
        "NSRemovableVolumesUsageDescription": "KOReader Bridge reads and migrates the Kobo you explicitly connect and confirm.",
        "NSSupportsAutomaticTermination": False,
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    licenses = [p for p in runtime.rglob("*") if p.is_file() and "license" in p.name.lower()]
    if not licenses:
        raise ValueError("Runtime license notices are missing.")
    metadata = {
        "schema_version": 1, "app": "KOReader Bridge", "development_version": "1.1.0-dev.2",
        "architecture": "arm64", "minimum_macos": "14.0", "python": lock,
        "source_inputs": {name: sha(ROOT / name) for name in BACKEND_INPUTS + SWIFT_INPUTS},
        "signing": "ad-hoc local", "notarized": False, "runtime_license_files": len(licenses),
        "contains_device_data": False, "network_at_launch": False,
    }
    (resources / "BUILD_INFO.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print("Ad-hoc signing bundled executables and extensions...", flush=True)
    for path in sorted(runtime.rglob("*")):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as f:
                magic = f.read(4)
            if magic in MACHO:
                run("/usr/bin/codesign", "--force", "--sign", "-", path)
    run("/usr/bin/codesign", "--force", "--sign", "-", executable)
    run("/usr/bin/codesign", "--force", "--sign", "-", app)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", app)
    result = {"app": str(app), "output": str(output), "metadata": metadata}
    (output / "BUILD_RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    (ROOT / ".local/latest-desktop-build.txt").write_text(str(app) + "\n")
    print(json.dumps({"app": str(app), "architecture": "arm64", "minimum_macos": "14.0", "signing": "ad-hoc", "notarized": False}), flush=True)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / ".local/desktop-builds")
    parser.add_argument("--runtime-archive", type=Path, help="Use an already downloaded, pinned archive.")
    parser.add_argument("--launch", action="store_true", help="Open the built app after successful verification.")
    args = parser.parse_args()
    app = build(args.output_root, args.runtime_archive)
    if args.launch:
        run("/usr/bin/open", app)


if __name__ == "__main__":
    main()
