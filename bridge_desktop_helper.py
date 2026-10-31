#!/usr/bin/env python3
"""Version 1 desktop protocol adapter. Migration policy remains in the CLI core."""
from __future__ import annotations
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import select
import signal
import sys
import threading
import time
import uuid
import zipfile
import shutil

VERSION = 1
MAX_INPUT = 65536
MAX_OUTPUT = 524288
ROOT = Path(__file__).resolve().parent
WIRE = sys.stdout
WRITE_LOCK = threading.Lock()
REQUEST_ID = ""
INPUT_BUFFER = b""
LAST_LINES = []


class ProtocolError(ValueError):
    pass


def sanitize(text):
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", str(text))
    text = "".join(c for c in text if c in "\n\t" or ord(c) >= 32)
    text = re.sub(r"(?i)((?:api[_ -]?key|access[_ -]?token|password|secret)\s*[:=]\s*)[^\s,;]+", r"\1[redacted]", text)
    text = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{16,})\b", "[redacted]", text)
    return text[:4096]


def emit(event, **fields):
    packet = {"version": VERSION, "id": REQUEST_ID, "event": event, **fields}
    data = json.dumps(packet, ensure_ascii=False, allow_nan=False)
    if len(data.encode()) > MAX_OUTPUT:
        raise ProtocolError("Response exceeds the protocol limit.")
    with WRITE_LOCK:
        WIRE.write(data + "\n")
        WIRE.flush()


def object_unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ProtocolError("Duplicate JSON field.")
        obj[key] = value
    return obj


