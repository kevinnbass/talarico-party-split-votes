#!/usr/bin/env python3
"""journal_members.py: every member's vote on every split vote, LegiScan against the names printed in the Texas House
Journal, and the chart recomputed from the Journal alone. Run checks/journal/fetch_journals.py first (it downloads the
Journal PDFs and extracts their text layers). Writes checks/journal_member_disagreements.csv, checks/journal_rates.csv,
checks/journal_members_summary.json and checks/journal/records.csv (the parsed Journal record votes, which
checks/journal_totals.py reads). Usage: python checks/journal/journal_members.py"""
import sys, types, csv, json, re, glob, zipfile, collections, unicodedata
sys.dont_write_bytecode = True
import os
JDIR = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(JDIR) + '/'
LS = os.path.join(os.path.dirname(HERE.rstrip('/')), 'data', 'legiscan')
TAL = 20246
SPEAKER = {'86R': 'Dennis Bonnen'}
SPEAKER.update({c: 'Dade Phelan' for c in ['87R', '871', '872', '873', '88R', '881', '882', '883', '884']})
SPEAKER.update({c: 'Dustin Burrows' for c in ['89R', '891', '892']})   # checked: each is the LegiScan member who is NV on ~all roll calls of that zip

# ---------- 1. Journal parse (VR1b-codex parser, unmodified source + one extra field) ----------
sys.path.insert(0, JDIR)
import journal_parser as pj
jrec = {}          # (session, rv) -> row with members (first occurrence that has Yea/Nay lists)
occ = collections.Counter()
for r in csv.DictReader(open(os.path.join(JDIR, 'journals.csv'))):
    r.update(path='pdf/' + r['file'], text_path='text/' + r['file'][:-4] + '.txt', url=r['official_url'])
    rows, _ = pj.parse_doc(pj.Doc(r))
    for x in rows:
        k = (x['session'], x['rv']); occ[k] += 1
        has = bool(x['members'].get('Yeas') or x['members'].get('Nays'))
        if k not in jrec or (has and not (jrec[k]['members'].get('Yeas') or jrec[k]['members'].get('Nays'))):
            jrec[k] = x
print('journal records parsed:', len(jrec), 'with Yea/Nay lists:', sum(1 for x in jrec.values() if x['members'].get('Yeas') or x['members'].get('Nays')))

# ---------- 2. LegiScan, exactly the reference rule ----------
man = {m['file']: m['session'] for m in json.load(open(os.path.join(LS, 'MANIFEST.json')))}
def code(name):
    n = re.match(r'(\d+)', name)[1]
    if 'Regular' in name: return n + 'R'
    return n + re.search(r'(\d)(?:st|nd|rd|th) Special', name)[1]
zcode = {f: code(s) for f, s in man.items()}
people = {}            # pid -> person dict (latest)
party = {}             # running party map (reference rule)
party_snap = {}        # zip -> party map as of that zip
pool = {}              # zip -> {pid: person}  (people appearing in a House roll call of that zip)
pers_zip = {}          # zip -> {pid: person}
ls_rc = {}             # (session, rv) -> (zip, roll_call dict) first seen
ls_all = []            # in order
seen = set(); splits = []   # list of dict(key, zip, rc, rs, ds)
for zp in sorted(glob.glob(os.path.join(LS, 'TX_*.zip'))):
    zf = zp.split('/')[-1]; sess = zcode[zf]
    z = zipfile.ZipFile(zp)
    pers_zip[zf] = {}
    for n in z.namelist():
        if '/people/' in n:
            p = json.loads(z.read(n))['person']; people[p['people_id']] = p; party[p['people_id']] = p['party']; pers_zip[zf][p['people_id']] = p
    party_snap[zf] = dict(party)
    pool[zf] = {}
    for n in z.namelist():
        if '/vote/' not in n: continue
        r = json.loads(z.read(n))['roll_call']
        if r['chamber'] != 'H': continue
        for v in r['votes']: pool[zf][v['people_id']] = pers_zip[zf].get(v['people_id']) or people.get(v['people_id'])
        m = re.findall(r'RV#\s*(\d+)', r['desc']); key = (zp, m[-1] if m else r['roll_call_id'])
        if key in seen: continue
        seen.add(key)
        ls_all.append(dict(zip=zf, sess=sess, rv=m[-1] if m else None, rc=r))
        c = collections.Counter((party.get(v['people_id']), v['vote_text']) for v in r['votes'])
        rs = 'Yea' if c[('R', 'Yea')] > c[('R', 'Nay')] else 'Nay' if c[('R', 'Nay')] > c[('R', 'Yea')] else None
        ds = 'Yea' if c[('D', 'Yea')] > c[('D', 'Nay')] else 'Nay' if c[('D', 'Nay')] > c[('D', 'Yea')] else None
        if rs and ds and rs != ds: splits.append(dict(zip=zf, sess=sess, rv=m[-1] if m else None, rc=r, rs=rs, ds=ds))
