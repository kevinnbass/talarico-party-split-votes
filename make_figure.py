#!/usr/bin/env python3
"""make_figure.py: how often each Texas House member voted with the Republican majority when the parties split, 2019-2025.

Reads the LegiScan session datasets in data/legiscan/ (MANIFEST.json lists each file with its sha256), and writes
data/house_split_votes.csv and output/talarico_party_split.png. Rule, in order:
  1. House record votes only, one per session and record number (LegiScan sometimes files one record vote under several
     bills; the copies are skipped).
  2. Each party's side is the way most of its members voted, counting Yea and Nay only. A tie inside a party drops the vote.
  3. A split vote is one where the two parties' sides are opposite.
  4. A member's rate is the split votes they cast with the Republican side, over their Yea and Nay votes on split votes.
     Absent and present-not-voting are left out.
  5. Members with fewer than 500 such votes are left out. Party is the one in the latest session that lists the member.
Usage: python make_figure.py [--repo-url URL]"""
import collections, csv, glob, json, os, re, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, 'data', 'legiscan')
MIN_VOTES = 500
FOCUS = 20246   # LegiScan people_id for James Talarico


def load():
    """Return (name, party, splits): one dict per split vote with session, record, motion (LegiScan's description), rs (the
    Republican side) and votes ({people_id: 'Yea'|'Nay'})."""
    session = {m['file']: m['session'] for m in json.load(open(os.path.join(RAW, 'MANIFEST.json')))}
    name, party, seen, splits = {}, {}, set(), []
    for zp in sorted(glob.glob(os.path.join(RAW, 'TX_*.zip'))):
        z = zipfile.ZipFile(zp)
        for n in z.namelist():
            if '/people/' in n:
                p = json.loads(z.read(n))['person']; name[p['people_id']] = p['name']; party[p['people_id']] = p['party']
        for n in z.namelist():
            if '/vote/' not in n: continue
            r = json.loads(z.read(n))['roll_call']
            if r['chamber'] != 'H': continue
            m = re.findall(r'RV#\s*(\d+)', r['desc']); key = (zp, m[-1] if m else r['roll_call_id'])
            if key in seen: continue
            seen.add(key)
            c = collections.Counter((party.get(v['people_id']), v['vote_text']) for v in r['votes'])
            rs = 'Yea' if c[('R', 'Yea')] > c[('R', 'Nay')] else 'Nay' if c[('R', 'Nay')] > c[('R', 'Yea')] else None
            ds = 'Yea' if c[('D', 'Yea')] > c[('D', 'Nay')] else 'Nay' if c[('D', 'Nay')] > c[('D', 'Yea')] else None
            if not rs or not ds or rs == ds: continue
            splits.append(dict(session=session[os.path.basename(zp)], record=key[1], motion=r['desc'], rs=rs,
                               votes={v['people_id']: v['vote_text'] for v in r['votes'] if v['vote_text'] in ('Yea', 'Nay')}))
    return name, party, splits


def rates(splits, party, min_votes=MIN_VOTES):
    """Members with min_votes+ split Yea/Nay votes, lowest rate first: dicts of people_id, party, with_r, votes, rate."""
    with_r, tot = collections.Counter(), collections.Counter()
    for s in splits:
        for p, x in s['votes'].items():
            tot[p] += 1; with_r[p] += x == s['rs']
    rows = [dict(people_id=p, party=party[p], with_r=with_r[p], votes=tot[p], rate=with_r[p] / tot[p])
            for p in tot if tot[p] >= min_votes and party.get(p) in ('D', 'R')]
    return sorted(rows, key=lambda r: r['rate'])


