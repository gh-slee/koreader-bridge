"""Read-only Kobo discovery and connection-bound identities for the Mac app.

Model numbers are interoperability facts, independently represented here.
References: calibre/devices/kobo/driver.py and pgaskin/koboutils/kobo/device.go.
No device Lua, shell commands, databases or book files are opened.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from pathlib import Path
import plistlib
import re
import select
import stat
import subprocess
import time

MODELS = {
    310: "Kobo Touch (A or B)", 320: "Kobo Touch C", 330: "Kobo Glo", 340: "Kobo Mini",
    350: "Kobo Aura HD", 360: "Kobo Aura", 370: "Kobo Aura H2O", 371: "Kobo Glo HD",
    372: "Kobo Touch 2.0", 373: "Kobo Aura ONE", 374: "Kobo Aura H2O Edition 2",
    375: "Kobo Aura Edition 2", 376: "Kobo Clara HD", 377: "Kobo Forma",
    378: "Kobo Aura H2O Edition 2", 379: "Kobo Aura Edition 2", 380: "Kobo Forma 32GB",
    381: "Kobo Aura ONE Limited Edition", 382: "Kobo Nia", 383: "Kobo Sage",
    384: "Kobo Libra H2O", 386: "Kobo Clara 2E", 387: "Kobo Elipsa", 388: "Kobo Libra 2",
    389: "Kobo Elipsa 2E", 390: "Kobo Libra Colour", 391: "Kobo Clara BW",
    393: "Kobo Clara Colour", 395: "Kobo Clara BW",
}
# Some newer firmware/devices share 0x4237. Never treat that PID as a unique model.
USB_MODELS = {
    0x4163: {310, 320}, 0x4173: {330}, 0x4183: {340}, 0x4193: {350},
    0x4203: {360}, 0x4213: {370}, 0x4223: {371}, 0x4224: {372},
    0x4225: {373, 381}, 0x4226: {375, 379}, 0x4227: {374, 378},
    0x4228: {376}, 0x4229: {377, 380}, 0x4230: {382}, 0x4231: {383},
    0x4232: {384}, 0x4233: {387}, 0x4234: {388}, 0x4235: {386},
    0x4236: {389}, 0x4237: {390, 391, 393, 395}, 0x4238: {393}, 0x4239: {391, 395},
}


class ReaderError(ValueError):
    pass


def session_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{32,80}", value):
        raise ReaderError("Reader session is missing or invalid. Refresh the reader list.")
    return value.encode("ascii")


def model_name(value):
    if not isinstance(value, str) or len(value) > 100 or any(ord(c) < 32 for c in value):
        raise ReaderError("Choose the physical reader model.")
    value = " ".join(value.split())
    if not value.lower().startswith("kobo "):
        value = "Kobo " + value
    if len(value) > 80 or not re.fullmatch(r"Kobo [A-Za-z0-9][A-Za-z0-9 ._()+-]*", value):
        raise ReaderError("Enter a Kobo model using at most 80 letters, numbers or ordinary punctuation.")
    return value


def read_identity(mount):
    """Open each path component without following links; return private metadata."""
    mount = Path(mount)
    if not mount.is_absolute() or mount.resolve() != mount:
        raise ReaderError("The reader volume cannot be a symbolic link.")
    descriptors = []
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors.append(os.open(mount, directory_flags))
        descriptors.append(os.open(".kobo", directory_flags, dir_fd=descriptors[-1]))
        fd = os.open("version", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptors[-1])
        descriptors.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 65536:
            raise ReaderError("Reader identity metadata is missing or unsafe.")
        raw = os.read(fd, 65537)
        if len(raw) > 65536:
            raise ReaderError("Reader identity metadata is too large.")
        fields = raw.decode("utf-8", errors="strict").strip().split(",")
        if len(fields) != 6 or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", fields[0]):
            raise ReaderError("Reader identity metadata is incomplete. Reconnect using Kobo's USB screen.")
        match = re.fullmatch(r"00000000-0000-0000-0000-([0-9]{12})", fields[5].strip())
        code = int(match[1]) if match else None
        mounted = os.fstat(descriptors[0])
        return {"serial": fields[0], "code": code, "model": MODELS.get(code),
                "fingerprint": hashlib.sha256(raw).hexdigest(),
                "device": mounted.st_dev, "inode": mounted.st_ino}
    except (OSError, UnicodeError) as error:
        raise ReaderError("Reader identity cannot be read safely. Reconnect and refresh.") from error
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def usb_inventory():
    """Bounded, timed IOKit metadata query; this command cannot write to readers."""
    process = subprocess.Popen(["/usr/sbin/ioreg", "-a", "-r", "-c", "IOUSBHostDevice", "-l"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    data = bytearray()
    deadline = time.monotonic() + 10
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                raise ReaderError("USB identification timed out. Refresh readers.")
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > 8 * 1024 * 1024:
                raise ReaderError("USB metadata exceeds the safe discovery limit.")
        if process.wait(timeout=max(0.1, deadline - time.monotonic())):
            raise ReaderError("USB identification is unavailable.")
        return parse_usb(plistlib.loads(data))
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate()  # Only this read-only ioreg process.
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def parse_usb(tree):
    records, seen = [], set()
    visited = 0
    def walk(node, depth=0):
        nonlocal visited
        visited += 1
        if visited > 16384 or depth > 48:
            raise ReaderError("USB metadata exceeds the safe discovery limit.")
        if isinstance(node, list):
            for child in node:
                walk(child, depth + 1)
        elif isinstance(node, dict):
            registry = node.get("IORegistryEntryID")
            if node.get("idVendor") == 0x2237 and type(registry) is int and registry not in seen:
                seen.add(registry)
                disks = []
                def collect(value, level=0):
                    if level > 48 or len(disks) > 128:
                        raise ReaderError("USB storage metadata is too large.")
                    if isinstance(value, list):
                        for child in value:
                            collect(child, level + 1)
                    elif isinstance(value, dict):
                        name = value.get("BSD Name")
                        if isinstance(name, str) and re.fullmatch(r"disk[0-9]+(?:s[0-9]+)*", name):
                            disks.append(name)
                        collect(value.get("IORegistryEntryChildren", []), level + 1)
                collect(node.get("IORegistryEntryChildren", []))
                devices = []
                for name in set(disks):
                    try:
                        metadata = os.stat("/dev/" + name)
                        if stat.S_ISBLK(metadata.st_mode):
                            devices.append(metadata.st_rdev)
                    except OSError:
                        pass
                serial = node.get("USB Serial Number", "")
                if not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", serial):
                    serial = ""
                product = node.get("idProduct")
                records.append({"registry": registry, "serial": serial,
                                "product": product if type(product) is int else None,
                                "devices": sorted(devices)})
            walk(node.get("IORegistryEntryChildren", []), depth + 1)
    walk(tree)
    return records


def discover(mounts, key, usb=None):
    """Return public display rows and private snapshots; never expose raw identity."""
    if len(mounts) > 32:
        raise ReaderError("Too many Kobo volumes are connected. Disconnect unused readers.")
    if not mounts:
        return []
    usb_available = True
    if usb is None:
        try:
            usb = usb_inventory()
        except (OSError, ValueError, subprocess.SubprocessError):
            usb, usb_available = [], False
    snapshots = []
    for index, mount in enumerate(mounts):
        mount = Path(mount)
        warning, fatal = [], False
        try:
            identity = read_identity(mount)
        except ReaderError:
            identity = {"serial": "", "code": None, "model": None, "fingerprint": "",
                        "device": mount.stat().st_dev, "inode": mount.stat().st_ino}
            warning.append("Reader identity cannot be read safely. Reconnect before continuing.")
            fatal = True
        matches = [entry for entry in usb if identity["device"] in entry["devices"]]
        hardware = matches[0] if len(matches) == 1 else None
        usb_model = None
        if len(matches) > 1:
            fatal = True
            warning.append("The USB connection is ambiguous. Reconnect this reader.")
        elif hardware:
            codes = USB_MODELS.get(hardware["product"], set())
            names = {MODELS[c] for c in codes}
            usb_model = next(iter(names)) if len(names) == 1 else None
            if not hardware["serial"] or identity["serial"] != hardware["serial"]:
                fatal = True
                warning.append("USB identity does not match this volume. A model override cannot fix this; reconnect the reader.")
            if identity["code"] in MODELS and codes and identity["code"] not in codes:
                warning.append("The native model code and USB model disagree. Check the physical reader and confirm its model.")
            if not codes:
                warning.append("This USB product code is unknown. Check the physical model.")
        else:
            fatal = True
            warning.append("USB identity could not be cross-checked. Reconnect or use sequential mode; a model correction cannot establish identity.")
        if identity["model"] is None:
            warning.append("The native model code is unknown. Choose and confirm the physical model.")
        # Connection ID and mount device/metadata bind this choice to this insertion.
        state = {"mount": str(mount), "identity": identity, "usb": hardware,
                 "usb_available": usb_available}
        token = hmac.new(key, json.dumps(state, sort_keys=True).encode(), hashlib.sha256).hexdigest()
        try:
            size = os.statvfs(mount)
            free, total = size.f_bavail * size.f_frsize, size.f_blocks * size.f_frsize
        except OSError:
            free = total = 0
        label = "".join(c for c in mount.name if c.isprintable())[:120]
        row = {"id": token, "volume": label or "Reader " + str(index + 1),
               "model": identity["model"] or usb_model, "nativeModel": identity["model"],
               "modelCode": str(identity["code"]) if identity["code"] is not None else None,
               "usbModel": usb_model, "usbVerified": hardware is not None and not fatal,
               "warning": " ".join(warning), "selectable": not fatal,
               "freeBytes": free, "totalBytes": total}
        snapshots.append({"public": row, "mount": mount, "state": state})
    # Cloned native identity is unsafe even when the two filesystem names differ.
    serials = [s["state"]["identity"]["serial"] for s in snapshots]
    for snapshot, serial in zip(snapshots, serials):
        if serial and serials.count(serial) > 1:
            snapshot["public"]["selectable"] = False
            snapshot["public"]["warning"] = "Two volumes have the same reader identity. Reconnect and resolve this before migrating."
    return snapshots


class Bindings:
    """Resolve only discovered tokens; revalidate the original connection each time."""
    def __init__(self, selections, inventory):
        self.inventory = inventory
        self.roles = {}
        if not isinstance(selections, dict) or set(selections) - {"source", "target"}:
            raise ReaderError("Invalid reader roles.")
        snapshots = inventory()
        for role, selection in selections.items():
            if not isinstance(selection, dict) or set(selection) != {"id", "model"}:
                raise ReaderError("Invalid reader choice.")
            token = selection["id"]
            if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token):
                raise ReaderError("Refresh and select the connected reader again.")
            matching = [s for s in snapshots if hmac.compare_digest(s["public"]["id"], token)]
            if len(matching) != 1 or not matching[0]["public"]["selectable"]:
                raise ReaderError("The selected reader changed or disconnected. Refresh and select it again.")
            self.roles[role] = (matching[0], model_name(selection["model"]))
        if len(self.roles) == 2:
            a, b = (self.roles[r][0] for r in ["source", "target"])
            if (a["mount"] == b["mount"] or a["state"]["identity"]["serial"] == b["state"]["identity"]["serial"]
                    or a["state"]["identity"]["device"] == b["state"]["identity"]["device"] and a["state"]["identity"]["inode"] == b["state"]["identity"]["inode"]):
                raise ReaderError("Source and target must be different physical readers.")

    def check(self, role):
        snapshot, model = self.roles[role]
        token = snapshot["public"]["id"]
        current = [s for s in self.inventory() if hmac.compare_digest(s["public"]["id"], token)]
        if len(current) != 1 or not current[0]["public"]["selectable"]:
            raise ReaderError("The selected reader identity or USB connection changed. Stop and select it again.")
        return current[0], model

    def check_path(self, path):
        for role, (snapshot, _) in self.roles.items():
            if Path(path) == snapshot["mount"]:
                self.check(role)
                return
        raise ReaderError("The operation attempted to use an unselected reader.")
