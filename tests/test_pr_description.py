"""PR structure and exact-body publication boundaries; no remote calls."""
from __future__ import annotations
import contextlib
import importlib.util
import io
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


description = load("check_pr_description")
publisher = load("publish")
guard = load("check_publication")
VALID_BODY = """## Change Summary

Readers can distinguish checked behavior from validation gaps.

- Separate evidence categories.
- Preserve publication approval requirements.

## Files Changed

- §AGENTS.md§: Routes PR authoring to the canonical template.

## Testing & Evidence

### Local Verification

- PASS: Synthetic format fixture checked locally.

### CI Verification

- NOT RUN: This fixture has no remote revision.

### Independent QA / Architecture Review

- NOT RUN: Developer self-testing only.

### Required Pre-PR Validation

- NOT RUN: No publication is requested by this fixture.
""".replace("§", chr(96))


class PRDescriptionTests(unittest.TestCase):
    def test_small_complete_body_allows_omitted_conditional_sections(self):
        self.assertEqual(description.validate_body(VALID_BODY), [])

    def test_dense_legacy_body_is_not_a_complete_review(self):
        self.assertTrue(description.validate_body("A long change narrative. Everything passed."))

    def test_missing_category_or_status_refuses(self):
        for text in [VALID_BODY.replace("### CI Verification", "### Other evidence"),
                     VALID_BODY.replace("- NOT RUN: This fixture has no remote revision.", "- Waiting for a revision.")]:
            with self.subTest(text=text):
                self.assertTrue(description.validate_body(text))

    def test_comment_or_fenced_template_cannot_supply_evidence(self):
        for text in ["<!--" + VALID_BODY + "-->", chr(96) * 3 + "\n" + VALID_BODY + chr(96) * 3]:
            with self.subTest(text=text):
                self.assertTrue(description.validate_body(text))

    def test_duplicate_and_reordered_required_sections_refuse(self):
        self.assertTrue(description.validate_body(VALID_BODY + "\n## Files Changed\n- Duplicate\n"))
        reordered = VALID_BODY.replace("## Change Summary", "## Temporary", 1).replace(
            "## Files Changed", "## Change Summary", 1).replace("## Temporary", "## Files Changed", 1)
        self.assertTrue(any("template order" in issue for issue in description.validate_body(reordered)))

    def test_missing_summary_sentence_and_module_paths_refuse(self):
        self.assertTrue(description.validate_body(VALID_BODY.replace("Readers can distinguish checked behavior from validation gaps.", "")))
        self.assertTrue(description.validate_body(VALID_BODY.replace(chr(96), "")))

    def test_oversized_or_invalid_utf8_file_refuses(self):
        self.assertTrue(description.validate_body(VALID_BODY + "界" * 65536))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "body.md"
            path.write_bytes(b"\xff")
            with mock.patch("sys.argv", ["check", "--body-file", str(path)]), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(description.main(), 1)

    def test_invalid_body_blocks_remote_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            body = Path(temp) / "body.md"; body.write_text("Incomplete body.")
            def run(*cmd, capture=False):
                if cmd[:4] == ("git", "symbolic-ref", "--quiet", "--short"): return "feature/fixture"
                if cmd[:3] == ("git", "remote", "get-url"): return "https://github.com/example/tool.git"
                return ""
            with mock.patch("sys.argv", ["publish", "--repository", "example/tool", "--title", "Fixture", "--body-file", str(body)]), \
                 mock.patch.object(publisher.shutil, "which", return_value="/bin/gh"), \
                 mock.patch.dict(sys.modules, {"check_publication": guard, "check_pr_description": description}), \
                 mock.patch.object(publisher, "run", side_effect=run) as calls, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(publisher.main(), 1)
            self.assertFalse(any(call.args[:2] == ("git", "push") or call.args[:2] == ("gh", "pr") for call in calls.call_args_list))

    def test_existing_pr_replaces_body_with_private_frozen_reviewed_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            body = Path(temp) / "body.md"; body.write_text(VALID_BODY)
            sent = []
            def run(*cmd, capture=False):
                if cmd[:4] == ("git", "symbolic-ref", "--quiet", "--short"): return "feature/fixture"
                if cmd[:3] == ("git", "remote", "get-url"): return "https://github.com/example/tool.git"
                if cmd[:3] == ("gh", "pr", "list"): return "https://github.com/example/tool/pull/1"
                if "--self-test" in cmd: body.write_text("Changed after validation.")
                if cmd[:3] == ("gh", "pr", "edit"):
                    frozen = Path(cmd[cmd.index("--body-file") + 1])
                    self.assertEqual(frozen.read_text(), VALID_BODY)
                    self.assertEqual(stat.S_IMODE(frozen.stat().st_mode), 0o600)
                    self.assertNotEqual(frozen, body)
                    sent.append(frozen)
                return ""
            with mock.patch("sys.argv", ["publish", "--repository", "example/tool", "--title", "Fixture", "--body-file", str(body)]), \
                 mock.patch.object(publisher.shutil, "which", return_value="/bin/gh"), \
                 mock.patch.dict(sys.modules, {"check_publication": guard, "check_pr_description": description}), \
                 mock.patch.object(publisher, "run", side_effect=run) as calls, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(publisher.main(), 0)
            self.assertEqual(len(sent), 1)
            self.assertFalse(sent[0].exists())
            self.assertFalse(any(call.args[:3] in {("gh", "pr", "create"), ("gh", "pr", "merge")} for call in calls.call_args_list))
