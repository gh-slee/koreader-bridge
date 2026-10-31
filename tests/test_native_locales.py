"""Native catalog parity, safe packaging and typed placeholder regressions."""
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_native_locales as native


class NativeLocaleTests(unittest.TestCase):
    def test_all_catalogs_and_packaged_resources_have_matching_keys(self):
        catalogs = native.load_catalogs()
        self.assertEqual(set(catalogs), {"en", "zh-Hant", "zh-Hans"})
        self.assertEqual(catalogs["zh-Hant"]["Settings"], "設定")
        self.assertEqual(catalogs["zh-Hans"]["Settings"], "设置")
        with tempfile.TemporaryDirectory() as temp:
            native.write_resources(Path(temp))
            for language in native.LOCALES:
                content = (Path(temp) / (language + ".lproj/Localizable.strings")).read_text()
                self.assertIn(json.dumps(catalogs[language]["Settings"], ensure_ascii=False), content)
                self.assertEqual(len(content.splitlines()), len(catalogs[language]))

    def test_duplicate_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"Settings":"a","Settings":"b"}', object_pairs_hook=native.unique)

    def test_explicit_native_keys_and_device_warning_codes_are_catalogued(self):
        catalog = native.load_catalogs()["en"]
        source = (ROOT / "macos/KOReaderBridgeApp.swift").read_text()
        keys = set(re.findall(r'native\("([^"\\]*)"', source)) - {"warning."}
        self.assertFalse(keys - catalog.keys())
        device_source = (ROOT / "bridge_devices.py").read_text()
        codes = set(re.findall(r'warning_codes.append\("([a-z_]+)"\)', device_source)) | {"duplicate_identity"}
        self.assertFalse({"warning." + code for code in codes} - catalog.keys())
        self.assertFalse({"Identical", "Keep Target", "Metadata Skipped", "New", "Overwrite", "Target Only",
                          "audited", "success", "cancelled", "needs-recovery", "Saved source", "Restore target"} - catalog.keys())

    def test_missing_and_changed_placeholders_are_rejected(self):
        for invalid in ["missing", "placeholder"]:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                for name in native.INPUTS:
                    target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((ROOT / name).read_bytes())
                path = root / native.INPUTS[1]; cat = json.loads(path.read_text())
                if invalid == "missing": cat.pop("Settings")
                else: cat["{count} files"] = "no placeholder"
                path.write_text(json.dumps(cat))
                with self.assertRaises(ValueError): native.load_catalogs(root)