def draw(rows, name, n_splits, path, repo_url):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    if any('Inter' in f.name for f in font_manager.fontManager.ttflist):
        plt.rcParams['font.family'] = 'Inter'
    INK, SOFT, GRID = '#1a1a1a', '#5f5f5f', '#e6e6e6'
    HUE = {'D': '#2f7ad9', 'R': '#e0605f'}
    me = next(r for r in rows if r['people_id'] == FOCUS)
    above = sum(r['rate'] > me['rate'] for r in rows)

    fig = plt.figure(figsize=(8, 4.5), dpi=200)
    ax = fig.add_axes([0.075, 0.25, 0.9, 0.53])
    xs = range(len(rows))
    ax.bar(xs, [100 * r['rate'] for r in rows], width=0.82, align='edge',
           color=[INK if r is me else HUE[r['party']] for r in rows], linewidth=0, zorder=2)
    ax.set_xlim(-0.5, len(rows) + 0.5); ax.set_ylim(0, 100)
    ax.set_yticks([0, 25, 50, 75, 100]); ax.set_yticklabels([f'{v}%' for v in (0, 25, 50, 75, 100)], fontsize=8.5, color=SOFT)
    ax.set_xticks([]); ax.tick_params(axis='y', length=0, pad=6)
    ax.grid(axis='y', color=GRID, linewidth=0.8, zorder=0)
    for s in ('top', 'right', 'left'): ax.spines[s].set_visible(False)
    ax.spines['bottom'].set_color('#b5b5b5')

    # party brackets under the bars
    for p, word in (('D', 'Democrats'), ('R', 'Republicans')):
        ix = [i for i, r in enumerate(rows) if r['party'] == p]
        lo, hi = min(rows[i]['rate'] for i in ix), max(rows[i]['rate'] for i in ix)
        a, b = min(ix), max(ix) + 1
        ax.plot([a + 0.3, b - 0.3], [-5, -5], color=HUE[p], linewidth=2.6, clip_on=False, solid_capstyle='butt')
        ax.text((a + b) / 2, -11, f'{len(ix)} {word}: {100 * lo:.1f}% to {100 * hi:.1f}%', ha='center', va='top', fontsize=8.5, color=INK)

    # Talarico
    mi = rows.index(me) + 0.41
    ax.plot([mi, mi], [100 * me['rate'] + 1.2, 76], color=INK, linewidth=0.8, zorder=3)
    ax.text(mi + 2.2, 85, f"{name[FOCUS].split()[-1]} {100 * me['rate']:.1f}%", fontsize=10, fontweight='bold', color=INK, va='bottom')
    ax.text(mi + 2.2, 84, f"{me['with_r']} of {me['votes']:,} split votes", fontsize=8.5, color=SOFT, va='top')

    fig.text(0.04, 0.925, f"{name[FOCUS].split()[-1]} sided with Republicans less often than {above} of {len(rows)} House members",
             fontsize=13.5, fontweight='bold', color=INK)
    fig.text(0.04, 0.87, f'Share of party-split Texas House votes cast with the Republican majority, 2019–2025', fontsize=9.5, color=SOFT)
    fig.text(0.04, 0.075, f'Each bar is one member with {MIN_VOTES}+ such votes, lowest to highest. A split vote ({n_splits:,} in all): '
             'most Republicans and most Democrats voted on opposite sides.', fontsize=7, color=SOFT)
    fig.text(0.04, 0.035, 'Data: LegiScan, Texas House record votes, 86th–89th Legislatures (CC BY 4.0).'
             + (f'  Method and code: {repo_url}' if repo_url else ''), fontsize=7, color=SOFT)
    fig.savefig(path, dpi=200, facecolor='white')


def main():
    repo_url = sys.argv[sys.argv.index('--repo-url') + 1] if '--repo-url' in sys.argv else ''
    name, party, splits = load()
    rows = rates(splits, party)
    with open(os.path.join(HERE, 'data', 'house_split_votes.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['name', 'people_id', 'party', 'with_republican_majority', 'split_votes', 'rate'])
        for r in rows: w.writerow([name[r['people_id']], r['people_id'], r['party'], r['with_r'], r['votes'], f"{r['rate']:.4f}"])
    os.makedirs(os.path.join(HERE, 'output'), exist_ok=True)
    draw(rows, name, len(splits), os.path.join(HERE, 'output', 'talarico_party_split.png'), repo_url)
    me = next(r for r in rows if r['people_id'] == FOCUS)
    print(f"{len(splits)} split votes; {len(rows)} members ({sum(r['party'] == 'D' for r in rows)} D, {sum(r['party'] == 'R' for r in rows)} R); "
          f"Talarico {me['with_r']}/{me['votes']} = {100 * me['rate']:.1f}%; higher: {sum(r['rate'] > me['rate'] for r in rows)} members, "
          f"{sum(r['rate'] > me['rate'] for r in rows if r['party'] == 'D')} Democrats")


if __name__ == '__main__':
    main()
