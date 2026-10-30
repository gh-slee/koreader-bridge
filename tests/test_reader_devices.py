"""Connection identity and model corrections use synthetic readers only."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reader_devices_test", ROOT / "bridge_devices.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class ReaderDeviceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.key = d.session_key("synthetic-session-for-reader-tests-1234")

    def reader(self, name="Reader", code=388, serial="SAMPLE-PRIVATE-ONE"):
        path = self.root / name
        (path / ".kobo").mkdir(parents=True)
        (path / ".kobo/version").write_text(serial + ",1.0,4.0,1.0,1.0,00000000-0000-0000-0000-" + str(code).zfill(12))
        return path

    def inventory(self, path, product=0x4234, serial="SAMPLE-PRIVATE-ONE", registry=1):
        usb = [{"serial": serial, "product": product, "registry": registry, "devices": [path.stat().st_dev]}]
        return d.discover([path], self.key, usb=usb)

    def test_native_and_usb_agree_without_exporting_serial_or_fingerprint(self):
        path = self.reader()
        row = self.inventory(path)[0]["public"]
        self.assertEqual(row["model"], "Kobo Libra 2")
        self.assertTrue(row["usbVerified"] and row["selectable"])
        self.assertEqual(row["warning"], "")
        self.assertNotIn("SAMPLE-PRIVATE-ONE", str(row))
        self.assertNotIn(d.read_identity(path)["fingerprint"], str(row))
        self.assertNotEqual(row["id"], d.discover([path], b"other-session", usb=[])[0]["public"]["id"])

    def test_unknown_codes_and_shared_usb_ids_are_not_guessed(self):
        path = self.reader(code=999)
        row = self.inventory(path, product=0x4237)[0]["public"]
        self.assertIsNone(row["model"])
        self.assertIsNone(row["usbModel"])
        self.assertIn("unknown", row["warning"])
        self.assertTrue(row["selectable"])

    def test_conflicting_model_allows_correction_but_serial_mismatch_is_fatal(self):
        path = self.reader(code=386)
        row = self.inventory(path)[0]["public"]
        self.assertIn("disagree", row["warning"])
        self.assertTrue(row["selectable"])
        self.assertEqual(row["nativeModel"], "Kobo Clara 2E")
        bad = self.inventory(path, serial="DIFFERENT-READER")[0]["public"]
        self.assertFalse(bad["selectable"])
        self.assertIn("cannot fix", bad["warning"])

    def test_missing_usb_warns_and_does_not_claim_verified(self):
        path = self.reader()
        row = d.discover([path], self.key, usb=[])[0]["public"]
        self.assertFalse(row["usbVerified"])
        self.assertFalse(row["selectable"])
        self.assertIn("could not be cross-checked", row["warning"])

    def test_usb_unavailable_never_silently_rebinds_existing_selection(self):
        path = self.reader()
        selected = self.inventory(path)[0]["public"]
        binding = d.Bindings({"target": {"id": selected["id"], "model": selected["model"]}}, lambda: self.inventory(path))
        binding.inventory = lambda: d.discover([path], self.key, usb=[])
        with self.assertRaises(d.ReaderError):
            binding.check("target")

    def test_identity_symlinks_fifo_and_oversized_files_are_refused(self):
        path = self.reader()
        version = path / ".kobo/version"
        version.unlink()
        external = self.root / "outside"; external.write_text("PRIVATE")
        version.symlink_to(external)
        with self.assertRaises(d.ReaderError): d.read_identity(path)
        version.unlink(); os.mkfifo(version)
        with self.assertRaises(d.ReaderError): d.read_identity(path)
        version.unlink(); version.write_bytes(b"x" * 65537)
        with self.assertRaises(d.ReaderError): d.read_identity(path)
        row = self.inventory(path)[0]["public"]
        self.assertFalse(row["selectable"])

    def test_connection_or_metadata_change_invalidates_choice(self):
        path = self.reader()
        row = self.inventory(path)[0]["public"]
        binding = d.Bindings({"source": {"id": row["id"], "model": "Kobo Clara 2E"}}, lambda: self.inventory(path))
        self.assertEqual(binding.check("source")[1], "Kobo Clara 2E")
        binding.inventory = lambda: self.inventory(path, registry=2)
        with self.assertRaises(d.ReaderError): binding.check("source")
        binding.inventory = lambda: self.inventory(path)
        (path / ".kobo/version").write_text("REPLACED,1,4,1,1,00000000-0000-0000-0000-000000000388")
        with self.assertRaises(d.ReaderError): binding.check_path(path)

    def test_same_reader_cannot_be_selected_twice_or_arbitrary_paths_passed(self):
        path = self.reader(); row = self.inventory(path)[0]["public"]
        selection = {"id": row["id"], "model": row["model"]}
        with self.assertRaises(d.ReaderError):
            d.Bindings({"source": selection, "target": selection}, lambda: self.inventory(path))
        with self.assertRaises(d.ReaderError):
            d.Bindings({"target": {"id": str(path), "model": row["model"]}}, lambda: self.inventory(path))
        binding = d.Bindings({"target": selection}, lambda: self.inventory(path))
        with self.assertRaises(d.ReaderError): binding.check_path(self.root)

    def test_native_identity_is_not_unique_model_id_and_does_not_execute_files(self):
        path = self.reader()
        (path / ".kobo/evil.lua").write_text("error('must not execute')")
        with patch.object(d, "usb_inventory", side_effect=AssertionError("No USB query without readers")):
            self.assertEqual(d.discover([], self.key), [])
        identity = d.read_identity(path)
        self.assertEqual(identity["code"], 388)
        self.assertEqual(d.model_name("Clara 2E"), "Kobo Clara 2E")
        for invalid in ["", "Clara\n2E", "x" * 1000, 42]:
            with self.assertRaises(d.ReaderError): d.model_name(invalid)

    def test_usb_parser_bounds_and_uses_storage_graph_not_serial_guessing(self):
        node = {"idVendor": 0x2237, "idProduct": 0x4234, "USB Serial Number": "SAMPLE-ONE",
                "IORegistryEntryID": 123, "IORegistryEntryChildren": [{"BSD Name": "../unsafe"}]}
        rows = d.parse_usb([node, node])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["devices"], [])
        tree = []
        for _ in range(60): tree = [tree]
        with self.assertRaises(d.ReaderError): d.parse_usb(tree)

    def test_interface_inherited_usb_ids_do_not_create_duplicate_devices(self):
        interface = {"idVendor": 0x2237, "idProduct": 0x4234, "USB Serial Number": "SAMPLE-ONE",
                     "IORegistryEntryID": 124, "IOObjectClass": "IOUSBHostInterface",
                     "IORegistryEntryChildren": [{"BSD Name": "../unsafe"}]}
        device = {"idVendor": 0x2237, "idProduct": 0x4234, "USB Serial Number": "SAMPLE-ONE",
                  "IORegistryEntryID": 123, "IOObjectClass": "IOUSBHostDevice",
                  "IORegistryEntryChildren": [interface]}
        rows = d.parse_usb([device])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["registry"], 123)


if __name__ == "__main__":
    unittest.main()
