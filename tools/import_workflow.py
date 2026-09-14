#!/usr/bin/env python3
"""Import a committed export into n8n, binding credentials BY ID.

The exports carry credential NAMES only, deliberately. n8n's public API
ignores names and honours ids, so an import that sends a name alone lets the
instance pick - on 2026-09-11 it picked the product database for 31 of 31
nodes. This binds every slot to a verified id, and DROPS any slot whose
credential does not exist rather than leaving a name for n8n to resolve.
"""
import json, os, sys, urllib.request, urllib.error

API = os.environ['N8N_API_URL']; KEY = os.environ['N8N_API_KEY']
PRODUCT_DB = 'kngcxwcybozgqgnoweyt'

# Credential ids are instance-specific and MUST NOT be committed - this repo is
# public. Supply them in ops/credential-ids.local.json (gitignored), shaped
#   { "Campaign Ledger (Supabase, campaign schema)": "...", ... }
# keyed by the exact credential NAME the exports carry. A name with no id here
# has its slot DROPPED rather than sent, because n8n resolves an unmatched name
# to a credential of its own choosing - on 2026-09-11 it chose the product
# database for 31 of 31 nodes.
CRED_MAP_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'ops', 'credential-ids.local.json')
if not os.path.exists(CRED_MAP_FILE):
    sys.exit(f'missing {CRED_MAP_FILE} - see ops/CREDENTIAL-IDS.md')
CRED_IDS = json.load(open(CRED_MAP_FILE))

def req(method, path, body=None):
    r = urllib.request.Request(API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'X-N8N-API-KEY': KEY, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=60) as f:
            return f.status, json.loads(f.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:800]

def prepare(path):
    wf = json.load(open(path))
    expected, dropped = {}, []
    for n in wf['nodes']:
        creds = n.get('credentials')
        if not creds:
            continue
        newc = {}
        for ctype, c in creds.items():
            name = c.get('name')
            cid = CRED_IDS.get(name)
            if cid:
                newc[ctype] = {'id': cid, 'name': name}
                expected[(n['name'], ctype)] = (cid, name)
            else:
                dropped.append((n['name'], ctype, name))
        if newc:
            n['credentials'] = newc
        else:
            n.pop('credentials', None)
    payload = {'name': wf['name'], 'nodes': wf['nodes'],
               'connections': wf['connections'], 'settings': wf.get('settings', {})}
    # The product-db id legitimately appears in ONE place: the Guard node whose
    # only job is to throw on it. Anywhere else - a ledger_url, a credential -
    # means this import would point the campaign at the live product database.
    stray = [n['name'] for n in payload['nodes']
             if PRODUCT_DB in json.dumps(n) and n['name'] != 'Guard: ledger target']
    assert not stray, f'REFUSING: product-db ref outside the guard: {stray}'
    # A guard is required of any workflow that can actually REACH the ledger,
    # which is not the same as any workflow that mentions it. WF-C2 carries
    # ledger_url in its Config and uses it nowhere: it only sends mail, holds
    # no supabaseApi credential, and the repo documents that it needs no guard.
    # Demanding one of every workflow refused C2 for having been built
    # correctly, so the test is reachability, not mention.
    touches_ledger = any('supabaseApi' in (n.get('credentials') or {})
                         for n in payload['nodes'])
    guards = [n['name'] for n in payload['nodes'] if n['name'] == 'Guard: ledger target']
    if touches_ledger:
        assert guards, 'REFUSING: workflow holds a ledger credential but has no "Guard: ledger target"'
    elif not guards:
        print('   note: no ledger credential and no guard, which is consistent')
    assert 'id' not in payload, 'payload must not carry a top-level id'
    return payload, expected, dropped

def verify(wid, expected):
    s, got = req('GET', f'/workflows/{wid}')
    assert s == 200, (s, got)
    stray = [n['name'] for n in got['nodes']
             if PRODUCT_DB in json.dumps(n) and n['name'] != 'Guard: ledger target']
    assert not stray, f'READ-BACK: product-db ref outside the guard: {stray}'
    # Same reachability rule as prepare(): only a workflow that can reach the
    # ledger must still have its guard after the round trip.
    if any('supabaseApi' in (n.get('credentials') or {}) for n in got['nodes']):
        assert any(n['name'] == 'Guard: ledger target' for n in got['nodes']), \
            'READ-BACK: the guard node did not survive the import'
    seen, bad = {}, []
    for n in got['nodes']:
        for ctype, c in (n.get('credentials') or {}).items():
            seen[(n['name'], ctype)] = (c.get('id'), c.get('name'))
    for k, want in expected.items():
        if seen.get(k) != want:
            bad.append((k, want, seen.get(k)))
    for k, v in seen.items():
        if k not in expected:
            bad.append((k, '(should not be bound at all)', v))
    return got, seen, bad

def main(path, apply=False, update_id=None):
    payload, expected, dropped = prepare(path)
    print(f"== {payload['name']}")
    print(f"   {len(payload['nodes'])} nodes; {len(expected)} credential slots bound by id")
    for (nn, ct), (cid, nm) in sorted(expected.items()):
        print(f"     bind   {nn:<34} {ct:<15} {cid}  {nm}")
    for nn, ct, nm in dropped:
        print(f"     DROP   {nn:<34} {ct:<15} -- no credential exists for {nm!r}")
    if not apply:
        print("   (dry run, nothing sent)"); return

    if update_id:
        # Snapshot first. A PUT re-registers the webhook on an active workflow,
        # so "did activation survive" is a thing to check, not assume.
        s, before = req('GET', f'/workflows/{update_id}')
        if s != 200:
            print('   cannot read existing workflow:', s, before); sys.exit(1)
        was_active = before.get('active')
        print(f"   updating {update_id}  (was active={was_active}, {len(before['nodes'])} nodes)")
        s, body = req('PUT', f'/workflows/{update_id}', payload)
        print('   update status', s)
        if s not in (200, 201):
            print(body); sys.exit(1)
        wid = update_id
    else:
        s, body = req('POST', '/workflows', payload)
        print('   create status', s)
        if s not in (200, 201):
            print(body); sys.exit(1)
        wid = body['id']
        was_active = None
    print(f"   id={wid}  active={body.get('active')}")
    if was_active is not None and body.get('active') != was_active:
        print(f"   !! ACTIVATION CHANGED: {was_active} -> {body.get('active')}")
        sys.exit(1)
    got, seen, bad = verify(wid, expected)
    if bad:
        print('   !! VERIFY FAILED')
        for b in bad: print('     ', b)
        sys.exit(1)
    print(f"   verified: {len(seen)}/{len(expected)} slots match id AND name; "
          f"active={got.get('active')}; no product-db reference")

if __name__ == '__main__':
    argv = sys.argv[1:]
    uid = None
    if '--update' in argv:
        uid = argv[argv.index('--update') + 1]
    main(argv[0], apply='--apply' in argv, update_id=uid)