final_party = dict(party)
pname = {p: d['name'] for p, d in people.items()}
print('LegiScan House record votes (unique zip,RV#):', len(ls_all), ' split:', len(splits))
vt_values = collections.Counter(v['vote_text'] for a in ls_all for v in a['rc']['votes']); print('LegiScan vote_text values:', dict(vt_values))

# ---------- 3. Name mapping ----------
def nk(s): return re.sub(r'[^a-z]', '', unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower())
def surn(p):
    """(full_keys, token_keys). Surname text = LegiScan `name` minus first_name (which is what the Journal prints);
    last_name is also accepted when it is contained in that text. If last_name contradicts the name field
    (LegiScan 24094: name 'Christian Manuel', last_name 'Hayes') only the name-field surname is used and the person is logged."""
    full = p['name']; fn = p['first_name']
    txt = full[len(fn):] if full.startswith(fn) else p['last_name']
    kt = nk(txt); kl = nk(p['last_name'])
    if kl and kl in kt: fulls = {kt, kl}; text = txt + ' ' + p['last_name']
    else:
        fulls = {kt}; text = txt
        if kl: LSNAME_CONFLICT[p['people_id']] = (p['name'], p['last_name'])
    toks = {nk(t) for t in re.split(r'[\s\-]+', text) if nk(t)}
    return fulls, toks
LSNAME_CONFLICT = {}
def clean_name(n):
    if re.match(r'Mr\. Speaker', n): return 'Mr. Speaker'
    n = re.sub(r',i(?=[A-Z])', ', ', n)                    # text-layer spacer artifact "Davis,iS"
    n = re.sub(r'^\d+\s+', '', n)                           # leading page-number artifact
    n = re.split(r'\.\s', n)[0]                             # trailing sentence glued onto the last name of a list
    n = re.sub(r'\(C\)$', '', n.strip()).strip()
    return n.rstrip('.').strip()
def initials_ok(p, letters):
    """returns 2 = every printed initial confirmed, 1 = compatible but a middle initial unknown, 0 = conflict"""
    fi = {nk(p['first_name'])[:1], nk(p['nickname'])[:1]} - {''}
    if letters[0] not in fi: return 0
    if len(letters) == 1: return 2
    mid = nk(p['middle_name'])[:1]
    if mid: return 2 if letters[1] == mid and len(letters) == 2 else (2 if letters[1] == mid else 0)
    return 1
