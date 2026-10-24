#!/usr/bin/env python3
"""fetch_journals.py: download the 467 Texas House Journal PDFs for 2019-2025 listed in journals.csv, check each
against its sha256, and extract its text layer with `pdftotext -layout` (poppler; no OCR) into text/.

415 come from the Texas Legislative Reference Library. The other 52 were on journals.house.texas.gov, which no longer
serves them; they come from the Internet Archive capture in download_url (official_url is the original address).
Files already present with the right hash are not downloaded again, so the script can be rerun after an interruption.
Requests are spaced a few seconds apart. Needs curl and poppler-utils (pdftotext) on the PATH.
Usage: python checks/journal/fetch_journals.py"""
import csv, hashlib, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PAUSE = 3


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    os.makedirs(os.path.join(HERE, 'pdf'), exist_ok=True); os.makedirs(os.path.join(HERE, 'text'), exist_ok=True)
    rows = list(csv.DictReader(open(os.path.join(HERE, 'journals.csv'))))
    bad = []
    for i, r in enumerate(rows, 1):
        pdf = os.path.join(HERE, 'pdf', r['file'])
        if not (os.path.exists(pdf) and sha256(pdf) == r['sha256']):
            got = subprocess.run(['curl', '-sSfL', '--retry', '3', '--max-time', '300', '-A', 'Mozilla/5.0 (reproduction script)',
                                  '-o', pdf + '.part', r['download_url']])
            if got.returncode == 0: os.replace(pdf + '.part', pdf)
            time.sleep(PAUSE)
        if not os.path.exists(pdf) or sha256(pdf) != r['sha256']:
            bad.append(r['file']); print(f"{i}/{len(rows)} {r['file']}: missing, or sha256 differs from journals.csv", file=sys.stderr); continue
        txt = os.path.join(HERE, 'text', r['file'][:-4] + '.txt')
        if not os.path.exists(txt):
            subprocess.run(['pdftotext', '-layout', pdf, txt], check=True)
    print(f'{len(rows) - len(bad)} of {len(rows)} Journal PDFs present and verified' + (f'; {len(bad)} differ: {bad}' if bad else ''))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
