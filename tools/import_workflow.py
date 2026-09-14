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
    guards = [n['name'] for n in payload['nodes'] if n['name'] == 'Guard: ledger target']
    assert guards, 'REFUSING: no "Guard: ledger target" node in this workflow'
    assert 'id' not in payload, 'payload must not carry a top-level id'
    return payload, expected, dropped

def verify(wid, expected):
    s, got = req('GET', f'/workflows/{wid}')
    assert s == 200, (s, got)
    stray = [n['name'] for n in got['nodes']
             if PRODUCT_DB in json.dumps(n) and n['name'] != 'Guard: ledger target']
    assert not stray, f'READ-BACK: product-db ref outside the guard: {stray}'
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

def main(path, apply=False):
    payload, expected, dropped = prepare(path)
    print(f"== {payload['name']}")
    print(f"   {len(payload['nodes'])} nodes; {len(expected)} credential slots bound by id")
    for (nn, ct), (cid, nm) in sorted(expected.items()):
        print(f"     bind   {nn:<34} {ct:<15} {cid}  {nm}")
    for nn, ct, nm in dropped:
        print(f"     DROP   {nn:<34} {ct:<15} -- no credential exists for {nm!r}")
    if not apply:
        print("   (dry run, nothing sent)"); return
    s, body = req('POST', '/workflows', payload)
    print('   create status', s)
    if s not in (200, 201):
        print(body); sys.exit(1)
    wid = body['id']
    print(f"   id={wid}  active={body.get('active')}")
    got, seen, bad = verify(wid, expected)
    if bad:
        print('   !! VERIFY FAILED')
        for b in bad: print('     ', b)
        sys.exit(1)
    print(f"   verified: {len(seen)}/{len(expected)} slots match id AND name; "
          f"active={got.get('active')}; no product-db reference")

if __name__ == '__main__':
    main(sys.argv[1], apply='--apply' in sys.argv)
