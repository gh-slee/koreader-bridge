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

    def call(self, operation, config=None, fixture=None, run_id=None, decline=False, confirmation=None,
             on_prompt=None, decline_model=False, **extra):
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
                    if on_prompt is not None:
                        on_prompt(packet)
                    if packet["kind"] == "boolean":
                        answer = "n" if (decline and packet["key"] == "confirm.migration") or (decline_model and not packet["key"]) else "y"
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

    def bound_config(self, base, dry=True):
        session = "synthetic-reader-session-integration-1234"
        result, _ = self.call("devices", fixture=base, readerSession=session)
        self.assertTrue(result["ok"], result)
        rows = result["data"]["readers"]
        by_volume = {row["volume"]: row for row in rows}
        config = self.config(dry=dry)
        config["readers"] = {role: {"id": by_volume[name]["id"], "model": by_volume[name]["model"] or "Kobo Sample"}
                             for role, name in [("source", "Source"), ("target", "Target")]}
        return config, session, rows

    def test_bound_discovery_returns_two_physical_choices_without_raw_identity(self):
        base = self.sample(); before = self.tree(base)
        config, session, rows = self.bound_config(base)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["model"] for r in rows}, {"Kobo Libra 2", "Kobo Clara 2E"})
        self.assertTrue(all(r["usbVerified"] and r["selectable"] for r in rows))
        self.assertNotIn("SOURCE-SAMPLE", json.dumps(rows))
        self.assertNotIn("Example.epub", json.dumps(rows))
        self.assertEqual(self.tree(base), before)
        result, _ = self.call("devices", fixture=base, readerSession="bad")
        self.assertFalse(result["ok"])

    @unittest.skipUnless(platform.system() == "Darwin", "Bound workflow uses macOS ditto on isolated readers.")
    def test_bound_dual_reader_preview_transfer_restore_and_saved_source(self):
        base = self.sample(); config, session, _ = self.bound_config(base)
        source, target = base / "Attached/Source", base / "Attached/Target"
        before_source, before_target = self.tree(source), self.tree(target)
        result, events = self.call("execute", config=config, fixture=base, readerSession=session)
        self.assertEqual(result["data"]["exitCode"], 0, result)
        self.assertEqual(self.tree(target), before_target)
        self.assertFalse(any(e.get("key") in {"prompt.source", "prompt.target"} for e in events))
        config["dryRun"] = False
        result, _ = self.call("execute", config=config, fixture=base, readerSession=session)
        self.assertEqual(result["data"]["exitCode"], 0, result)
        saved = result["data"]["runID"]
        self.assertTrue((target / "Books/Example.epub").is_file())
        self.assertTrue((target / "Books/Keep.txt").is_file())
        self.assertEqual(self.tree(source), before_source)
        for action in ["restore", "reuse"]:
            follow = dict(config, action=action, runID=saved, readers={"target": config["readers"]["target"]})
            result, _ = self.call("execute", config=follow, fixture=base, readerSession=session)
            self.assertEqual(result["data"]["exitCode"], 0, result)
            if action == "restore": self.assertEqual(self.tree(target), before_target)

    def test_bound_roles_refuse_same_stale_or_missing_connections_without_target_writes(self):
        base = self.sample(); config, session, _ = self.bound_config(base)
        before = self.tree(base / "Attached/Target")
        config["readers"]["target"] = config["readers"]["source"]
        result, _ = self.call("execute", config=config, fixture=base, readerSession=session)
        self.assertFalse(result["ok"])
        config, session, _ = self.bound_config(base)
        usb = base / ".bridge-usb.json"; rows = json.loads(usb.read_text()); rows[1]["registry"] += 1; usb.write_text(json.dumps(rows))
        result, _ = self.call("execute", config=config, fixture=base, readerSession=session)
        self.assertFalse(result["ok"])
        self.assertEqual(self.tree(base / "Attached/Target"), before)

    @unittest.skipUnless(platform.system() == "Darwin", "Bound correction uses core macOS preview.")
    def test_model_override_and_unknown_code_require_default_no_confirmation(self):
        base = self.sample(); config, session, _ = self.bound_config(base)
        config["readers"]["source"]["model"] = "Kobo Clara 2E"
        before = self.tree(base / "Attached/Target")
        result, events = self.call("execute", config=config, fixture=base, readerSession=session, decline_model=True)
        self.assertEqual(result["data"]["status"], "cancelled", result)
        self.assertTrue(any(e.get("kind") == "boolean" and "overrides" in e.get("text", "") for e in events))
        self.assertEqual(self.tree(base / "Attached/Target"), before)
        version = base / "Attached/Source/.kobo/version"
        version.write_text(version.read_text().replace("000000000388", "000000000999"))
        config, session, _ = self.bound_config(base)
        result, events = self.call("execute", config=config, fixture=base, readerSession=session)
        self.assertEqual(result["data"]["exitCode"], 0, result)
        self.assertTrue(any("native model code is unknown" in e.get("text", "") for e in events))

    @unittest.skipUnless(platform.system() == "Darwin", "Write-boundary regression uses core macOS backups.")
    def test_usb_connection_replacement_at_final_confirmation_blocks_writes(self):
        base = self.sample(); config, session, _ = self.bound_config(base, dry=False)
        before = self.tree(base / "Attached/Target")
        def replace(packet):
            if packet.get("key") == "confirm.migration":
                p = base / ".bridge-usb.json"; rows = json.loads(p.read_text()); rows[1]["registry"] += 1; p.write_text(json.dumps(rows))
        result, events = self.call("execute", config=config, fixture=base, readerSession=session, on_prompt=replace)
        self.assertNotEqual(result["data"]["exitCode"], 0, result)
        self.assertEqual(self.tree(base / "Attached/Target"), before)
        self.assertTrue(any("USB connection changed" in e.get("text", "") for e in events))

    def tree(self, path):
        return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in path.rglob("*") if p.is_file() and not p.is_symlink()}

    def reviewed(self, config, **changes):
        config["review"] = {"rolesConfirmed": True, "compatible": True, "identity": "preserve", "cloneConfirmed": False}
        config["review"].update(changes)
        return config

    def test_review_requires_bound_roles_and_typed_request_scoped_choices(self):
        base = self.sample(); config, session, _ = self.bound_config(base, dry=False)
        before = self.tree(base / "Attached/Target")
        for changes in [{"rolesConfirmed": False}, {"rolesConfirmed": 1}, {"compatible": False},
                        {"identity": []}, {"identity": "yes-all"}, {"identity": "clone"}, {"extra": True}]:
            with self.subTest(changes=changes):
                self.reviewed(config, **changes)
                result, events = self.call("execute", config=config, fixture=base, readerSession=session)
                self.assertFalse(result["ok"], result)
                self.assertFalse(any(e["event"] == "prompt" for e in events))
                self.assertEqual(self.tree(base / "Attached/Target"), before)
        config.pop("readers"); self.reviewed(config)
        result, _ = self.call("execute", config=config, fixture=base, readerSession=session)
        self.assertFalse(result["ok"])

    @unittest.skipUnless(platform.system() == "Darwin", "Reviewed transfer uses macOS ditto on isolated readers.")
    def test_reviewed_transfer_has_one_final_prompt_and_retains_backups_on_decline(self):
        base = self.sample(); config, session, _ = self.bound_config(base, dry=False)
        self.reviewed(config); before = self.tree(base / "Attached/Target")
        result, events = self.call("execute", config=config, fixture=base, readerSession=session, decline=True)
        self.assertEqual(result["data"]["status"], "cancelled", result)
        prompts = [e for e in events if e["event"] == "prompt"]
        self.assertEqual([e["key"] for e in prompts], ["confirm.migration"])
        self.assertEqual(prompts[0]["kind"], "boolean")
        self.assertEqual(self.tree(base / "Attached/Target"), before)
        self.assertTrue(list(self.workspace.rglob("*.zip")))
        result, events = self.call("execute", config=config, fixture=base, readerSession=session)
        self.assertEqual(result["data"]["status"], "success", result)
        self.assertEqual([e["key"] for e in events if e["event"] == "prompt"], ["confirm.migration"])
        config.pop("review"); config["dryRun"] = True
        _, events = self.call("execute", config=config, fixture=base, readerSession=session)
        self.assertTrue(any(e.get("key") == "confirm.continue" for e in events))

    @unittest.skipUnless(platform.system() == "Darwin", "Reviewed preview enters the macOS-only core workflow.")
    def test_reviewed_readonly_preview_needs_no_compatibility_or_write_prompt(self):
        base = self.sample(); config, session, _ = self.bound_config(base)
        self.reviewed(config, compatible=False); before = self.tree(base / "Attached/Target")
        result, events = self.call("execute", config=config, fixture=base, readerSession=session)
        self.assertEqual(result["data"]["exitCode"], 0, result)
        self.assertFalse(any(e["event"] == "prompt" for e in events))
        self.assertEqual(self.tree(base / "Attached/Target"), before)

    @unittest.skipIf(platform.system() == "Darwin", "Exercises the unsupported-host guard.")
    def test_reviewed_preview_on_unsupported_host_refuses_without_reader_changes(self):
        base = self.sample(); config, session, _ = self.bound_config(base)
        self.reviewed(config, compatible=False)
        before = self.tree(base / "Attached")
        result, events = self.call("execute", config=config, fixture=base, readerSession=session)
        self.assertNotEqual(result["data"]["exitCode"], 0, result)
        self.assertIsNone(result["data"]["runID"])
        self.assertFalse(any(e["event"] == "prompt" for e in events))
        self.assertTrue(any("macOS" in e.get("text", "") for e in events))
        self.assertEqual(self.tree(base / "Attached"), before)

    @unittest.skipUnless(platform.system() == "Darwin", "Saved-source review uses isolated macOS archives.")
    def test_reviewed_saved_source_reuses_only_target_choice_and_keeps_final_consent(self):
        base = self.sample(); config, session, _ = self.bound_config(base, dry=False)
        self.reviewed(config)
        result, _ = self.call("execute", config=config, fixture=base, readerSession=session)
        self.assertEqual(result["data"]["status"], "success", result)
        saved = result["data"]["runID"]
        config["action"] = "reuse"; config["runID"] = saved; config["readers"].pop("source")
        config["sourceModel"] = "Kobo Unrelated Label"
        before = self.tree(base / "Attached/Target")
        result, events = self.call("execute", config=config, fixture=base, readerSession=session, decline=True)
        self.assertEqual(result["data"]["status"], "cancelled", result)
        self.assertEqual([e["key"] for e in events if e["event"] == "prompt"], ["confirm.migration"])
        self.assertEqual(self.tree(base / "Attached/Target"), before)
        config["dryRun"] = True
        result, events = self.call("execute", config=config, fixture=base, readerSession=session)
        self.assertEqual(result["data"]["exitCode"], 0, result)
        self.assertFalse(any(e["event"] == "prompt" for e in events))

    def test_structured_cleanup_reasons_and_duplicate_identity_warning_remain_available(self):
        base = self.sample()
        result, _ = self.call("catalog", fixture=base)
        protected = [r for r in result["data"]["runs"] if r["protection"]]
        self.assertTrue(protected)
        self.assertTrue(all(r["protectionKey"].startswith("cleanup.reason_") for r in protected))
        path = base / "Attached/Target/.kobo/version"
        path.write_text(path.read_text().replace("TARGET-SAMPLE", "SOURCE-SAMPLE"))
        result, _ = self.call("devices", fixture=base, readerSession="synthetic-warning-session-integration-1234")
        self.assertTrue(all(not r["selectable"] and r["warningCodes"] == ["duplicate_identity"] for r in result["data"]["readers"]))

    @unittest.skipUnless(platform.system() == "Darwin", "Model confirmation enters the macOS-only core workflow.")
    def test_review_cannot_suppress_manual_model_warning(self):
        base = self.sample(); config, session, _ = self.bound_config(base)
        self.reviewed(config); config["readers"]["source"]["model"] = "Kobo Clara 2E"
        result, events = self.call("execute", config=config, fixture=base, readerSession=session, decline_model=True)
        self.assertEqual(result["data"]["status"], "cancelled", result)
        warning = next(e for e in events if e["event"] == "prompt")
        self.assertEqual(warning["messageKey"], "prompt.model_correction")
        self.assertEqual(warning["values"]["role"], "source")

    @unittest.skipUnless(platform.system() == "Darwin", "Write-boundary regression uses core macOS backups.")
    def test_review_does_not_bypass_revalidation_at_final_write_boundary(self):
        base = self.sample(); config, session, _ = self.bound_config(base, dry=False)
        self.reviewed(config); before = self.tree(base / "Attached/Target")
        def replace(packet):
            if packet.get("key") == "confirm.migration":
                path = base / ".bridge-usb.json"; rows = json.loads(path.read_text()); rows[1]["registry"] += 1; path.write_text(json.dumps(rows))
        result, _ = self.call("execute", config=config, fixture=base, readerSession=session, on_prompt=replace)
        self.assertNotEqual(result["data"]["exitCode"], 0, result)
        self.assertEqual(self.tree(base / "Attached/Target"), before)

    @unittest.skipUnless(platform.system() == "Darwin", "Identity choices use isolated macOS runtime copies.")
    def test_reviewed_identity_choices_and_missing_target_fallback(self):
        for identity in ["preserve", "new", "clone", "missing"]:
            with self.subTest(identity=identity):
                base = self.sample(); config, session, _ = self.bound_config(base, dry=False)
                config["mode"] = "koreader"
                self.reviewed(config, identity=identity if identity != "missing" else "preserve", cloneConfirmed=identity == "clone")
                settings = base / "Attached/Target/.adds/koreader/settings.reader.lua"
                if identity == "missing":
                    settings.write_text('return {}\n')
                before = settings.read_text()
                result, _ = self.call("execute", config=config, fixture=base, readerSession=session)
                self.assertEqual(result["data"]["status"], "success", result)
                after = settings.read_text()
                if identity == "preserve": self.assertEqual(after, before)
                elif identity == "clone": self.assertEqual(after, (base / "Attached/Source/.adds/koreader/settings.reader.lua").read_text())
                else: self.assertNotEqual(after, before)

    def test_health_is_offline_versioned_and_has_no_workspace_writes(self):
        result, events = self.call("health")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["protocolVersion"], 1)
        self.assertEqual(events, [])
        self.assertFalse(self.workspace.exists())

    def test_connected_preview_is_read_only_and_never_exposes_identity_or_books(self):
        base = self.sample()
        reader = base / "Connected/Reader"
        (reader / ".kobo/version").write_text("SYNTHETIC-PRIVATE-IDENTITY")
        (reader / "Books").mkdir()
        (reader / "Books/private-title.epub").write_text("SYNTHETIC BOOK CONTENT")
        before = self.tree(base)
        result, events = self.call("devices", fixture=base)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"], {"count": 1, "modelHint": "Kobo Sample Source", "status": "connected", "synthetic": True})
        self.assertEqual(events, [])
        self.assertNotIn("SYNTHETIC-PRIVATE-IDENTITY", json.dumps(result))
        self.assertNotIn("private-title", json.dumps(result))
        self.assertEqual(self.tree(base), before)

    def test_connected_preview_empty_multiple_unknown_and_symlink_states(self):
        base = self.sample()
        reader = base / "Connected/Reader"
        log = reader / ".adds/koreader/crash.log"
        log.unlink()
        result, _ = self.call("devices", fixture=base)
        self.assertEqual(result["data"]["status"], "unknown")
        outside = self.root / "outside.log"
        outside.write_text("Detected a Kobo Private Outside (test)")
        log.symlink_to(outside)
        result, _ = self.call("devices", fixture=base)
        self.assertEqual(result["data"]["status"], "unavailable")
        log.unlink()
        (base / "Connected/Other/.kobo").mkdir(parents=True)
        result, _ = self.call("devices", fixture=base)
        self.assertEqual(result["data"]["status"], "multiple")
        self.assertIsNone(result["data"]["modelHint"])
        (base / "Connected/Other/.kobo").rmdir()
        (reader / ".kobo").rmdir()
        result, _ = self.call("devices", fixture=base)
        self.assertEqual(result["data"]["status"], "none")

    @unittest.skipUnless(platform.system() == "Darwin", "Actual reader preview uses macOS tools.")
    def test_empty_model_choices_use_core_hints_and_still_confirm_roles(self):
        base = self.sample()
        before = self.tree(base / "Target")
        config = self.config()
        config["sourceModel"] = config["targetModel"] = ""
        result, events = self.call("execute", config=config, fixture=base)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["exitCode"], 0)
        self.assertEqual(sum(e.get("key") == "prompt.physical_model" for e in events), 2)
        self.assertEqual(sum(e.get("key") == "confirm.device" for e in events), 2)
        self.assertEqual(self.tree(base / "Target"), before)

    def test_connected_preview_rejects_unmarked_or_escaped_sample(self):
        base = self.sample()
        (base / ".bridge-demo.json").unlink()
        result, _ = self.call("devices", fixture=base)
        self.assertFalse(result["ok"])
        result, _ = self.call("devices", fixture=self.root)
        self.assertFalse(result["ok"])

    def test_unknown_version_operation_and_field_refuse(self):
        for values in [{"version": 99}, {"operation": "shell"}, {"unexpected": "ignored?"}]:
            with self.subTest(values=values):
                result, _ = self.call("health", **values) if "operation" not in values else self.call(values["operation"])
                self.assertFalse(result["ok"])
                self.assertFalse(self.workspace.exists())

    def test_bad_scopes_ids_and_volume_workspace_refuse(self):
        for op, values in [("details", {"runID": "../outside"}), ("catalog", {"workspace": "/Volumes/Example"}),
                           ("execute", {"config": {"command": "arbitrary"}}), ("catalog", {"keepSuccessful": 0}), ("execute", {"keepSuccessful": 0})]:
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
        result, events = self.call("execute", config=self.config(), fixture=base)
        self.assertTrue(result["ok"], result)
        self.assertEqual([(e["role"], e["model"]) for e in events if e["event"] == "device"],
                         [("source", "Kobo Sample Source"), ("target", "Kobo Sample Target")])
        self.assertEqual(result["data"]["exitCode"], 0, result)
        refreshed, _ = self.call("catalog")
        self.assertEqual(result["data"]["reclaimableBytes"], refreshed["data"]["reclaimableBytes"])
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

    def test_cleanup_uses_the_same_retention_as_its_preview(self):
        base = self.sample()
        preview, _ = self.call("catalog", keepSuccessful=1)
        selected = next(row for row in preview["data"]["runs"] if row["id"] == "sample-2024-02")
        self.assertTrue(selected["eligible"])
        result, _ = self.call("execute", config=self.config(dry=False, action="delete", run_id=selected["id"]),
                              fixture=base, keepSuccessful=1)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["exitCode"], 0)
        self.assertFalse((self.workspace / "runs" / selected["id"]).exists())
        current, _ = self.call("catalog", keepSuccessful=1)
        self.assertEqual(result["data"]["reclaimableBytes"], current["data"]["reclaimableBytes"])

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
