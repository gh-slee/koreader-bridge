"""Ticket backlog validation and the parallel-agent claim protocol."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import tickets  # noqa: E402

TEMPLATE = """---
id: {id}
title: Synthetic ticket {id}
priority: P1
status: {status}
type: chore
parent:
depends_on: [{deps}]
resources: [{res}]
risk: low
size: S
agent_tier: {tier}
gate: none
gate_approval:
review: self
branch:
pr:
spec:
updated: 2026-11-05
---

# {id}

## Goal

Synthetic.

## Acceptance criteria

- [ ] Works.

## Plan

- [ ] Do it.

## Handoff

- State: none.

## Log

- 2026-11-05 test: created.
"""


def run(cwd: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    old = Path.cwd()
    os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tickets.main(list(argv))
    finally:
        os.chdir(old)
    return code, out.getvalue(), err.getvalue()


class RepositoryTicketsTest(unittest.TestCase):
    def test_repository_tickets_are_valid(self):
        self.assertEqual(tickets.validate(tickets.load_tickets(ROOT)), [])


class ClaimProtocolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / 'repo'
        (self.repo / 'tickets').mkdir(parents=True)
        self.write('TK-P1-001', res='shared-res')
        self.write('TK-P1-002', res='shared-res')
        self.write('TK-P1-003', deps='TK-P1-001')
        self.write('TK-P1-004', tier='frontier')
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}
        for cmd in (['init', '-q', '-b', 'main'], ['add', '.'], ['commit', '-q', '-m', 'init']):
            subprocess.run(['git', '-C', str(self.repo), *cmd], check=True, env=env, capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, tid, status='ready', deps='', res='', tier='any'):
        (self.repo / 'tickets' / f'{tid}.md').write_text(
            TEMPLATE.format(id=tid, status=status, deps=deps, res=res, tier=tier), encoding='utf-8')

    def claim(self, tid, agent='codex/test', *extra):
        return run(self.repo, 'claim', tid, '--agent', agent, *extra)

    def test_second_claim_on_same_ticket_is_refused(self):
        self.assertEqual(self.claim('TK-P1-001')[0], 0)
        code, _, err = self.claim('TK-P1-001', 'claude/test')
        self.assertEqual(code, 2)
        self.assertIn('already claimed by codex/test', err)

    def test_shared_resource_blocks_parallel_ticket_and_is_released(self):
        self.assertEqual(self.claim('TK-P1-001')[0], 0)
        code, _, err = self.claim('TK-P1-002', 'opencode/test')
        self.assertEqual(code, 2)
        self.assertIn('resource shared-res held by TK-P1-001', err)
        self.assertEqual(run(self.repo, 'release', 'TK-P1-001')[0], 0)
        self.assertEqual(self.claim('TK-P1-002', 'opencode/test')[0], 0)

    def test_unfinished_dependency_and_tier_filter(self):
        code, _, err = self.claim('TK-P1-003')
        self.assertEqual(code, 2)
        self.assertIn('waiting on TK-P1-001', err)
        _, out, _ = run(self.repo, 'next', '--tier', 'any')
        self.assertIn('TK-P1-001', out)
        self.assertNotIn('TK-P1-004', out)

    def test_heartbeat_requires_the_owning_worktree_token(self):
        self.assertEqual(self.claim('TK-P1-001')[0], 0)
        self.assertEqual(run(self.repo, 'heartbeat', 'TK-P1-001')[0], 0)
        (self.repo / 'work' / 'agent-claim.json').unlink()
        code, _, err = run(self.repo, 'heartbeat', 'TK-P1-001')
        self.assertEqual(code, 2)
        self.assertIn('does not own the claim', err)

    def test_takeover_needs_stale_claim_and_records_previous_owner(self):
        self.assertEqual(self.claim('TK-P1-001')[0], 0)
        code, _, err = run(self.repo, 'takeover', 'TK-P1-001', '--agent', 'claude/test')
        self.assertEqual(code, 2)
        self.assertIn('is live', err)
        with mock.patch.object(tickets, 'STALE_MINUTES', -1):
            code, out, _ = run(self.repo, 'takeover', 'TK-P1-001', '--agent', 'claude/test', '--reason', 'usage limit')
        self.assertEqual(code, 0, out)
        claim = tickets.read_claim(tickets.lock_dir(self.repo), 'TK-P1-001')
        self.assertEqual(claim['agent'], 'claude/test')
        self.assertEqual(claim['previous_owners'][0]['agent'], 'codex/test')
        self.assertEqual(claim['previous_owners'][0]['reason'], 'usage limit')
        self.assertEqual(run(self.repo, 'heartbeat', 'TK-P1-001')[0], 0)

    def test_claim_with_worktree_creates_isolated_branch(self):
        code, out, _ = self.claim('TK-P1-001', 'codex/test', '--worktree', '--base', 'main')
        self.assertEqual(code, 0, out)
        wt = self.repo / 'work' / 'worktrees' / 'tk-p1-001'
        self.assertTrue((wt / 'tickets' / 'TK-P1-001.md').exists())
        branch = subprocess.run(['git', '-C', str(wt), 'branch', '--show-current'],
                                capture_output=True, text=True, check=True).stdout.strip()
        self.assertTrue(branch.startswith('ticket/tk-p1-001-'))
        local = json.loads((wt / 'work' / 'agent-claim.json').read_text())
        self.assertEqual(local['ticket'], 'TK-P1-001')
        self.assertEqual(run(wt, 'heartbeat', 'TK-P1-001')[0], 0)

    def test_validation_rejects_cycles_unknown_deps_and_private_paths(self):
        self.write('TK-P1-001', deps='TK-P1-003')
        self.write('TK-P1-002', deps='TK-P1-099')
        path = self.repo / 'tickets' / 'TK-P1-004.md'
        path.write_text(path.read_text() + '\nSee /' + 'Users/someone/secret\n')  # split to keep the guard clean
        errors = '\n'.join(tickets.validate(tickets.load_tickets(self.repo)))
        self.assertIn('dependency cycle', errors)
        self.assertIn('unknown dependency TK-P1-099', errors)
        self.assertIn('machine-specific home path', errors)


if __name__ == '__main__':
    unittest.main()
