#!/usr/bin/env python3
"""robustness.py: does Talarico's position depend on the choices in make_figure.py? Recomputes his rate and rank with the
cutoff changed, one Legislature at a time, and with procedural or non-final votes removed. Writes output/robustness.csv.
Motion types come from LegiScan's one-line description of each vote (the House Journal is the authority on the motion)."""
import csv, os
from make_figure import FOCUS, HERE, load, rates


def kind(desc):
    d = desc.lower()
    if 'statement' in d: return 'statement_of_vote'
    if 'conference' in d or 'concur' in d: return 'final_concurrence'
    if 'table' in d: return 'motion_to_table'
    if 'amend' in d: return 'amendment'
    if any(k in d for k in ('postpone', 'previous question', 'reconsider', 'point of order', 'suspend', 'motion', 'adjourn', 'recommit', 'appeal', 'permission')): return 'procedural'
    if '3rd' in d or 'third' in d or 'passed' in d or 'failed to pass' in d or 'adopted' in d or 'failed' in d: return 'passage'
    if '2nd' in d or 'second' in d or 'engross' in d: return 'second_reading'
    return 'unlabelled'


def row(label, splits, party, min_votes):
    rows = rates(splits, party, min_votes)
    me = next(r for r in rows if r['people_id'] == FOCUS)
    dems = [r for r in rows if r['party'] == 'D']
    return dict(check=label, split_votes=len(splits), min_votes=min_votes, talarico=f"{100 * me['rate']:.1f}% ({me['with_r']} of {me['votes']:,})",
                democrats=len(dems), democrats_higher=sum(r['rate'] > me['rate'] for r in dems),
                democrats_lower=sum(r['rate'] < me['rate'] for r in dems), members=len(rows),
                members_higher=sum(r['rate'] > me['rate'] for r in rows))


def main():
    name, party, splits = load()
    out = [row('As charted', splits, party, 500)]
    for n in (100, 250, 1000):
        out.append(row(f'Cutoff {n} votes instead of 500', splits, party, n))
    for leg in ('86th', '87th', '88th', '89th'):
        out.append(row(f'{leg} Legislature only', [s for s in splits if s['session'].startswith(leg)], party, 100))
    out.append(row('Final passage and conference/concurrence votes only', [s for s in splits if kind(s['motion']) in ('passage', 'final_concurrence')], party, 150))
    out.append(row('Procedural motions, motions to table and statements removed',
                   [s for s in splits if kind(s['motion']) not in ('procedural', 'motion_to_table', 'statement_of_vote')], party, 300))
    with open(os.path.join(HERE, 'output', 'robustness.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    for r in out:
        print(f"{r['check']}: {r['split_votes']:,} split votes, cutoff {r['min_votes']}; Talarico {r['talarico']}; "
              f"{r['democrats_higher']} of {r['democrats']} Democrats higher, {r['democrats_lower']} lower; {r['members_higher']} of {r['members']} members higher")


if __name__ == '__main__':
    main()
