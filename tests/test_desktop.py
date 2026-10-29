"""Desktop protocol safety and real synthetic workflow regressions."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_publication
import build_macos_app


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "PrivateOutput"

    def call(self, operation, config=None, fixture=None, run_id=None, decline=False, confirmation=None, **extra):
        req = {"version": 1, "id": "desktop-test", "operation": operation, "workspace": str(self.workspace)}
        if config is not None:
            req["config"] = config
        if fixture:
            req["fixtureRoot"] = str(fixture)
        if run_id:
            req["runID"] = run_id
        req.update(extra)
        proc = subprocess.Popen([sys.executable, "-I", "-B", str(ROOT / "bridge_desktop_helper.py")],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        timer = threading.Timer(45, proc.kill)
        timer.start()
        events = []
        def send(packet):
            try:
                proc.stdin.write(json.dumps(packet) + "\n")
                proc.stdin.flush()
            except BrokenPipeError:
                pass
        send(req)
        result = None
        try:
            for line in proc.stdout:
                packet = json.loads(line)
                self.assertEqual(packet["version"], 1)
                if packet["event"] == "result":
                    result = packet
                    break
                events.append(packet)
                if packet["event"] == "prompt":
                    if packet["kind"] == "boolean":
                        answer = "n" if decline and packet["key"] == "confirm.migration" else "y"
                    elif packet["kind"] == "choice":
                        answer = packet["choices"][0]["value"]
                    elif packet.get("requiredText"):
                        answer = packet["requiredText"] if confirmation is None else confirmation
                    else:
                        answer = ""
                    send({"version": 1, "id": "desktop-test", "operation": "reply",
                          "promptID": packet["promptID"], "text": answer})
            proc.stdin.close()
            proc.wait(timeout=10)
            self.assertIsNotNone(result, proc.stderr.read()[-2000:])
            return result, events
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            proc.stdout.close()
            proc.stderr.close()

    def sample(self):
        result, _ = self.call("create_demo")
        self.assertTrue(result["ok"], result)
        base = Path(result["data"]["fixtureRoot"])
        self.workspace = Path(result["data"]["workspace"])
        return base

    def config(self, mode="full", dry=True, action="migration", run_id=None):
        value = {"mode": mode, "dryRun": dry, "action": action,
                 "sourceModel": "Sample Source", "targetModel": "Sample Target", "locale": "en"}
        if run_id:
            value["runID"] = run_id
        return value

    def tree(self, path):
        return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in path.rglob("*") if p.is_file() and not p.is_symlink()}

    def test_health_is_offline_versioned_and_has_no_workspace_writes(self):
        result, events = self.call("health")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["protocolVersion"], 1)
        self.assertEqual(events, [])
        self.assertFalse(self.workspace.exists())

    def test_unknown_version_operation_and_field_refuse(self):
        for values in [{"version": 99}, {"operation": "shell"}, {"unexpected": "ignored?"}]:
            with self.subTest(values=values):
                result, _ = self.call("health", **values) if "operation" not in values else self.call(values["operation"])
                self.assertFalse(result["ok"])
                self.assertFalse(self.workspace.exists())

    def test_bad_scopes_ids_and_volume_workspace_refuse(self):
        for op, values in [("details", {"runID": "../outside"}), ("catalog", {"workspace": "/Volumes/Example"}),
                           ("execute", {"config": {"command": "arbitrary"}}), ("catalog", {"keepSuccessful": 0})]:
            with self.subTest(op=op, values=values):
                result, _ = self.call(op, **values)
                self.assertFalse(result["ok"])

    def test_symlink_workspace_refuses(self):
        self.workspace.symlink_to(self.root, target_is_directory=True)
        result, _ = self.call("catalog")
        self.assertFalse(result["ok"])

    def test_sample_is_isolated_and_does_not_rewrite_unknown_metadata(self):
        base = self.sample()
        self.assertEqual(base.parent.name, "SampleReaders")
        run = self.workspace / "runs/sample-2024-01/run.json"
        data = json.loads(run.read_text())
        data["futureField"] = {"preserve": [1, 2, 3]}
        run.write_text(json.dumps(data))
        before = run.read_bytes()
        result, _ = self.call("catalog")
        self.assertTrue(result["ok"])
        self.assertEqual(run.read_bytes(), before)
        self.assertEqual(len(result["data"]["runs"]), 3)
        self.assertEqual(os.stat(base).st_mode & 0o777, 0o700)

    def test_synthetic_marker_and_location_are_required(self):
        base = self.sample()
        (base / ".bridge-demo.json").write_text('{"synthetic":false}')
        result, _ = self.call("execute", config=self.config(), fixture=base)
        self.assertFalse(result["ok"])

    @unittest.skipUnless(platform.system() == "Darwin", "Actual ditto fixture runs on macOS.")
    def test_actual_core_preview_full_restore_reuse_cancel_and_cleanup(self):
        base = self.sample()
        source_before, target_before = self.tree(base / "Source"), self.tree(base / "Target")
        result, _ = self.call("execute", config=self.config(), fixture=base)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["exitCode"], 0, result)
        self.assertEqual(self.tree(base / "Source"), source_before)
        self.assertEqual(self.tree(base / "Target"), target_before)
        self.assertFalse(list(self.workspace.rglob("*.zip")))
        result, events = self.call("execute", config=self.config(dry=False), fixture=base)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["exitCode"], 0, events[-8:])
        self.assertEqual((base / "Source/Books/Example.epub").read_bytes(), (base / "Target/Books/Example.epub").read_bytes())
        self.assertEqual(self.tree(base / "Source"), source_before)
        saved = next(x["id"] for x in result["data"]["runs"] if x["canRestore"] and x["canReuse"])
        result, _ = self.call("execute", config=self.config(dry=False, action="restore", run_id=saved), fixture=base)
        self.assertEqual(result["data"]["exitCode"], 0)
        self.assertEqual(self.tree(base / "Target"), target_before)
        result, _ = self.call("execute", config=self.config(dry=False, action="reuse", run_id=saved), fixture=base)
        self.assertEqual(result["data"]["exitCode"], 0)
        result, _ = self.call("execute", config=self.config(dry=False), fixture=base, decline=True)
        self.assertEqual(result["data"]["exitCode"], 0)
        self.assertTrue(any(x["status"] == "cancelled" for x in result["data"]["runs"]))
        config = self.config(dry=False, action="delete", run_id="sample-2024-01")
        result, _ = self.call("execute", config=config, fixture=base, confirmation="wrong")
        self.assertEqual(result["data"]["exitCode"], 0)
        self.assertTrue((self.workspace / "runs/sample-2024-01").exists())
        result, _ = self.call("execute", config=config, fixture=base)
        self.assertEqual(result["data"]["exitCode"], 0)
        self.assertFalse((self.workspace / "runs/sample-2024-01").exists())
        self.assertTrue((self.workspace / "runs" / saved).exists())

    def test_runtime_archive_rejects_escape(self):
        path = self.root / "bad.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            info = tarfile.TarInfo("../escape")
            archive.addfile(info)
        with self.assertRaises(ValueError):
            build_macos_app.safe_extract(path, self.root / "extract")

    def test_public_screenshot_allowlist_rejects_text_metadata_and_other_images(self):
        def chunk(kind, payload):
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
        header = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 100, 100, 8, 2, 0, 0, 0))
        image = header + chunk(b"IDAT", zlib.compress(b"\0" + b"\0" * 300)) + chunk(b"IEND", b"")
        self.assertEqual(check_publication.inspect_blob("assets/desktop/migration-light.png", image), [])
        private = header + chunk(b"tEXt", b"private path") + chunk(b"IEND", b"")
        self.assertTrue(check_publication.inspect_blob("assets/desktop/migration-light.png", private))
        self.assertTrue(check_publication.inspect_blob("assets/desktop/arbitrary.png", image))
        self.assertTrue(check_publication.inspect_blob("assets/desktop/migration-light.png", image + b"extra"))
