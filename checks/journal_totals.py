#!/usr/bin/env python3
"""journal_totals.py: for every split vote, the Yea and Nay totals in LegiScan against the totals printed in the official
Texas House Journal. Writes checks/journal_totals.csv with the Journal's sentence, page, PDF link and PDF sha256, so any
row can be checked by opening the Journal.

Reads checks/journal/records.csv, the Journal record votes parsed by checks/journal/journal_members.py (run
checks/journal/fetch_journals.py and that script first). Usage: python checks/journal_totals.py [records.csv]"""
import collections, csv, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from make_figure import HERE, load

CODE = {'86th Legislature Regular Session': '86R', '87th Legislature Regular Session': '87R', '87th Legislature 1st Special': '871',
        '87th Legislature 2nd Special Session': '872', '87th Legislature 3rd Special Session': '873', '88th Legislature Regular Session': '88R',
        '88th Legislature 1st Special Session': '881', '88th Legislature 2nd Special Session': '882', '88th Legislature 3rd Special Session': '883',
        '88th Legislature 4th Special Session': '884', '89th Legislature Regular Session': '89R', '89th Legislature 1st Special Session': '891',
        '89th Legislature 2nd Special Session': '892'}


def main():
    csv.field_size_limit(10 ** 9)
    J = collections.defaultdict(list)
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'checks', 'journal', 'records.csv')
    for r in csv.DictReader(open(src)):
        J[(r['session'], r['rv'])].append(r)
    _, _, splits = load()
    count = collections.Counter()
    with open(os.path.join(HERE, 'checks', 'journal_totals.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['session', 'record', 'legiscan_yea', 'legiscan_nay', 'journal_yea', 'journal_nay', 'totals_agree', 'note',
                    'journal_motion', 'journal_page', 'journal_pdf_url', 'journal_pdf_sha256'])
        for s in splits:
            code = CODE[s['session']]
            y = sum(v == 'Yea' for v in s['votes'].values()); n = sum(v == 'Nay' for v in s['votes'].values())
            js = J.get((code, s['record']), [])
            j = next((x for x in js if (x['yea'], x['nay']) == (str(y), str(n))), js[0] if js else None)
            jy, jn, note = (j['yea'], j['nay'], '') if j else ('', '', 'no Journal record found')
            if j and not jy:   # the printed sentence lacks a number the parser expects; read the two totals from it
                m = re.search(r'\(Record \d+\):\s*(\d+) Yeas?,\s*(\d+) Nays?', j['motion_verbatim'])
                if m: jy, jn, note = m[1], m[2], 'totals read from the printed sentence, which gives no present-not-voting number'
            agree = (jy, jn) == (str(y), str(n))
            count[agree] += 1
            w.writerow([code, s['record'], y, n, jy, jn, 'yes' if agree else 'no', note, j['motion_verbatim'] if j else '',
                        j['journal_page'] if j else '', j['source_url'] if j else '', j['source_sha256'] if j else ''])
    print(f'{len(splits)} split votes: totals agree on {count[True]}, differ on {count[False]}')


if __name__ == '__main__':
    main()
