#!/usr/bin/env python3
"""Validate native catalogs and emit standard macOS localization resources."""
from __future__ import annotations
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ("en", "zh-Hant", "zh-Hans")
INPUTS = ["macos/locales/" + language + ".json" for language in LOCALES]


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate native message: " + key)
        result[key] = value
    return result


def load_catalogs(root=ROOT):
    catalogs = {}
    for language, name in zip(LOCALES, INPUTS):
        path = root / name
        if path.is_symlink() or path.stat().st_size > 256 * 1024:
            raise ValueError("Unsafe native catalog: " + name)
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
        if not isinstance(value, dict) or not value or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip()
                                                        or "\x00" in k + v for k, v in value.items()):
            raise ValueError("Invalid native catalog: " + name)
        catalogs[language] = value
    english = catalogs["en"]
    for language, catalog in catalogs.items():
        if catalog.keys() != english.keys():
            raise ValueError("Native catalog keys differ: " + language)
        for key, value in catalog.items():
            if sorted(re.findall(r"\{[a-zA-Z]+\}", value)) != sorted(re.findall(r"\{[a-zA-Z]+\}", english[key])):
                raise ValueError("Native placeholders differ: " + language + " " + key)
    return catalogs


def write_resources(destination, root=ROOT):
    catalogs = load_catalogs(root)
    for language, catalog in catalogs.items():
        folder = destination / (language + ".lproj")
        folder.mkdir(parents=True, exist_ok=False)
        # JSON string quoting is compatible with the subset used in .strings.
        text = "\n".join(json.dumps(k, ensure_ascii=False) + " = " + json.dumps(v, ensure_ascii=False) + ";"
                         for k, v in sorted(catalog.items())) + "\n"
        (folder / "Localizable.strings").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    data = load_catalogs()
    print("Native locales: " + ", ".join(k + "=" + str(len(v)) for k, v in data.items()))