mapcache = {}
def map_name(sess, zf, raw):
    """-> (pid or None, method/reason, candidate list)"""
    ck = (zf, raw)
    if ck in mapcache: return mapcache[ck]
    n = clean_name(raw); cand = []
    if n == 'Mr. Speaker':
        c = [pid for pid, p in pool[zf].items() if p and p['name'] == SPEAKER[sess]]
        res = (c[0], 'speaker_title', c) if len(c) == 1 else (None, 'unmapped:speaker', c)
    else:
        sur, _, dis = n.partition(',')
        key = nk(sur); letters = [c.lower() for c in dis if c.isalpha()]
        S = {pid: surn(p) for pid, p in pool[zf].items() if p}
        exact = [pid for pid, (f, t) in S.items() if key in f]
        tok = [pid for pid, (f, t) in S.items() if key in t]
        if not letters:
            cand = exact or tok; how = 'surname' if exact else 'surname_token'
            if not cand: res = (None, 'unmapped:no_surname_match', [])
            elif len(cand) == 1: res = (cand[0], how, cand)
            else: res = (None, 'ambiguous:' + ','.join(f'{c}={pname[c]}' for c in cand), cand)
        else:
            cand = sorted(set(exact) | set(tok))
            if not cand: res = (None, 'unmapped:no_surname_match', [])
            else:
                sc = {pid: initials_ok(pool[zf][pid], letters) for pid in cand}
                strict = [p for p, v in sc.items() if v == 2]; loose = [p for p, v in sc.items() if v == 1]
                if len(strict) == 1: res = (strict[0], 'surname+initial', cand)
                elif not strict and len(loose) == 1: res = (loose[0], 'surname+initial_middle_unknown', cand)
                elif not strict and not loose: res = (None, 'unmapped:initial_conflict', cand)
                else: res = (None, 'ambiguous:' + ','.join(f'{c}={pname[c]}' for c in strict + loose), strict + loose)
    mapcache[ck] = res; return res
LAB = {'Yeas': 'Yea', 'Nays': 'Nay', 'Present, not voting': 'NV', 'Absent': 'Absent', 'Absent, Excused': 'Absent',
       'Absent, Excused, Committee Meeting': 'Absent', 'Present': 'Present'}
elim = collections.Counter()
def jpositions(x, zf):
    """-> ({pid: set(positions)}, [(raw,label,reason)]). Second pass: a bare surname that matches several members
    is resolved only if every candidate but one is already mapped elsewhere in the same record's lists."""
    pos = collections.defaultdict(set); bad = []; pending = []
    for lab, names in x['members'].items():
        for raw in names:
            pid, why, cand = map_name(x['session'], zf, raw)
            if pid is None:
                (pending if why.startswith('ambiguous') else bad).append((raw, lab, why, cand))
            else: pos[pid].add(LAB[lab])
    assigned = set(pos)
    for raw, lab, why, cand in pending:
        rem = [c for c in cand if c not in assigned]
        if len(rem) == 1: pos[rem[0]].add(LAB[lab]); assigned.add(rem[0]); elim['resolved_by_elimination_in_record'] += 1
        else: bad.append((raw, lab, why, cand))
    return pos, [(r, l, w) for r, l, w, c in bad]

