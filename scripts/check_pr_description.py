#!/usr/bin/env python3
"""Validate PR structure only. Cannot verify claims, evidence or authorization."""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import sys

MAX_BYTES = 65536
REQUIRED = ("Change Summary", "Files Changed", "Testing & Evidence")
EVIDENCE = ("Local Verification", "CI Verification",
            "Independent QA / Architecture Review", "Required Pre-PR Validation")
STATUS = re.compile(r"\b(?:PASS|FAIL|NOT RUN|PENDING|N/A)\b")


def sections(source: str, level: int) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^" + "#" * level + r" (.+?)\s*$", source, re.M))
    return [(m.group(1), source[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(source)])
            for i, m in enumerate(matches)]


def validate_body(source: str) -> list[str]:
    if len(source.encode("utf-8")) > MAX_BYTES:
        return ["PR body exceeds 64 KiB."]
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    source = re.sub(r"^(\x60{3,}|~{3,}).*?^\1\s*$", "", source, flags=re.M | re.S)
    parsed = sections(source, 2)
    headings = [title for title, _ in parsed]
    issues = []
    for title in REQUIRED:
        if headings.count(title) != 1:
            issues.append("Include exactly one ## " + title + ".")
    if issues:
        return issues
    if [headings.index(title) for title in REQUIRED] != sorted(headings.index(title) for title in REQUIRED):
        issues.append("Keep required sections in template order.")
    body = dict(parsed)
    summary = body["Change Summary"].strip()
    if not summary or summary.startswith(("-", "*", "#")):
        issues.append("Start Change Summary with a concise problem/outcome sentence.")
    if not re.search(r"^[-*] \S", summary, re.M):
        issues.append("Use focused bullets in Change Summary.")
    file_bullets = re.findall(r"^[-*] (.+)$", body["Files Changed"], re.M)
    if not file_bullets or not any(re.search(r"\x60[^\x60]+\x60", line) for line in file_bullets):
        issues.append("Summarize meaningful files/modules with backticked paths and bullets.")
    evidence = sections(body["Testing & Evidence"], 3)
    categories = [title for title, _ in evidence]
    for title in EVIDENCE:
        matches = [content for heading, content in evidence if heading == title]
        if len(matches) != 1 or not re.search(r"^[-*] \S", matches[0], re.M):
            issues.append("Include evidence bullets under ### " + title + ".")
        elif not STATUS.search(matches[0]):
            issues.append("Record an explicit status under ### " + title + ".")
    if all(categories.count(title) == 1 for title in EVIDENCE):
        if [categories.index(title) for title in EVIDENCE] != sorted(categories.index(title) for title in EVIDENCE):
            issues.append("Keep evidence categories in template order.")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.body_file.stat().st_size > MAX_BYTES:
            raise ValueError("PR body exceeds 64 KiB.")
        issues = validate_body(args.body_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        print("PR description check failed: choose a readable UTF-8 file within 64 KiB.", file=sys.stderr)
        return 1
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1
    print("PR description structure passed. Claims and approval still require human review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