def read_packet(timeout=30):
    global INPUT_BUFFER
    deadline = time.monotonic() + timeout
    while b"\n" not in INPUT_BUFFER:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([sys.stdin], [], [], remaining)[0]:
            raise ProtocolError("Request timed out.")
        chunk = os.read(sys.stdin.fileno(), 4096)
        if not chunk:
            raise ProtocolError("The application disconnected.")
        INPUT_BUFFER += chunk
        if len(INPUT_BUFFER) > MAX_INPUT:
            raise ProtocolError("Oversized protocol request.")
    line, INPUT_BUFFER = INPUT_BUFFER.split(b"\n", 1)
    if not line or len(line) > MAX_INPUT:
        raise ProtocolError("Missing or oversized protocol request.")
    try:
        value = json.loads(line, object_pairs_hook=object_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError("Invalid number.")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Malformed protocol request.") from exc
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != VERSION:
        raise ProtocolError("Unsupported protocol version.")
    if not isinstance(value.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", value["id"]):
        raise ProtocolError("Invalid request identifier.")
    return value


def engine():
    spec = importlib.util.spec_from_file_location("_bridge_desktop_core", ROOT / "kobo-koreader-migrate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def device_module():
    name = "_bridge_reader_devices"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "bridge_devices.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def reader_inventory(m, request):
    devices = device_module()
    key = devices.session_key(request.get("readerSession"))
    fixture = request.get("fixtureRoot")
    if fixture is None:
        return devices.discover(m.kobo_mounts(), key)
    base = sample_base(fixture, workspace(request.get("workspace")))
    # Fixtures have their own storage/USB graph. Never call host discovery here.
    attached = base / "Attached"
    if attached.is_symlink() or not attached.is_dir():
        raise ProtocolError("Invalid sample reader connections.")
    records = bounded_json(base / ".bridge-usb.json")
    if not isinstance(records, list) or len(records) > 32:
        raise ProtocolError("Invalid sample USB metadata.")
    result = []
    mounts = sorted(attached.iterdir())
    if len(mounts) > 32:
        raise ProtocolError("Too many sample reader connections.")
    for mount in mounts:
        if mount.is_symlink() or not mount.is_dir() or not (mount / ".kobo").is_dir():
            continue
        usb = []
        for entry in records:
            if not isinstance(entry, dict) or set(entry) != {"volume", "serial", "product", "registry"}:
                raise ProtocolError("Invalid sample USB record.")
            if entry["volume"] == mount.name:
                usb.append({"registry": entry["registry"], "serial": entry["serial"],
                            "product": entry["product"], "devices": [mount.stat().st_dev]})
        rows = devices.discover([mount], key, usb=usb)
        for snapshot in rows:
            # Display capacities are synthetic too; never publish host free space.
            snapshot["public"]["freeBytes"] = (12 if mount.name == "Source" else 8) * 1024 ** 3
            snapshot["public"]["totalBytes"] = (32 if mount.name == "Source" else 16) * 1024 ** 3
        result.extend(rows)
    serials = [s["state"]["identity"]["serial"] for s in result]
    for snapshot, serial in zip(result, serials):
        if serial and serials.count(serial) > 1:
            snapshot["public"]["selectable"] = False
            snapshot["public"]["warningCodes"] = ["duplicate_identity"]
            snapshot["public"]["warning"] = "Two sample volumes have the same identity."
    return result


def workspace(value, create=False):
    if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
        raise ProtocolError("Choose a valid backup folder.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ProtocolError("Backup folders must be absolute paths.")
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ProtocolError("Symbolic-link backup folders are not supported.")
    resolved = path.resolve()
    if resolved == Path("/") or Path("/Volumes") == resolved or Path("/Volumes") in resolved.parents:
        raise ProtocolError("Backups must be on the Mac, outside reader volumes.")
    if any(part.suffix == ".app" for part in [resolved, *resolved.parents]):
        raise ProtocolError("Choose a backup folder outside the application.")
    if path.exists() and (not path.is_dir() or path.stat().st_uid != os.getuid()):
        raise ProtocolError("The backup folder must be owned by the current user.")
    if (path / "runs").is_symlink():
        raise ProtocolError("The batch folder cannot be a symbolic link.")
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def run_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) or ".." in value:
        raise ProtocolError("Invalid batch identifier.")
    return value


def bounded_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_OUTPUT:
        raise ProtocolError("The selected report is unavailable or too large.")
    return json.loads(path.read_text(), object_pairs_hook=object_unique)


def catalog(m, project, keep=2):
    plan = m.cleanup_plan(project, keep)
    eligible = {x["run_id"] for x in plan["candidates"]}
    protected = {x["run_id"]: x["reason"] for x in plan["protected"]}
    records = []
    for row in m.run_catalog(project)[-500:]:
        ident = row["run_id"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", ident) or ".." in ident:
            continue
        folder = project / "runs" / ident
        records.append({"id": ident, "status": row["status"], "operation": row["operation"],
                        "bytes": row["bytes"], "endedAt": row.get("ended_at") or "",
                        "targetModified": bool(row.get("target_modified")), "eligible": ident in eligible,
                        "protection": sanitize(protected.get(ident, "")),
                        "protectionKey": getattr(protected.get(ident), "key", None),
                        "canReuse": (folder / "source-snapshot.json").is_file(),
                        "canRestore": (folder / "target-snapshot.json").is_file() and (folder / "target-changes.json").is_file()})
    return {"runs": sorted(records, key=lambda x: (x["endedAt"], x["id"]), reverse=True), "reclaimableBytes": plan["reclaimable_bytes"]}


def sample_base(value, project):
    if not isinstance(value, str) or len(value) > 4096 or "\x00" in value:
        raise ProtocolError("Invalid sample session.")
    base = Path(value)
    if base.is_symlink() or base.resolve() != base or project != base / "Workspace" or base.parent.name != "SampleReaders":
        raise ProtocolError("Invalid sample session.")
    marker = bounded_json(base / ".bridge-demo.json")
    if marker != {"schema": 1, "synthetic": True} or base.stat().st_uid != os.getuid():
        raise ProtocolError("Invalid sample marker.")
    for name in ["Source", "Target", "Connected"]:
        if (base / name).is_symlink() or not (base / name).is_dir():
            raise ProtocolError("Sample readers cannot be symbolic links.")
    return base


def connected_readers(m, request):
    """Return bounded read-only connections, retaining the legacy hint-only shape."""
    if "readerSession" in request:
        rows = [snapshot["public"] for snapshot in reader_inventory(m, request)]
        return {"count": len(rows), "modelHint": rows[0]["model"] if len(rows) == 1 else None,
                "status": "connected" if rows else "none", "synthetic": request.get("fixtureRoot") is not None,
                "readers": rows, "models": sorted(set(device_module().MODELS.values()))}
    fixture = request.get("fixtureRoot")
    if fixture is not None:
        project = workspace(request.get("workspace"))
        base = sample_base(fixture, project)
        m.VOLUME_ROOT = base / "Connected"
    mounts = m.kobo_mounts()
    if len(mounts) != 1:
        return {"count": min(len(mounts), 100), "modelHint": None,
                "status": "none" if not mounts else "multiple", "synthetic": fixture is not None}
    mount = mounts[0]
    kr = mount / ".adds" / "koreader"
    for path in (mount / ".adds", kr, kr / "crash.log", kr / "version.log"):
        if path.is_symlink():
            return {"count": 1, "modelHint": None, "status": "unavailable", "synthetic": fixture is not None}
    try:
        hint = m.detect_model(mount)
        if hint is not None:
            hint = sanitize(hint)
            if len(hint) > 80 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._()+-]*", hint):
                hint = None
    except OSError:
        hint = None
    return {"count": 1, "modelHint": hint, "status": "connected" if hint else "unknown",
            "synthetic": fixture is not None}


def demo(project):
    base = project / "SampleReaders" / uuid.uuid4().hex
    base.mkdir(parents=True, mode=0o700)
    (base / ".bridge-demo.json").write_text(json.dumps({"schema": 1, "synthetic": True}))
    for name, role in [("Source", "SOURCE"), ("Target", "TARGET")]:
        mount = base / name
        (mount / ".kobo").mkdir(parents=True)
        code = "388" if role == "SOURCE" else "386"
        (mount / ".kobo/version").write_text(role + "-SAMPLE,1.0,4.0.0,1.0,1.0,00000000-0000-0000-0000-000000000" + code)
        kr = mount / ".adds/koreader"
        (kr / "frontend").mkdir(parents=True)
        (kr / "plugins/sample.koplugin").mkdir(parents=True)
        (kr / "plugins/sample.koplugin/main.lua").write_text("return {}")
        (kr / "plugins/sample.koplugin/_meta.lua").write_text("return {}")
        (kr / "reader.lua").write_text("return {}")
        (kr / "frontend/reader.lua").write_text("return {}")
        (kr / "settings.reader.lua").write_text('return { ["device_id"] = "SAMPLE-' + role + '" }')
        (kr / "history.lua").write_text("return {}")
        (kr / "crash.log").write_text("Detected a Kobo Sample " + role.title() + " (synthetic)\n")
        (kr / "git-rev").write_text("sample-runtime")
        (mount / "Books").mkdir()
    with zipfile.ZipFile(base / "Source/Books/Example.epub", "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", "<container/>")
        z.writestr("chapter.xhtml", "<html><body>Synthetic sample book</body></html>")
    (base / "Target/Books/Keep.txt").write_text("Synthetic target-only content")
    preview = base / "Connected" / "Reader"
    (preview / ".kobo").mkdir(parents=True)
    (preview / ".adds/koreader").mkdir(parents=True)
    (preview / ".adds/koreader/crash.log").write_text("Detected a Kobo Sample Source (synthetic)\n")
    attached = base / "Attached"
    attached.mkdir()
    for name in ["Source", "Target"]:
        shutil.copytree(base / name, attached / name)
    (base / ".bridge-usb.json").write_text(json.dumps([
        {"volume": "Source", "serial": "SOURCE-SAMPLE", "product": 0x4234, "registry": 1},
        {"volume": "Target", "serial": "TARGET-SAMPLE", "product": 0x4235, "registry": 2}]))
    output = base / "Workspace"
    for index in range(1, 4):
        folder = output / "runs" / ("sample-2024-0" + str(index))
        folder.mkdir(parents=True)
        (folder / "run.json").write_text(json.dumps({"run_id": folder.name, "status": "success",
            "operation": "sample", "ended_at": "2024-01-0" + str(index) + "T00:00:00+00:00",
            "dependencies": [], "target_modified": False}))
        (folder / "sample.txt").write_text("Synthetic batch. No reader data.")
    return {"fixtureRoot": str(base), "workspace": str(output)}


class EventStream(io.TextIOBase):
    def __init__(self):
        self.buffered = ""
    def write(self, text):
        self.buffered += str(text).replace("\r", "\n")
        while "\n" in self.buffered:
            line, self.buffered = self.buffered.split("\n", 1)
            if line.strip():
                line = sanitize(line)
                LAST_LINES.append(line)
                del LAST_LINES[:-12]
                emit("log", text=line)
        if len(self.buffered) > 4096:
            self.flush()
        return len(text)
    def flush(self):
        if self.buffered:
            text, self.buffered = self.buffered, ""
            emit("log", text=sanitize(text))


def execute(m, request, project):
    config = request.get("config", {})
    allowed = {"action", "mode", "dryRun", "sourceModel", "targetModel", "locale", "books",
               "fonts", "readingData", "conflict", "runID", "includeDirs", "excludeDirs", "extensions", "readers", "review"}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ProtocolError("Unsupported workflow option.")
    action = config.get("action", "migration")
    if action not in {"migration", "reuse", "restore", "delete"}:
        raise ProtocolError("Unsupported workflow.")
    mode = config.get("mode", "koreader")
    if mode not in {"full", "koreader", "library", "audit"}:
        raise ProtocolError("Unsupported migration mode.")
    locale = config.get("locale", "en")
    if locale not in {"en", "zh-Hant", "zh-Hans"}:
        raise ProtocolError("Unsupported language.")
    dry = config.get("dryRun", True)
    if type(dry) is not bool:
        raise ProtocolError("Preview must be a boolean.")
    bindings = None
    if "readers" in config and config["readers"] is not None:
        required = {"source", "target"} if action == "migration" else {"target"}
        if action == "delete" or not isinstance(config["readers"], dict) or set(config["readers"]) != required:
            raise ProtocolError("Choose each required reader role before continuing.")
        bindings = device_module().Bindings(config["readers"], lambda: reader_inventory(m, request))
        config = dict(config)
        for role, (_, model) in bindings.roles.items():
            config[role + "Model"] = model
        if action == "reuse":
            config["sourceModel"] = ""  # The verified saved source defines this role.
    review = config.get("review")
    readonly = dry or mode == "audit"
    if review is not None:
        if not bindings or action not in {"migration", "reuse"}:
            raise ProtocolError("Simplified review requires explicitly bound migration readers.")
        if (not isinstance(review, dict) or set(review) != {"rolesConfirmed", "compatible", "identity", "cloneConfirmed"}
                or any(type(review[k]) is not bool for k in ["rolesConfirmed", "compatible", "cloneConfirmed"])
                or review["rolesConfirmed"] is not True or not isinstance(review["identity"], str)
                or review["identity"] not in {"preserve", "new", "clone"}):
            raise ProtocolError("Review the exact reader roles and migration choices before continuing.")
        if mode in {"full", "koreader"} and not readonly and not review["compatible"]:
            raise ProtocolError("Confirm the source KOReader build is compatible with the target in the review.")
        if review["identity"] == "clone" and not readonly and not review["cloneConfirmed"]:
            raise ProtocolError("Cloning source identity requires an explicit review acknowledgement.")
    args = ["koreader-bridge.py", "--backup-dir", str(project), "--locale", locale]
    if dry:
        args.append("--dry-run")
    if action == "restore":
        args += ["--restore-run", run_id(config.get("runID"))]
    elif action == "delete":
        args += ["--cleanup", "--delete-run", run_id(config.get("runID")),
                 "--keep-successful", str(request.get("keepSuccessful", 2))]
    else:
        args += ["--mode", mode]
        if action == "reuse":
            args += ["--from-run", run_id(config.get("runID"))]
        for key, flag in [("sourceModel", "--source-model"), ("targetModel", "--target-model")]:
            text = config.get(key, "")
            if not isinstance(text, str) or len(text) > 100 or any(c in text for c in "\n\r\x00"):
                raise ProtocolError("Invalid model label.")
            if text:
                args += [flag, text]
        if mode == "library":
            for key, flag in [("books", "books"), ("fonts", "fonts"), ("readingData", "reading-data")]:
                value = config.get(key, True)
                if type(value) is not bool:
                    raise ProtocolError("Library choices must be booleans.")
                args.append("--" + ("" if value else "no-") + flag)
            conflict = config.get("conflict", "overwrite")
            if conflict not in {"overwrite", "keep-target"}:
                raise ProtocolError("Unsupported conflict policy.")
            args += ["--conflict", conflict]
            for key, flag in [("includeDirs", "--include-dir"), ("excludeDirs", "--exclude-dir"), ("extensions", "--extra-extension")]:
                values = config.get(key, [])
                if not isinstance(values, list) or len(values) > 64 or any(not isinstance(s, str) or len(s) > 256 or "\x00" in s for s in values):
                    raise ProtocolError("Invalid library scope.")
                for value in values:
                    args += [flag, value]
    run_root = project / "runs"
    previous_runs = {p.name for p in run_root.iterdir()} if run_root.is_dir() else set()
    stream = EventStream()
    choices = []
    choice_title = ""
    original_choose = m.choose
    def choose(question, options, default=None):
        nonlocal choices, choice_title
        choice_title = sanitize(m.current_ui().text(question))
        choices = [{"value": str(key), "label": sanitize(m.current_ui().text(label))} for key, label in options]
        try:
            return original_choose(question, options, default)
        finally:
            choices = []
    class DesktopPrompt(str):
        def __new__(cls, text, role, model, codes):
            value = str.__new__(cls, text)
            value.native_values = {"role": role, "model": model}
            value.warning_codes = codes
            return value
    def read(ui, prompt, suffix=""):
        key = getattr(prompt, "key", "")
        # Reuse only this request's explicit, immutable review. Never auto-answer
        # final writes, recovery, deletion or unrecognized/exception prompts.
        if review is not None:
            accepted = key in {"confirm.continue", "confirm.saved_source"}
            if key == "confirm.compatibility":
                accepted = readonly or review["compatible"]
            if key == "confirm.device":
                values = getattr(prompt, "values", {})
                role = {"SOURCE": "source", "TARGET": "target"}.get(values.get("role"))
                if role in bindings.roles:
                    snapshot, chosen = checked_role(role)
                    accepted = m.canonical_model(values.get("model")).casefold() == chosen.casefold()
            if accepted:
                emit("log", text="Using this operation's reviewed choice. Identity checks remain active.", messageKey="progress.reviewed")
                return "y"
        ui.write(prompt, end=suffix)
        stream.flush()
        ident = uuid.uuid4().hex
        kind = "choice" if key == "prompt.selection" else "boolean" if "[y/N]" in suffix or "[Y/n]" in suffix else "continue" if key in {"prompt.source", "prompt.target", "prompt.restore_target"} else "text"
        required = "DELETE " + config.get("runID", "") if key == "prompt.confirmation" and action == "delete" else ""
        displayed = choice_title if kind == "choice" else re.sub(r"\s*\[(?:y/N|Y/n)\]:?\s*$", "", ui.text(prompt) + suffix)
        emit("prompt", promptID=ident, key=key, text=sanitize(displayed),
             kind=kind, choices=choices, context=LAST_LINES[-8:], requiredText=required,
             **({"messageKey": "prompt.model_correction", "values": prompt.native_values, "warningCodes": prompt.warning_codes}
                if isinstance(prompt, DesktopPrompt) else {}))
        try:
            reply = read_packet(900)
            if set(reply) != {"version", "id", "operation", "promptID", "text"} or reply["operation"] != "reply" or reply["id"] != REQUEST_ID or reply["promptID"] != ident:
                raise ProtocolError("Reply does not match the pending question.")
            if not isinstance(reply["text"], str) or len(reply["text"]) > 256 or any(c in reply["text"] for c in "\r\n\x00"):
                raise ProtocolError("Invalid confirmation.")
            return reply["text"]
        except ProtocolError:
            raise m.MigrationCancelled("Confirmation expired or the application disconnected.")
        finally:
            if ui.log:
                ui.log.write("\n")
                ui.log.flush()
    original_read = m.UIOutput.read
    m.UIOutput.read, m.choose = read, choose
    fixture = request.get("fixtureRoot")
    if fixture is not None:
        base = sample_base(fixture, project)
        m.VOLUME_ROOT = base / "NeverRealVolumes"
        m.wait_for_single_kobo = lambda role: base / ("Source" if role == "SOURCE" else "Target")
        m.safe_eject = lambda path: emit("log", text="Sample reader disconnected (simulated USB).", messageKey="progress.sample-disconnected")
        original_spinner = m.run_with_spinner
        def fixture_spinner(cmd, label, env=None):
            if not ((cmd[:4] == ["ditto", "-c", "-k", "--keepParent"] and len(cmd) == 6) or (cmd[:3] == ["ditto", "-x", "-k"] and len(cmd) == 5)):
                raise ProtocolError("Unexpected sample subprocess.")
            for path in cmd[-2:]:
                if base not in Path(path).resolve().parents:
                    raise ProtocolError("Sample operation escaped its workspace.")
            return original_spinner(cmd, label, env)
        m.run_with_spinner = fixture_spinner
    if bindings:
        def checked_role(role):
            try:
                return bindings.check(role)
            except device_module().ReaderError as exc:
                raise m.MigrationError(str(exc)) from exc
        def confirm_choice(snapshot, chosen, role):
            row = snapshot["public"]
            warning = row["warning"]
            if not row["model"] or row["model"].casefold() != chosen.casefold():
                warning += " The selected model overrides automatic identification."
            if warning and not m.prompt_yes_no(DesktopPrompt(warning + " Confirm the physical " + role.upper() + " is " + chosen + "?", role, chosen, row.get("warningCodes", [])), default=False):
                raise m.MigrationCancelled("Reader model correction was not confirmed.")
        def check_path(path):
            try:
                bindings.check_path(path)
            except device_module().ReaderError as exc:
                raise m.MigrationError(str(exc)) from exc
        def select(role):
            key = "source" if role == "SOURCE" else "target"
            snapshot, chosen = checked_role(key)
            if role == "RESTORE TARGET":
                confirm_choice(snapshot, chosen, key)
            return snapshot["mount"]
        m.wait_for_single_kobo = select
        original_check, original_eject = m.confirm_device, m.safe_eject
        def confirmed(path, fingerprint):
            check_path(path)
            original_check(path, fingerprint)
        def eject(path):
            check_path(path)
            original_eject(path)
        m.confirm_device, m.safe_eject = confirmed, eject
        original_emit, original_input = m.ui_emit, m.ui_input
        def selected_emit(key, **values):
            if key in {"workflow.disconnect", "workflow.unplug_source", "saved_source.connect"}:
                emit("log", text="Using explicitly selected readers. Keep the target connected until the operation finishes.", messageKey="progress.selected-readers")
            elif key == "device.log_hint":
                emit("log", text="Native model metadata and USB connection were checked. Confirm the physical reader; model labels do not establish identity.", messageKey="progress.identity-checked")
            elif key == "device.model_mismatch":
                emit("log", text="Automatic model identification differs from the chosen physical model. Confirm this correction carefully.", messageKey="progress.model-mismatch")
            else:
                return original_emit(key, **values)
        def selected_input(prompt):
            if getattr(prompt, "key", "") in {"prompt.source", "prompt.target", "prompt.restore_target"}:
                return ""
            return original_input(prompt)
        m.ui_emit, m.ui_input = selected_emit, selected_input
        original_detect = m.detect_model
        def native_model(mount):
            for snapshot, _ in bindings.roles.values():
                if Path(mount) == snapshot["mount"]:
                    check_path(mount)
                    return snapshot["public"]["model"] or original_detect(mount)
            return original_detect(mount)
        m.detect_model = native_model
        if review is not None:
            def reviewed_identity(target_device_id):
                chosen = review["identity"]
                if chosen == "preserve" and not target_device_id:
                    emit("log", text="Target identity is missing; a new KOReader identity will be generated, as reviewed.", messageKey="progress.new-identity")
                    return "new"
                return chosen
            m.choose_identity_mode = reviewed_identity
    original_confirm = m.confirm_role_model
    def confirm_model(info, requested, role):
        if bindings:
            key = "source" if role == "SOURCE" else "target"
            snapshot, chosen = checked_role(key)
            confirm_choice(snapshot, chosen, key)
        confirmed = original_confirm(info, requested, role)
        if role in {"SOURCE", "TARGET"}:
            emit("device", role=role.lower(), model=confirmed)
        return confirmed
    m.confirm_role_model = confirm_model
    old_argv = sys.argv
    timer = threading.Timer(86400, lambda: os.kill(os.getpid(), signal.SIGINT))
    timer.daemon = True
    timer.start()
    try:
        sys.argv = args
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            code = m.cli()
        stream.flush()
        inventory = catalog(m, project, request.get("keepSuccessful", 2))
        rows = inventory["runs"]
        created = [row for row in rows if row["id"] not in previous_runs]
        return {"exitCode": code, "runs": rows, "reclaimableBytes": inventory["reclaimableBytes"], "runID": created[0]["id"] if created else None,
                "status": created[0]["status"] if created else None}
    finally:
        timer.cancel()
        sys.argv = old_argv
        m.UIOutput.read = original_read


def serve():
    global REQUEST_ID
    os.umask(0o077)
    try:
        request = read_packet()
        REQUEST_ID = request["id"]
        if set(request) - {"version", "id", "operation", "workspace", "config", "runID", "keepSuccessful", "fixtureRoot", "readerSession"}:
            raise ProtocolError("Unknown request field.")
        operation = request.get("operation")
        if operation not in {"health", "devices", "catalog", "details", "cleanup_plan", "create_demo", "execute"}:
            raise ProtocolError("Unsupported operation.")
        m = engine()
        if operation == "health":
            result = {"protocolVersion": VERSION, "coreVersion": m.VERSION, "pythonVersion": sys.version.split()[0]}
        elif operation == "devices":
            result = connected_readers(m, request)
        else:
            project = workspace(request.get("workspace"), create=operation in {"create_demo", "execute"})
            if operation in {"catalog", "cleanup_plan"}:
                keep = request.get("keepSuccessful", 2)
                if type(keep) is not int or not 1 <= keep <= 100:
                    raise ProtocolError("Retention must be between 1 and 100.")
                result = catalog(m, project, keep)
            elif operation == "details":
                directory = m.resolve_saved_run(project, run_id(request.get("runID")))
                result = {"run": bounded_json(directory / "run.json"), "summary": {}}
                if (directory / "difference.json").is_file():
                    result["summary"] = bounded_json(directory / "difference.json").get("summary", {})
                # Do not expose device fingerprints or arbitrary raw documents.
                result["run"] = {k: result["run"].get(k) for k in ["run_id", "status", "operation", "mode", "dry_run", "target_modified", "exit_code"]}
            elif operation == "create_demo":
                result = demo(workspace(str(project), create=True))
            else:
                keep = request.get("keepSuccessful", 2)
                if type(keep) is not int or not 1 <= keep <= 100:
                    raise ProtocolError("Retention must be between 1 and 100.")
                result = execute(m, request, project)
        emit("result", ok=True, data=result)
        return 0
    except (ProtocolError, ValueError, OSError) as exc:
        emit("result", ok=False, error={"code": "invalid_request", "message": sanitize(exc)})
        return 1
    except KeyboardInterrupt:
        emit("result", ok=False, error={"code": "cancelled", "message": "Operation interrupted. Retain recovery backups."})
        return 130
    except BaseException:
        emit("result", ok=False, error={"code": "backend_error", "message": "The operation could not finish. Keep recovery data and inspect the batch in Backups."})
        return 1


if __name__ == "__main__":
    raise SystemExit(serve())