# ---------- 4. Compare on the 2,642 split votes ----------
sess_zip = {}
for f, c in zcode.items(): sess_zip[c] = f
matched = 0; unmatched = []; compared = collections.Counter(); dis = []; unm_names = collections.defaultdict(list)
tally_mismatch = []; jdouble = []; mapmethods = collections.Counter(); amb = {}
for s in splits:
    k = (s['sess'], s['rv']); x = jrec.get(k)
    if not x or not (x['members'].get('Yeas') or x['members'].get('Nays')): unmatched.append((k, 'no journal member lists')); continue
    matched += 1
    jp, bad = jpositions(x, s['zip'])
    for raw, lab, why in bad: unm_names[(s['sess'], raw, why)].append(s['rv'])
    ly = sum(v['vote_text'] == 'Yea' for v in s['rc']['votes']); ln = sum(v['vote_text'] == 'Nay' for v in s['rc']['votes'])
    jy = sum('Yea' in v for v in jp.values()) + sum(1 for r_, l_, w_ in bad if l_ == 'Yeas'); jn = sum('Nay' in v for v in jp.values()) + sum(1 for r_, l_, w_ in bad if l_ == 'Nays')
    printed = (int(x['yea']) if x['yea'] != '' else None, int(x['nay']) if x['nay'] != '' else None)
    if printed != (ly, ln): tally_mismatch.append((k, 'legiscan', (ly, ln), 'journal printed', printed, 'journal names', (len(x['members'].get('Yeas', [])), len(x['members'].get('Nays', [])))))
    lsp = {v['people_id']: v['vote_text'] for v in s['rc']['votes']}
    for pid in sorted(set(lsp) | set(jp)):
        a = lsp.get(pid, '(not listed)'); b = jp.get(pid)
        if b is None: bs = '(not printed)'
        else: bs = '|'.join(sorted(b))
        compared['all'] += 1
        core = a in ('Yea', 'Nay') or bs in ('Yea', 'Nay') or ('Yea' in (b or ())) or ('Nay' in (b or ()))
        compared['yea_nay_involving'] += core
        compared['both_yea_nay'] += (a in ('Yea', 'Nay') and bs in ('Yea', 'Nay'))
        norm_ok = (a == bs) or (a == 'Absent' and bs == '(not printed)') and False
        if a != bs:
            dis.append(dict(session=s['sess'], rv=s['rv'], date=x['date'], people_id=pid, member=pname.get(pid, ''), party=s['rc'] and party_snap[s['zip']].get(pid, ''),
                            legiscan_position=a, journal_position=bs, journal_page=x['journal_page'], kind='yea_nay' if core else 'other_status',
                            note=x['parse_notes']))
        else: compared['agree'] += 1
