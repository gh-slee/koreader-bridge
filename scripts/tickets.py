#!/usr/bin/env python3
"""Agent-agnostic ticket board, claims and handoffs for parallel coding agents.

Tickets are Markdown files under ``tickets/`` with a small front-matter block.
Live claims are atomic lock files under the Git common directory, so every
worktree and every agent on the same machine (Codex, Claude Code, opencode or a
human) sees the same claims without a server. The ticket file on the ticket's
branch is the durable, reviewable record; the lock only prevents two writers.

Standard library only; Python 3.9+ (this project tests 3.9, 3.12 and 3.14).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

TICKET_DIR = 'tickets'
ID_RE = re.compile(r'^[A-Z][A-Z0-9]*-P[0-2]-\d{3}[A-Z]?$')
PRIORITIES = ('P0', 'P1', 'P2')
STATUSES = ('backlog', 'ready', 'in_progress', 'paused', 'in_review', 'blocked', 'done', 'superseded')
ACTIVE = ('in_progress', 'paused', 'in_review')
TYPES = ('epic', 'feature', 'bug', 'chore', 'docs', 'review', 'decision', 'research')
RISKS = ('low', 'medium', 'high', 'critical')
SIZES = ('XS', 'S', 'M', 'L', 'XL')
TIERS = ('any', 'standard', 'frontier')
GATES = ('none', 'owner')
REVIEWS = ('self', 'independent')
REQUIRED = ('id', 'title', 'priority', 'status', 'type', 'risk', 'size', 'agent_tier',
            'gate', 'review', 'depends_on', 'resources', 'updated')
SECTIONS = ('## Goal', '## Acceptance criteria', '## Plan', '## Handoff')
PRIVATE_PATH = re.compile(r'/(?:Users|home)/[A-Za-z0-9_.-]+/')
STALE_MINUTES = int(os.environ.get('TICKETS_STALE_MINUTES', '120'))
CLAIM_FILE = Path('work') / 'agent-claim.json'


class TicketError(RuntimeError):
    pass


# ---------------------------------------------------------------- parsing

def _value(raw: str):
    raw = raw.strip()
    if raw.startswith('[') and raw.endswith(']'):
        inner = raw[1:-1].strip()
        return [item.strip().strip('"\'') for item in inner.split(',') if item.strip()] if inner else []
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in '"\'':
        return raw[1:-1]
    return raw


def parse_ticket(path: Path, text: str | None = None) -> dict:
    text = path.read_text(encoding='utf-8') if text is None else text
    if not text.startswith('---\n'):
        raise TicketError(f'{path}: missing front matter')
    end = text.find('\n---\n', 4)
    if end < 0:
        raise TicketError(f'{path}: unterminated front matter')
    meta: dict = {}
    for n, line in enumerate(text[4:end].splitlines(), 2):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if ':' not in line:
            raise TicketError(f'{path}:{n}: expected "key: value"')
        key, raw = line.split(':', 1)
        if not raw.strip().startswith(('"', "'")):
            raw = re.split(r'\s{2,}#', raw, maxsplit=1)[0]  # trailing comments need two spaces
        meta[key.strip()] = _value(raw)
    meta['_body'] = text[end + 5:]
    meta['_path'] = path
    return meta


def ticket_paths(root: Path) -> list[Path]:
    return sorted(p for p in (root / TICKET_DIR).glob('*.md') if ID_RE.match(p.stem))


def load_tickets(root: Path) -> dict[str, dict]:
    tickets = {}
    for path in ticket_paths(root):
        t = parse_ticket(path)
        tickets[t.get('id', path.stem)] = t
    return tickets


def validate(tickets: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    enums = {'priority': PRIORITIES, 'status': STATUSES, 'type': TYPES, 'risk': RISKS,
             'size': SIZES, 'agent_tier': TIERS, 'gate': GATES, 'review': REVIEWS}
    for tid, t in tickets.items():
        where = t['_path'].name
        for key in REQUIRED:
            if key not in t:
                errors.append(f'{where}: missing field {key}')
        if t.get('id') != t['_path'].stem:
            errors.append(f'{where}: id must equal file name')
        if not ID_RE.match(str(t.get('id', ''))):
            errors.append(f'{where}: malformed id')
        for key, allowed in enums.items():
            if key in t and t[key] not in allowed:
                errors.append(f'{where}: {key}={t[key]!r} not in {allowed}')
        for key in ('depends_on', 'resources'):
            if key in t and not isinstance(t[key], list):
                errors.append(f'{where}: {key} must be a [list]')
        for res in t.get('resources') or []:
            if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,80}', res):
                errors.append(f'{where}: invalid resource name {res!r}')
        for dep in t.get('depends_on') or []:
            if dep not in tickets:
                errors.append(f'{where}: unknown dependency {dep}')
            if dep == tid:
                errors.append(f'{where}: depends on itself')
        parent = t.get('parent')
        if parent and parent not in tickets:
            errors.append(f'{where}: unknown parent {parent}')
        body = t.get('_body', '')
        for heading in SECTIONS:
            if not re.search('^' + re.escape(heading) + r'\s*$', body, re.M):
                errors.append(f'{where}: missing section "{heading}"')
        if t.get('status') == 'blocked' and not re.search(r'^## Decisions needed\s*$', body, re.M):
            errors.append(f'{where}: blocked tickets need a "## Decisions needed" section')
        if t.get('gate') == 'owner' and t.get('status') in ('in_progress', 'in_review', 'done') and not t.get('gate_approval'):
            errors.append(f'{where}: owner-gated ticket is {t["status"]} without gate_approval')
        if t.get('status') == 'done':
            for dep in t.get('depends_on') or []:
                if dep in tickets and tickets[dep].get('status') not in ('done', 'superseded'):
                    errors.append(f'{where}: done but dependency {dep} is {tickets[dep].get("status")}')
        if PRIVATE_PATH.search(t['_path'].read_text(encoding='utf-8')):
            errors.append(f'{where}: contains a machine-specific home path')
    # cycle detection
    state: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> None:
        if state.get(node) == 2 or node not in tickets:
            return
        if state.get(node) == 1:
            errors.append('dependency cycle: ' + ' -> '.join(stack + [node]))
            return
        state[node] = 1
        for dep in tickets[node].get('depends_on') or []:
            visit(dep, stack + [node])
        state[node] = 2

    for tid in tickets:
        visit(tid, [])
    return errors


# ---------------------------------------------------------------- git/locks

def git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if check and result.returncode:
        raise TicketError(f'git {args[0]} failed: {result.stderr.strip()[:300]}')
    return result.stdout.strip()


def repo_root(start: Path) -> Path:
    return Path(git(start, 'rev-parse', '--show-toplevel'))


def lock_dir(root: Path) -> Path:
    override = os.environ.get('TICKETS_LOCK_DIR')
    if override:
        base = Path(override)
    else:
        base = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')) / 'agent-tickets'
    (base / 'claims').mkdir(parents=True, exist_ok=True)
    (base / 'resources').mkdir(parents=True, exist_ok=True)
    return base


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t: dt.datetime) -> str:
    return t.isoformat().replace('+00:00', 'Z')


def parse_iso(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))


def _create_exclusive(path: Path, data: dict) -> bool:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write('\n')
    return True


def _replace(path: Path, data: dict) -> None:
    tmp = path.with_suffix(f'.{secrets.token_hex(4)}.tmp')
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def read_claim(locks: Path, tid: str) -> dict | None:
    path = locks / 'claims' / f'{tid}.json'
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None


def all_claims(locks: Path) -> dict[str, dict]:
    out = {}
    for path in sorted((locks / 'claims').glob('*.json')):
        try:
            out[path.stem] = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            out[path.stem] = {'ticket': path.stem, 'agent': '?', 'heartbeat': '1970-01-01T00:00:00Z'}
    return out


def is_stale(claim: dict) -> bool:
    age = now() - parse_iso(claim.get('heartbeat', '1970-01-01T00:00:00Z'))
    return age > dt.timedelta(minutes=STALE_MINUTES)


def resource_holder(locks: Path, resource: str) -> dict | None:
    try:
        return json.loads((locks / 'resources' / f'{_safe(resource)}.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None


def _safe(name: str) -> str:
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,80}', name):
        raise TicketError(f'invalid resource name {name!r}; use lowercase kebab-case')
    return name


def local_claim_file(worktree: Path) -> Path:
    return worktree / CLAIM_FILE


# ---------------------------------------------------------------- readiness

def deps_done(t: dict, tickets: dict[str, dict]) -> bool:
    return all(tickets.get(d, {}).get('status') in ('done', 'superseded') for d in t.get('depends_on') or [])


def gate_ok(t: dict) -> bool:
    return t.get('gate') == 'none' or bool(t.get('gate_approval'))


def tier_ok(t: dict, tier: str) -> bool:
    return TIERS.index(t.get('agent_tier', 'frontier')) <= TIERS.index(tier)


def availability(t: dict, tickets: dict, claims: dict, locks: Path) -> tuple[bool, str]:
    tid = t['id']
    claim = claims.get(tid)
    if claim and not is_stale(claim):
        return False, f'claimed by {claim.get("agent")}'
    if t['status'] in ('done', 'superseded'):
        return False, t['status']
    if t['status'] == 'blocked':
        return False, 'blocked on decision'
    if t['status'] == 'in_review':
        return False, 'in review (owner/reviewer)'
    if t['type'] == 'epic':
        return False, 'epic (work its children)'
    if t['status'] == 'backlog':
        return False, 'backlog (not groomed)'
    if not deps_done(t, tickets):
        return False, 'waiting on ' + ','.join(d for d in t['depends_on'] if tickets[d]['status'] not in ('done', 'superseded'))
    if not gate_ok(t):
        return False, 'needs owner gate approval'
    for res in t.get('resources') or []:
        holder = resource_holder(locks, res)
        if holder and holder.get('ticket') != tid:
            other = claims.get(holder.get('ticket'))
            if other and not is_stale(other):
                return False, f'resource {res} held by {holder.get("ticket")}'
    if claim:
        return True, f'RESUMABLE: stale claim by {claim.get("agent")} (use takeover)'
    if t['status'] in ACTIVE:
        return True, 'RESUMABLE: in progress with no live claim (use claim)'
    return True, 'ready'


# ---------------------------------------------------------------- commands

def cmd_check(root: Path, args) -> int:
    tickets = load_tickets(root)
    errors = validate(tickets)
    for e in errors:
        print('ERROR', e)
    print(f'{len(tickets)} tickets, {len(errors)} errors')
    return 1 if errors else 0


def cmd_list(root: Path, args) -> int:
    tickets = load_tickets(root)
    locks = lock_dir(root)
    claims = all_claims(locks)
    rows = []
    for t in sorted(tickets.values(), key=lambda t: (t['priority'], t['id'])):
        if args.priority and t['priority'] != args.priority:
            continue
        if args.status and t['status'] != args.status:
            continue
        if not args.all and t['status'] in ('done', 'superseded'):
            continue
        claim = claims.get(t['id'])
        who = ''
        if claim:
            who = claim.get('agent', '?') + (' (STALE)' if is_stale(claim) else '')
        rows.append((t['id'], t['priority'], t['status'], t['agent_tier'], t['risk'], who, t['title']))
    width = [max([len(str(r[i])) for r in rows] + [2]) for i in range(6)]
    for r in rows:
        print('  '.join(str(r[i]).ljust(width[i]) for i in range(6)) + '  ' + r[6])
    print(f'{len(rows)} shown; live claims: {len([c for c in claims.values() if not is_stale(c)])}')
    return 0


def cmd_next(root: Path, args) -> int:
    tickets = load_tickets(root)
    locks = lock_dir(root)
    claims = all_claims(locks)
    found = 0
    for t in sorted(tickets.values(), key=lambda t: (t['priority'], t['status'] not in ACTIVE, t['id'])):
        if not tier_ok(t, args.tier):
            continue
        ok, why = availability(t, tickets, claims, locks)
        if ok:
            found += 1
            print(f'{t["id"]:<12} {t["priority"]} {t["agent_tier"]:<9} {t["risk"]:<8} {why:<28} {t["title"]}')
    if not found:
        print('No claimable ticket for this tier. Run "list" to see blockers.')
    return 0


def cmd_show(root: Path, args) -> int:
    tickets = load_tickets(root)
    t = tickets.get(args.id)
    if not t:
        raise TicketError(f'unknown ticket {args.id}')
    locks = lock_dir(root)
    claim = read_claim(locks, args.id)
    branch = (claim or {}).get('branch') or t.get('branch')
    text = t['_path'].read_text(encoding='utf-8')
    if branch:
        for ref in (branch, f'origin/{branch}'):
            other = git(root, 'show', f'{ref}:{TICKET_DIR}/{args.id}.md', check=False)
            if other:
                if other.strip() != text.strip():
                    print(f'# NOTE: showing the newer copy from branch {ref}\n')
                text = other
                break
    print(text)
    if claim:
        print('\n# Live claim\n' + json.dumps({k: v for k, v in claim.items() if k != 'token'}, indent=2))
    return 0


def _slug(title: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40].rstrip('-')


def cmd_claim(root: Path, args, takeover: bool = False) -> int:
    tickets = load_tickets(root)
    t = tickets.get(args.id)
    if not t:
        raise TicketError(f'unknown ticket {args.id}')
    locks = lock_dir(root)
    claims = all_claims(locks)
    existing = claims.get(args.id)
    if takeover:
        if not existing:
            raise TicketError('no claim to take over; use claim')
        if not is_stale(existing) and not args.owner_approved:
            raise TicketError(f'claim by {existing.get("agent")} is live (heartbeat {existing.get("heartbeat")}); '
                              f'wait until it is older than {STALE_MINUTES} min or pass --owner-approved')
    else:
        if existing:
            raise TicketError(f'already claimed by {existing.get("agent")}; '
                              + ('claim is STALE, use takeover' if is_stale(existing) else 'pick another ticket'))
        ok, why = availability(t, tickets, claims, locks)
        if not ok and not args.force:
            raise TicketError(f'{args.id} is not claimable: {why}')
    branch = (existing or {}).get('branch') or t.get('branch') or f'ticket/{args.id.lower()}-{_slug(t["title"])}'
    main_root = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')).parent
    worktree = Path(args.worktree_path) if args.worktree_path else (
        Path((existing or {}).get('worktree', '')) if (existing or {}).get('worktree') else
        main_root / 'work' / 'worktrees' / args.id.lower())
    token = secrets.token_hex(16)
    digest = int(hashlib.sha256(args.id.encode()).hexdigest(), 16)
    record = {
        'ticket': args.id, 'agent': args.agent, 'token_sha256': hashlib.sha256(token.encode()).hexdigest(),
        'claimed_at': iso(now()), 'heartbeat': iso(now()), 'branch': branch, 'worktree': str(worktree),
        'isolation_id': f'{args.id.lower()}-{secrets.token_hex(2)}',
        'port_base': 20000 + (digest % 400) * 100,
        'resources': list(t.get('resources') or []), 'host': os.uname().nodename if hasattr(os, 'uname') else '',
        'previous_owners': [], 'note': args.note or '',
    }
    path = locks / 'claims' / f'{args.id}.json'
    if takeover:
        record['previous_owners'] = existing.get('previous_owners', []) + [
            {'agent': existing.get('agent'), 'claimed_at': existing.get('claimed_at'),
             'last_heartbeat': existing.get('heartbeat'), 'taken_over_at': iso(now()),
             'reason': args.reason or ('stale' if is_stale(existing) else 'owner-approved')}]
        record['isolation_id'] = existing.get('isolation_id', record['isolation_id'])
        record['port_base'] = existing.get('port_base', record['port_base'])
        _replace(path, record)
    elif not _create_exclusive(path, record):
        raise TicketError('lost the race: another agent claimed it just now')
    taken: list[Path] = []
    try:
        for res in record['resources']:
            rpath = locks / 'resources' / f'{_safe(res)}.json'
            holder = resource_holder(locks, res)
            if holder and holder.get('ticket') != args.id:
                other = read_claim(locks, holder['ticket'])
                if other and not is_stale(other):
                    raise TicketError(f'resource {res} is held by live claim {holder["ticket"]}')
                rpath.unlink(missing_ok=True)  # stale or orphaned holder
            if holder and holder.get('ticket') == args.id:
                _replace(rpath, {'ticket': args.id, 'since': iso(now())})
            elif not _create_exclusive(rpath, {'ticket': args.id, 'since': iso(now())}):
                raise TicketError(f'lost the race for resource {res}')
            taken.append(rpath)
    except TicketError:
        for rpath in taken:
            rpath.unlink(missing_ok=True)
        if not takeover:
            path.unlink(missing_ok=True)
        raise
    if args.worktree:
        if not worktree.exists():
            has_local = git(root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}', check=False)
            has_remote = git(root, 'rev-parse', '--verify', '--quiet', f'refs/remotes/origin/{branch}', check=False)
            if has_local:
                git(root, 'worktree', 'add', str(worktree), branch)
            elif has_remote:
                git(root, 'worktree', 'add', '--no-track', '-b', branch, str(worktree), f'origin/{branch}')
            else:
                git(root, 'worktree', 'add', '--no-track', '-b', branch, str(worktree), args.base)
    target = worktree if worktree.exists() else root
    cf = local_claim_file(target)
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps({'ticket': args.id, 'token': token, 'agent': args.agent}, indent=2) + '\n', encoding='utf-8')
    os.chmod(cf, 0o600)
    print(json.dumps({k: v for k, v in record.items() if k != 'token_sha256'}, indent=2))
    print(f'\nClaimed {args.id}. Work in: {target}\nBranch: {branch}\n'
          f'Next: read tickets/{args.id}.md "## Handoff", set status: in_progress, commit, and heartbeat at each checkpoint.')
    return 0


def _owned(root: Path, locks: Path, tid: str) -> dict:
    claim = read_claim(locks, tid)
    if not claim:
        raise TicketError(f'{tid} has no live claim')
    cf = local_claim_file(root)
    token = os.environ.get('TICKETS_TOKEN')
    if not token and cf.exists():
        local = json.loads(cf.read_text(encoding='utf-8'))
        token = local.get('token') if local.get('ticket') == tid else None
    if not token or hashlib.sha256(token.encode()).hexdigest() != claim.get('token_sha256'):
        raise TicketError(f'this worktree does not own the claim on {tid} (owner: {claim.get("agent")}); '
                          'run from the claiming worktree or use takeover')
    return claim


def cmd_heartbeat(root: Path, args) -> int:
    locks = lock_dir(root)
    claim = _owned(root, locks, args.id)
    claim['heartbeat'] = iso(now())
    if args.note:
        claim['note'] = args.note
    _replace(locks / 'claims' / f'{args.id}.json', claim)
    print(f'heartbeat {args.id} {claim["heartbeat"]}')
    return 0


def cmd_release(root: Path, args) -> int:
    locks = lock_dir(root)
    claim = read_claim(locks, args.id) if args.owner_approved else _owned(root, locks, args.id)
    if not claim:
        raise TicketError(f'{args.id} has no claim')
    for res in claim.get('resources', []):
        holder = resource_holder(locks, res)
        if holder and holder.get('ticket') == args.id:
            (locks / 'resources' / f'{_safe(res)}.json').unlink(missing_ok=True)
    (locks / 'claims' / f'{args.id}.json').unlink(missing_ok=True)
    cf = local_claim_file(root)
    if cf.exists():
        cf.unlink()
    print(f'released {args.id}')
    return 0


def cmd_resume(root: Path, args) -> int:
    """Print everything a fresh agent needs to continue a ticket."""
    cmd_show(root, args)
    locks = lock_dir(root)
    claim = read_claim(locks, args.id) or {}
    t = load_tickets(root)[args.id]
    branch = claim.get('branch') or t.get('branch')
    wt = Path(claim['worktree']) if claim.get('worktree') else None
    print('\n# Git state')
    if branch:
        print('branch:', branch)
        print(git(root, 'log', '--oneline', '-15', f'origin/main..{branch}', check=False) or '(no local commits ahead of origin/main or branch missing locally)')
    if wt and wt.exists():
        print(f'worktree: {wt}')
        print(git(wt, 'status', '--short', check=False) or '(clean)')
    print('\nResume protocol: confirm no other process writes in that worktree, then claim/takeover, '
          're-run the "Verify" commands in the ticket Handoff, and continue from "Next step".')
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('check', help='validate all ticket files')
    s = sub.add_parser('list', help='board view')
    s.add_argument('--priority', choices=PRIORITIES)
    s.add_argument('--status', choices=STATUSES)
    s.add_argument('--all', action='store_true', help='include done/superseded')
    s = sub.add_parser('next', help='claimable tickets for your capability tier')
    s.add_argument('--tier', choices=TIERS, default='frontier')
    for name in ('show', 'resume'):
        s = sub.add_parser(name)
        s.add_argument('id')
    for name in ('claim', 'takeover'):
        s = sub.add_parser(name)
        s.add_argument('id')
        s.add_argument('--agent', required=True, help='e.g. codex/gpt-5.5, claude/opus-5.5, opencode/deepseek-flash')
        s.add_argument('--worktree', action='store_true', help='create/attach the ticket worktree')
        s.add_argument('--worktree-path')
        s.add_argument('--base', default='origin/main')
        s.add_argument('--note')
        s.add_argument('--force', action='store_true', help='claim even if not ready (owner instruction only)')
        s.add_argument('--owner-approved', action='store_true', help='owner said to take over a live claim')
        s.add_argument('--reason')
    s = sub.add_parser('heartbeat')
    s.add_argument('id')
    s.add_argument('--note')
    s = sub.add_parser('release')
    s.add_argument('id')
    s.add_argument('--owner-approved', action='store_true')
    args = p.parse_args(argv)
    root = repo_root(Path.cwd())
    try:
        if args.cmd == 'takeover':
            return cmd_claim(root, args, takeover=True)
        return {'check': cmd_check, 'list': cmd_list, 'next': cmd_next, 'show': cmd_show,
                'resume': cmd_resume, 'claim': cmd_claim, 'heartbeat': cmd_heartbeat,
                'release': cmd_release}[args.cmd](root, args)
    except TicketError as exc:
        print('error:', exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