# disagreement bookkeeping
for d in dis: pass
yn_dis = [d for d in dis if d['kind'] == 'yea_nay']
cols = ['session', 'rv', 'date', 'people_id', 'member', 'party', 'legiscan_position', 'journal_position', 'journal_page', 'kind', 'note']
with open(HERE + 'journal_member_disagreements.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(dis)

# ---------- 5. Recompute chart from the Journal ----------
def chart(universe):
    """universe: iterable of (session, rv, zip). party sides from Journal lists, party as-of-zip from LegiScan."""
    tot = collections.Counter(); wr = collections.Counter(); splitkeys = []; excluded = collections.Counter()
    for sess, rv, zf in universe:
        x = jrec[(sess, rv)]
        jp, bad = jpositions(x, zf); ps = party_snap[zf]
        yn = {pid: (next(iter(v)) if len(v) == 1 else None) for pid, v in jp.items()}
        c = collections.Counter((ps.get(pid), p) for pid, p in yn.items() if p in ('Yea', 'Nay'))
        rs = 'Yea' if c[('R', 'Yea')] > c[('R', 'Nay')] else 'Nay' if c[('R', 'Nay')] > c[('R', 'Yea')] else None
        ds = 'Yea' if c[('D', 'Yea')] > c[('D', 'Nay')] else 'Nay' if c[('D', 'Nay')] > c[('D', 'Yea')] else None
        if not rs or not ds or rs == ds: continue
        splitkeys.append((sess, rv))
        for pid, p in yn.items():
            if p in ('Yea', 'Nay'): tot[pid] += 1; wr[pid] += (p == rs)
        for pid, v in jp.items():
            if len(v) > 1 and (v & {'Yea', 'Nay'}): excluded[(sess, rv, pid)] += 1
    return tot, wr, splitkeys, excluded
def rates(tot, wr):
    return sorted(((wr[p] / tot[p], p) for p in tot if final_party.get(p) in ('D', 'R') and tot[p] >= 500))
def talarico(rows, tot, wr):
    t = [x for x, p in rows if p == TAL]
    if not t: return None
    r = t[0]
    return dict(with_r=wr[TAL], yea_nay=tot[TAL], rate=round(r, 6), charted=len(rows),
                charted_D=sum(final_party[p] == 'D' for _, p in rows), charted_R=sum(final_party[p] == 'R' for _, p in rows),
                dems_higher=sum(1 for x, p in rows if final_party[p] == 'D' and x > r), all_higher=sum(1 for x, p in rows if x > r),
                dems_equal=sum(1 for x, p in rows if final_party[p] == 'D' and x == r and p != TAL))
# universe A: every Journal record with Yea/Nay lists. universe B: only records that LegiScan also has as House record votes.
ls_keys = {(a['sess'], a['rv']): a['zip'] for a in ls_all if a['rv']}
UA = [(s, rv, sess_zip[s]) for (s, rv), x in sorted(jrec.items(), key=lambda kv: (kv[0][0], int(kv[0][1]))) if x['members'].get('Yeas') or x['members'].get('Nays')]
UB = [(s, rv, zf) for (s, rv, zf) in UA if (s, rv) in ls_keys]
# LegiScan-recomputed baseline (reference), for comparison
ls_tot = collections.Counter(); ls_wr = collections.Counter()
for s in splits:
    for v in s['rc']['votes']:
        if v['vote_text'] in ('Yea', 'Nay'): ls_tot[v['people_id']] += 1; ls_wr[v['people_id']] += (v['vote_text'] == s['rs'])
ls_rows = rates(ls_tot, ls_wr)
resA = chart(UA); resB = chart(UB)
rowsA = rates(resA[0], resA[1]); rowsB = rates(resB[0], resB[1])
lsset = {(s['sess'], s['rv']) for s in splits}
def cmpsets(res):
    js = set(res[2]); return dict(journal_split=len(js), same=len(js & lsset), only_journal=sorted(js - lsset, key=lambda k: (k[0], int(k[1]))), only_legiscan=sorted(lsset - js, key=lambda k: (k[0], int(k[1]))))
cA, cB = cmpsets(resA), cmpsets(resB)
with open(HERE + 'journal_rates.csv', 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['name', 'people_id', 'party', 'with_r', 'yea_nay', 'rate', 'legiscan_with_r', 'legiscan_yea_nay', 'legiscan_rate', 'in_legiscan_chart'])
    lsr = {p: x for x, p in ls_rows}
    for x, p in rowsA:
        w.writerow([pname[p], p, final_party[p], resA[1][p], resA[0][p], f'{x:.4f}', ls_wr[p], ls_tot[p], f'{ls_wr[p]/ls_tot[p]:.4f}' if ls_tot[p] else '', p in lsr])
    for x, p in ls_rows:
        if p not in {q for _, q in rowsA}: w.writerow([pname[p], p, final_party[p], resA[1][p], resA[0][p], f'{resA[1][p]/resA[0][p]:.4f}' if resA[0][p] else '', ls_wr[p], ls_tot[p], f'{x:.4f}', True])
rate_diffs = sum(1 for p in set(resA[0]) | set(ls_tot) if (resA[1][p], resA[0][p]) != (ls_wr[p], ls_tot[p]))
unm_flat = {f'{k[0]} | {k[1]} | {k[2]}': dict(n_records=len(v), first_rvs=v[:5]) for k, v in unm_names.items()}
allbad = collections.Counter()
for sess_, rv_, zf_ in UA:
    for raw, lab, why in jpositions(jrec[(sess_, rv_)], zf_)[1]: allbad[(sess_, raw, why)] += 1
def diffmembers(res): return sorted(f"{pname[p]} ({p}): journal {res[1][p]}/{res[0][p]} vs legiscan {ls_wr[p]}/{ls_tot[p]}" for p in set(res[0]) | set(ls_tot) if (res[1][p], res[0][p]) != (ls_wr[p], ls_tot[p]))
dB = diffmembers(resB)
summary = dict(
    extra_checks=dict(universeB_members_with_different_counts=dB, universeB_charted_set_identical_to_legiscan=({p for _, p in rowsB} == {p for _, p in ls_rows}), universeA_charted_set_identical_to_legiscan=({p for _, p in rowsA} == {p for _, p in ls_rows}),
                      journal_records_without_member_lists=sum(1 for x in jrec.values() if not (x['members'].get('Yeas') or x['members'].get('Nays'))),
                      journal_records_with_lists_not_in_legiscan_house_votes=len(UA) - len(UB),
                      unmapped_or_ambiguous_names_in_all_journal_lists={f'{k[0]} | {k[1]} | {k[2]}': v for k, v in allbad.items()}),
    legiscan=dict(house_record_votes=len(ls_all), split_votes=len(splits), charted=len(ls_rows), charted_D=sum(final_party[p] == 'D' for _, p in ls_rows), charted_R=sum(final_party[p] == 'R' for _, p in ls_rows), talarico=talarico(ls_rows, ls_tot, ls_wr)),
    split_records_matched_to_journal=matched, split_records_unmatched=[dict(session=k[0], rv=k[1], why=w) for k, w in unmatched],
    member_votes_compared=dict(compared), disagreements_total=len(dis), disagreements_yea_nay=len(yn_dis),
    disagreements_other_status=len(dis) - len(yn_dis),
    disagreement_pair_counts={f"{a} -> {b}": n for (a, b), n in collections.Counter((d['legiscan_position'], d['journal_position']) for d in dis).most_common()},
    tally_mismatch_records=[dict(session=k[0][0], rv=k[0][1], detail=str(k[1:])) for k in tally_mismatch],
    unmapped_or_ambiguous_names_on_split_votes=unm_flat,
    resolved_by_elimination_in_record=elim['resolved_by_elimination_in_record'], legiscan_name_field_conflicts={str(k): v for k, v in LSNAME_CONFLICT.items()},
    non_plain_name_mappings=sorted(f"{zf}: {raw!r} -> {pid} {pname[pid]} [{m}]" for (zf, raw), (pid, m, c_) in mapcache.items() if pid is not None and m not in ('surname', 'speaker_title')),
    name_mapping_methods=dict(collections.Counter(m for (zf, raw), (pid, m, c_) in mapcache.items() if pid is not None)),
    journal_recompute_all_journal_records=dict(records_used=len(UA), split_votes=len(resA[2]), vs_legiscan_split_set=dict(journal_split=cA['journal_split'], same=cA['same'], only_journal=len(cA['only_journal']), only_legiscan=len(cA['only_legiscan']), only_journal_list=[f'{a}/{b}' for a, b in cA['only_journal']], only_legiscan_list=[f'{a}/{b}' for a, b in cA['only_legiscan']]),
                                              charted=len(rowsA), charted_D=sum(final_party[p] == 'D' for _, p in rowsA), charted_R=sum(final_party[p] == 'R' for _, p in rowsA), talarico=talarico(rowsA, resA[0], resA[1]),
                                              members_whose_counts_differ_from_legiscan=rate_diffs, member_double_listed_yea_nay=len(resA[3])),
    journal_recompute_legiscan_universe_only=dict(records_used=len(UB), split_votes=len(resB[2]), vs_legiscan_split_set=dict(journal_split=cB['journal_split'], same=cB['same'], only_journal_list=[f'{a}/{b}' for a, b in cB['only_journal']], only_legiscan_list=[f'{a}/{b}' for a, b in cB['only_legiscan']]),
                                                  charted=len(rowsB), charted_D=sum(final_party[p] == 'D' for _, p in rowsB), charted_R=sum(final_party[p] == 'R' for _, p in rowsB), talarico=talarico(rowsB, resB[0], resB[1])),
)
json.dump(summary, open(HERE + 'journal_members_summary.json', 'w'), indent=1, default=str)
with open(os.path.join(JDIR, 'records.csv'), 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['session', 'rv', 'date', 'motion_verbatim', 'yea', 'nay', 'journal_page', 'source_url', 'source_sha256'])
    for (sess_, rv_), x in sorted(jrec.items(), key=lambda kv: (kv[0][0], int(kv[0][1]))):
        w.writerow([sess_, rv_, x['date'], x['motion_verbatim'], x['yea'], x['nay'], x['journal_page'], x['source_url'], x['source_sha256']])
print(json.dumps(summary, indent=1, default=str))
