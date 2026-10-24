#!/usr/bin/env python3
"""journal_parser.py: reads the record votes in the Texas House Journal text layers (pdftotext -layout, no OCR).

Copied from the parser that matched all 10,460 LegiScan record votes to the Journal, with three changes: ROOT is this
folder, DATA (that project's own record of Talarico's votes, used only by main()) is not used here, and each parsed
record also returns its printed member lists (row['members']). journal_members.py imports Doc and parse_doc from it;
main() belongs to the original project and is not run here.

Original description follows.
Parse saved House Journal text layers, without OCR or imputing missing records.

The CSV input is a comparison target, never a source of journal vote positions.
Text-layer spacer artifacts (e.g. Recordi25 and HBi4) and whitespace are normalized.
Printed page references are anchored to each LRL index entry's starting page.
All parser diagnostics are retained for review.
"""
from pathlib import Path
import bisect,collections,csv,datetime,hashlib,json,re

ROOT=Path(__file__).resolve().parent
DATA=None   # used only by main(), which is not run here
RV=re.compile(r'\(Record\s+(\d+)\)')
BILL=re.compile(r'\b(?:CS)?([HS](?:JR|CR|B|R))\s*(\d+)\b')
DATE_HEADING=re.compile(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), (January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2})$')
LABEL=re.compile(r'^(Yeas|Nays|Present,? [Nn]ot [Vv]oting|Absent,? Excused(?:, Committee Meeting)?|Absent|Present)\s*[—–-]+\s*(.*)',re.S)
POS={'Yeas':'Yea','Nays':'Nay','Present, not voting':'NV','Present, Not Voting':'NV',
     'Absent, Excused':'Absent, Excused','Absent':'Absent','Present':'Present'}
REVIEW={
    ('86R','84'):'Reviewed journal p. 939: the passage motion names HB 123. The dataset also associates HB 76 with this record; that association is not supported by this journal passage.',
    ('86R','460'):'Source inconsistency verified visually at journal p. 1806: the heading and bill description name HB 2166, while the recorded passage sentence prints HB 216. The quoted sentence is preserved. See evidence/review/86R_RV460.png.',
    ('86R','834'):'Reviewed journal p. 2522: CSHJR 95 was adopted. The dataset also associates SB 2 and describes an amendment failing; this journal record is adoption of CSHJR 95.',
}

def readcsv(p):return list(csv.DictReader(open(p)))
def writecsv(p,rows,cols):
    with open(ROOT/p,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
def flat(s):return re.sub(r'\s+',' ',s).strip()
def clean(s):
    s=s.replace('\x00','').replace('\u00a0',' ')
    s=re.sub(r'\b(January|February|March|April|May|June|July|August|September|October|November|December|Rule|Section|Article|Representative|James)i(?=[A-Z0-9])',r'\1 ',s)
    s=re.sub(r'\bRecordi(?=\d)','Record ',s)
    s=re.sub(r'\b((?:CS)?[HS](?:JR|CR|B|R))i(?=\d)',r'\1 ',s)
    s=re.sub(r'(?<=\d)i(?=[^a-zA-Z]|[a-zA-Z])',' ',s)
    s=re.sub(r'\bi(?=\d)',' ',s)
    s=re.sub(r'(?<=[a-zA-Z])i-ino\b',' - no',s)
    s=re.sub(r'(?<=[a-zA-Z])i-iyes\b',' - yes',s)
    s=re.sub(r'\bi-\s*i?',' - ',s)
    return s
def bills(s):return sorted(set(a+b for a,b in BILL.findall(s)),key=lambda x:(re.sub(r'\d','',x),int(re.search(r'\d+',x)[0])))
def upper(s):
    a=''.join(x for x in s if x.isalpha())
    return len(a)>4 and a==a.upper()

class Doc:
    def __init__(self,row):
        self.row=row;self.paras=[];self.starts=[];self.pages=[]
        raw=(ROOT/row['text_path']).read_text(errors='replace')
        current=[];pagenum=None
        def flush():
            nonlocal current
            if current:self.paras.append((flat(' '.join(current)),pagenum));current=[]
        for i,page in enumerate(raw.split('\f')):
            if not page.strip():continue
            page_no=str(int(row['first_page'])+i) if row['first_page'].isdigit() else f"{row['first_page']} + PDF page {i+1}"
            lines=[]
            for line in page.splitlines():
                s=line.strip()
                if not s:continue
                if 'HOUSE JOURNAL —' in s or re.search(r'\b\d+th LEGISLATURE —',s):continue
                lines.append(clean(line.rstrip()))
            body=[len(x)-len(x.lstrip()) for x in lines if len(x.strip())>40 and not upper(x)]
            base=min(body,default=0)
            for line in lines:
                s=line.strip();indent=len(line)-len(line.lstrip())
                date_heading=bool(DATE_HEADING.fullmatch(s))
                measure_heading=bool(re.match(r'^(?:CS)?[HS](?:JR|CR|B|R)\s*\d+\s*[-–—]',s))
                entry_line=bool(re.match(r'^(?:CS)?[HS](?:JR|CR|B|R)\s*\d+(?:\s*\(|\s*$)',s))
                amendment_heading=bool(re.fullmatch(r'Amendment No\. \d+',s))
                heading=upper(s)
                signature=indent>=base+25 and len(s)<180 and not upper(s)
                new=entry_line or measure_heading or amendment_heading or date_heading or heading or signature or bool(LABEL.match(s)) or base+4<=indent<=base+12
                if new:flush()
                if not current:pagenum=page_no
                current.append(s)
                if measure_heading or amendment_heading or date_heading or heading or signature:flush()
        flush()
        chunks=[];n=0;self.dates=[];current_date=row['date']
        for para,page in self.paras:
            dh=DATE_HEADING.fullmatch(para)
            if dh:
                current_date=datetime.datetime.strptime(dh[2]+' '+dh[3]+' '+row['date'][:4],'%B %d %Y').date().isoformat()
            self.dates.append(current_date)
            self.starts.append(n);self.pages.append(page);chunks.append(para);n+=len(para)+2
        self.text='\n\n'.join(chunks)
    def pi(self,offset):return max(0,bisect.bisect_right(self.starts,offset)-1)
    def page(self,offset):return self.pages[self.pi(offset)]

def kind(motion,heading,context):
    d=motion.split('(Record',1)[0].lower();h=heading.lower()
    if 'roll of the house' in d or 'quorum was' in d or 'verified roll' in d:return 'roll_call'
    if 'casting of the votes' in d:return 'speaker_election'
    if 'motion to table' in d:return 'motion_to_table'
    if 'reconsider' in d:return 'other_procedural'
    if 'resolutions were adopted' in d or ('resolutions' in d and 'were adopted' in d):return 'resolution_adoption'
    if 'conference committee report' in d or 'conference report' in d:return 'conference_report'
    if 'concur' in d:return 'concurrence'
    if ('engrossment' in d or ('second reading' in h and ('passed' in d or 'failed to pass' in d))):return 'passage_second_reading'
    if ('third reading' in h and ('passed' in d or 'failed to pass' in d)) or ('third time' in d and ('passed' in d or 'failed to pass' in d)):return 'passage_third_reading'
    if ('passed' in d or 'failed to pass' in d) and re.match(r'^(?:CS)?[HS](?:B|JR|CR|R)\s*\d',motion):return 'passage_final'
    if 'amendment no.' in d and ('adopt' in d or 'failed' in d):return 'amendment'
    if re.search(r'\b(?:cs)?[hs]jr\s*\d+.*(?:was adopted|failed of adoption)',d):
        if 'third reading' in h:return 'passage_third_reading'
        if 'second reading' in h:return 'passage_second_reading'
        return 'resolution_adoption'
    if re.search(r'\b(?:cs)?[hs](?:r|cr|jr)\s*\d+.*(?:was adopted|failed of adoption)',d):return 'resolution_adoption'
    return 'other_procedural'

def parse_doc(doc):
    rows=[];issues=[]
    markers=list(RV.finditer(doc.text))
    for k,m in enumerate(markers):
        pi=doc.pi(m.start());p=doc.paras[pi][0]
        after=markers[k+1].start() if k+1<len(markers) else len(doc.text)
        before=markers[k-1].end() if k else 0
        context=doc.text[max(before,m.start()-12000):m.start()]
        heading=next((x[0] for x in reversed(doc.paras[:pi]) if upper(x[0]) and ('READING' in x[0] or 'CALENDAR' in x[0])), '')
        motion=p
        if p.startswith('(Record') and pi:
            motion=doc.paras[pi-1][0]+' '+p
        elif re.match(r'^(The motion|The request|The roll of those voting|There being objection|Permission to)',p):
            prior=[x[0] for x in doc.paras[max(0,pi-6):pi] if re.search(r'\b(?:moved|requested|offered)\b',x[0]) and not LABEL.match(x[0]) and not x[0].startswith(('A record vote was requested','A verification of the vote'))]
            if prior:motion=prior[-1]+' '+p
            if 'motion in writing' in motion:
                start=next((j for j in range(pi-1,max(-1,pi-15),-1) if doc.paras[j][0].startswith('Mr. Speaker:')),None)
                if start is not None:motion=' '.join(q[0] for q in doc.paras[start:pi])+' '+p
        mk=kind(motion,heading,context)
        # A table motion identifies an amendment and its author independently.
        bill_headings=list(re.finditer(r'(?m)^(?:CS)?[HS](?:JR|CR|B|R)\s*\d+\b[^\n]*(?:ON (?:SECOND|THIRD) READING)',doc.text[:m.start()]))
        amendment_context=doc.text[bill_headings[-1].start() if bill_headings else before:m.start()]
        amendment=list(re.finditer(r'Amendment No\.\s*(\d+)',amendment_context,re.I))
        amendment_no=amendment[-1][1] if amendment else ''
        authors=list(re.finditer(r'Representatives?\s+(.{1,500}?)\s+offered the following (?:amendment|substitute)',amendment_context))
        author=authors[-1][1] if authors else ''
        if mk=='other_procedural' and 'reconsider' not in motion.lower() and re.search(r'Amendment No\.\s*\d+\s+(?:was|failed)',motion):mk='amendment'
        # Prefer the bill named by the motion, then the most recent explicit bill heading.
        bulk=bool(re.search(r'(?:bills|resolutions).*(?:calendar|read third time|following record vote).*record vote|resolutions.*following record vote|suspend all necessary rules.*resolutions.*calendar',motion,re.I))
        bs=bills(motion)
        if not bs and 'resolutions were adopted' in motion.lower():
            begin=next((j for j in range(pi-1,-1,-1) if re.search(r'The following .*resolutions were laid',doc.paras[j][0])),max(0,pi-30))
            bs=sorted(set(b for q,_ in doc.paras[begin:pi] if BILL.match(q) and 'previously adopted' not in q and 'was withdrawn' not in q for b in bills(q)[:1]))
        if not bs and not bulk and mk not in ('roll_call','speaker_election'):
            hs=list(re.finditer(r'(?m)^(?:CS)?[HS](?:JR|CR|B|R)\s*\d+\b[^\n]*(?:ON |READING|VOTE RECONSIDERED|[-–—])',doc.text[:m.start()]))
            if hs:bs=bills(hs[-1][0])
        summary=re.search(r'\(Record\s+\d+\):\s*(\d+) Yeas?,\s*(\d+) Nays?,\s*(\d+) Present, not voting\.',p,re.I)
        counts={};tally=''
        if summary:
            counts=dict(zip(['yea','nay','nv'],map(int,summary.groups())))
            tally=f"{counts['yea']} Yeas, {counts['nay']} Nays, {counts['nv']} Present, not voting"
        found=[];members={};last_list_end=doc.starts[pi]+len(p)
        for j in range(pi+1,len(doc.paras)):
            if doc.starts[j]>=after:break
            q=doc.paras[j][0];label=LABEL.match(q)
            if not label:
                if members:break
                continue
            lab=label[1]
            if lab.lower()=='present, not voting':lab='Present, not voting'
            names=[x.strip().rstrip('.') for x in label[2].split(';') if x.strip()]
            members[lab]=names;last_list_end=doc.starts[j]+len(q)
            if any(re.search(r'\bTalarico\b',n) for n in names):found.append('Absent, Excused' if lab.startswith('Absent, Excused') else POS.get(lab,lab))
        pos='; '.join(found) if found else 'unresolved'
        if mk=='speaker_election':
            segment=doc.text[m.end():after]
            choices=list(re.finditer(r'For the Honorable (.*?)\s*(?:\([^)]*\))?\s*[–—-]+\s*(\d+)\s*(.*?)(?=For the Honorable|Present, Not Voting|Absent [–—-]|Secretary Nelson|$)',segment,re.S))
            cc=[]
            for c in choices:
                cc.append(flat(c[1])+': '+c[2])
                if re.search(r'\bTalarico\b',c[3]):pos='For '+flat(c[1])
            tally='; '.join(cc)
        if members:
            counts['absent']=sum(len(names) for lab,names in members.items() if lab.startswith('Absent'))
        errors=[]
        for field,lab in [('yea','Yeas'),('nay','Nays'),('nv','Present, not voting')]:
            if field in counts and len(members.get(lab,[]))!=counts[field]:errors.append(f"{field}: tally {counts[field]}, parsed names {len(members.get(lab,[]))}")
        if pos=='unresolved':errors.append('Talarico not located in record member lists')
        if len(found)>1:errors.append('Talarico in multiple record member lists')
        exceptions=[];calendar_entries=[]
        if bulk:
            bulk_bills=[]
            for j in range(pi+1,len(doc.paras)):
                if doc.starts[j]<last_list_end:continue
                if doc.starts[j]>=after:break
                q=doc.paras[j][0]
                if bulk_bills and upper(q) and not ('SPONSOR AUTHORIZED' in q or q.startswith('STATEMENT') or q.startswith('REASON') or ('suspend all necessary rules' in motion and any(x in q for x in ['MEMORIAL','CONGRATULATORY','RESOLUTIONS','SUSPENSION']))):break
                entry=re.match(r'^(?:CS)?([HS](?:JR|CR|B|R))\s*(\d+)(?:\s*\(|\s*$)',q)
                if entry:
                    bn=entry[1]+entry[2];bulk_bills.append(bn)
                    bill_pos=pos
                    for exc in re.finditer(r'\(([^()]*)\s*-\s*(no|yes|present, not voting)\)',q,re.I):
                        if 'Talarico' in exc[1]:
                            ex_pos={'no':'Nay','yes':'Yea','present, not voting':'NV'}[exc[2].lower()]
                            bill_pos=ex_pos
                            exceptions.append(dict(bill=bn,talarico=ex_pos,entry_verbatim=q,journal_page=doc.paras[j][1]))
                    bt=re.search(r'\((\d+)\s*-\s*(\d+)\s*-\s*(\d+)\)',q)
                    bill_tally=f'{bt[1]} Yeas, {bt[2]} Nays, {bt[3]} Present, not voting' if bt else tally
                    calendar_entries.append(dict(bill=bn,talarico_journal=bill_pos,tally=bill_tally,tally_source='bill-specific printed tally' if bt else 'shared record tally, per journal motion',bill_entry_verbatim=q,journal_page=doc.paras[j][1]))
            bs=sorted(set(bs+bulk_bills))
            if not bs:errors.append('Bulk calendar bill list unresolved')
        row=dict(session=doc.row['session'],rv=m[1],date=doc.dates[pi],motion_verbatim=motion,motion_kind=mk,
                 bills='; '.join(bs),tally=tally,talarico_journal=pos,journal_page=doc.page(m.start()),source_sha256=doc.row['sha256'],
                 source_url=doc.row['url'],source_path=doc.row['path'],amendment_no=amendment_no,amendment_author=author,
                 yea=counts.get('yea',''),nay=counts.get('nay',''),nv=counts.get('nv',''),absent=counts.get('absent',''),
                 parse_notes='; '.join(errors),journal_listing=next((lab for lab,names in members.items() if any(re.search(r'\bTalarico\b',n) for n in names)),''),
                 bill_vote_exceptions=json.dumps(exceptions,ensure_ascii=False) if exceptions else '')
        row['calendar_entries']=calendar_entries;row['members']=members
        rows.append(row)
        if errors:issues.append({**row,'issue':'; '.join(errors)})
    # Some days explicitly apply two earlier votes to an entire following calendar.
    for i,(p,page) in enumerate(doc.paras):
        if not ('record vote' in p.lower() and 'all bills' in p.lower() and re.search(r'\b(?:using|use)\b',p)):
            continue
        anchor=bills(p)
        if len(anchor)!=1:continue
        earlier=[r for r in rows if doc.starts[doc.pi(next(m.start() for m in markers if m[1]==r['rv']))]<doc.starts[i] and anchor[0] in r['bills'].split('; ')]
        want_rule='suspend the constitutional' in p or 'constitutional three-day rule on' in p
        earlier=[r for r in earlier if ('suspend the constitutional' in r['motion_verbatim'])==want_rule]
        later=[r for r in rows if r['motion_verbatim'].startswith('The following bills') and int(r['journal_page'])>=int(page) and int(r['journal_page'])<=int(page)+3]
        if earlier and later:
            target=earlier[-1];target['bills']='; '.join(sorted(set(target['bills'].split('; ')+later[0]['bills'].split('; '))))
            target['motion_verbatim']+=' '+p
            target['parse_notes']+=f'; Journal explicitly reuses this vote for calendar bills, motion at p. {page}.'
    return rows,issues

def statements(doc):
    out=[]
    for i,(p,page) in enumerate(doc.paras):
        if not re.search(r'\bTalarico\b',p):continue
        # Signatures are short paragraphs. A statement may have several authors.
        if len(p)>180 or ';' in p or '(' in p or BILL.match(p) or p.startswith('Amendment') or re.search(r'\b(?:Representatives?|motion|present|absent|House|Mr\.)\b',p,re.I):continue
        prior=doc.paras[max(0,i-20):i]
        heading=next((j for j in range(i-1,max(-1,i-100),-1) if re.search(r'^(?:STATEMENTS? OF VOTES?|REASONS? FOR VOTES?)$',doc.paras[j][0])),None)
        if heading is None:continue
        # The nearest statement begins at a formula or after the last signature.
        start=next((j for j in range(i-1,heading,-1) if re.match(r'^(?:When Record|I was shown|I intended|During the vote|I am |I voted|I oppose|I support)',doc.paras[j][0])),None)
        if start is None:
            start=heading+1
        content=' '.join(q[0] for q in doc.paras[start:i])
        if not content or any(upper(q[0]) for q in doc.paras[start:i]):continue
        rvs='; '.join(dict.fromkeys(re.findall(r'Record (?:No\. )?(\d+)',content)))
        out.append(dict(session=doc.row['session'],date=doc.dates[start],rv=rvs,statement_verbatim=content,
                        authors=p,journal_page=doc.paras[start][1],source_sha256=doc.row['sha256'],source_url=doc.row['url'],source_path=doc.row['path'],statement_type='statement_of_vote',filed_by=p,notes=''))
    # A jointly signed explanation can be filed under a different journal heading.
    for i,(p,page) in enumerate(doc.paras):
        if 'STATEMENT FOR INCLUSION IN THE JOURNAL' not in p:continue
        end=next((j for j in range(i+1,len(doc.paras)) if upper(doc.paras[j][0])),len(doc.paras))
        segment=doc.paras[i+1:end]
        submit=next((re.search(r'Representative (.*?) submitted the following statement',q) for q,_ in segment if 'submitted the following statement' in q),None)
        if not submit:continue
        author_start=next((j for j in range(i+1,end) if doc.paras[j][0].startswith(submit[1]+',')),None)
        if author_start is None:continue
        authors=' '.join(q for q,_ in doc.paras[author_start:end])
        if not re.search(r'\bTalarico\b',authors):continue
        body_start=next(j+1 for j in range(i+1,author_start) if 'submitted the following statement' in doc.paras[j][0])
        content=' '.join(q for q,_ in doc.paras[body_start:author_start])
        prior=list(RV.finditer(doc.text[:doc.starts[i]]))
        out.append(dict(session=doc.row['session'],date=doc.dates[body_start],rv=prior[-1][1] if prior else '',statement_verbatim=content,
                        authors=authors,journal_page=doc.paras[body_start][1],source_sha256=doc.row['sha256'],source_url=doc.row['url'],source_path=doc.row['path'],
                        statement_type='co_signed_explanation_of_vote',filed_by=submit[1],notes='Filed by the named submitter and co-signed by Talarico. Record number identifies the immediately preceding vote on the bill; it is not printed in the statement.'))
    return out

def absences(docs,votes,data,index,statements):
    out=[]
    absent=collections.defaultdict(list);all_day=collections.defaultdict(list)
    jmap={(r['session'],r['rv']):r for r in votes}
    for r in data:
        all_day[r['session'],r['date']].append(r)
        if r['talarico']=='Absent':absent[r['session'],r['date']].append(r)
    for (session,date),target in sorted(absent.items()):
        sources=[d for d in docs if d.row['session']==session and date in d.dates]
        expected=[r for r in index if r['session']==session and r['date']==date]
        complete=bool(expected) and all(r['status']=='saved' for r in expected)
        selected=[jmap.get((session,r['rv'])) for r in target];actual=[r for r in selected if r]
        listings=sorted(set(r['journal_listing'] for r in actual if r['journal_listing']))
        reasons=[];movers=[];citations=[];sha=[];notes=[]
        for d in sources:
            for i,(p,page) in enumerate(d.paras):
                if d.dates[i]!=date or not re.search(r'\bTalarico\b',p):continue
                m=re.search(r'Talarico on motion of ((?:[A-Z]\.\s*)*[^.]+)\.',p)
                if m:
                    h=next((j for j in range(i-1,max(-1,i-150),-1) if upper(d.paras[j][0])),None)
                    intro=[]
                    if h is not None and 'LEAVE' in d.paras[h][0]:
                        # A leave heading can contain several reasons. Use the nearest
                        # actual grant introduction rather than the first category.
                        grant=next((j for j in range(i-1,h,-1) if re.search(r'(?:was|were) granted (?:leave|leaves) of absence',d.paras[j][0])),None)
                        if grant is not None:intro=[d.paras[grant][0]]
                    if intro:
                        reasons.append(' '.join(intro+[m[0]]));movers.append(m[1]);citations.append(page);sha.append(d.row['sha256'])
        leave='yes' if reasons else 'no' if complete else 'unresolved'
        if not reasons and sources:notes.append('No explicit Talarico leave grant located in available text; collective or inherited leave requires context review.')
        if not complete:notes.append('Recorded journal gap: '+', '.join(r['day']+': '+r['status'] for r in expected if r['status']!='saved') if expected else 'Recorded journal gap: no dated index entry for this vote date.')
        missing=[r['rv'] for r,j in zip(target,selected) if not j]
        if missing:notes.append('Absent RVs without parsed journal record: '+', '.join(missing))
        day=sorted(all_day[session,date],key=lambda r:int(r['rv'] or 0))
        transitions=[]
        for i,r in enumerate(day):
            if r['talarico']=='Absent' and (i==0 or day[i-1]['talarico']!='Absent'):
                prior=f"after RV {day[i-1]['rv']} ({day[i-1]['talarico']})" if i else 'at first dataset vote'
                last=i
                while last+1<len(day) and day[last+1]['talarico']=='Absent':last+=1
                nxt=f"; resumes RV {day[last+1]['rv']} ({day[last+1]['talarico']})" if last+1<len(day) else '; through last dataset vote'
                transitions.append(f"Absent RV {r['rv']}–{day[last]['rv']} {prior}{nxt}")
        notes.append('Dataset sequence (RV numbers between endpoints may be outside the dataset): '+' | '.join(transitions))
        if not sha:
            sha=list(dict.fromkeys(r['source_sha256'] for r in actual));citations=list(dict.fromkeys(r['journal_page'] for r in actual))
        target_rvs={r['rv'] for r in target}
        filed=[r for r in statements if r['session']==session and r['date']==date and target_rvs.intersection(r['rv'].split('; '))]
        for st in filed:
            notes.append(f"His filed statement, journal p. {st['journal_page']}, sha256 {st['source_sha256']}: {st['statement_verbatim']}")
        out.append(dict(first_missed_rv=target[0]['rv'],last_missed_rv=target[-1]['rv'],partial_day='yes' if len(target)<len(day) else 'no',missed_runs=' | '.join(transitions),missed_record_details=json.dumps([dict(rv=r['rv'],journal_listing=j['journal_listing'] if j else 'unresolved',journal_page=j['journal_page'] if j else '',source_sha256=j['source_sha256'] if j else '') for r,j in zip(target,selected)],ensure_ascii=False),session=session,date=date,record_votes_absent=len(target),record_votes_that_day=len(day),
                        journal_listing=('Absent, Excused' if listings[0].startswith('Absent, Excused') else listings[0]) if len(listings)==1 else 'mixed' if listings else '',leave_granted=leave,
                        reason_verbatim=' | '.join(dict.fromkeys(reasons)),moved_by='; '.join(dict.fromkeys(movers)),journal_page='; '.join(dict.fromkeys(citations)),
                        source_sha256='; '.join(dict.fromkeys(sha)),notes=' '.join(notes)))
    return out

def compare(votes,data):
    j={(r['session'],r['rv']):r for r in votes};d={(r['session'],r['rv']):r for r in data}
    rows=[];counts=collections.Counter()
    for key in sorted(j.keys()|d.keys(),key=lambda k:(k[0],int(k[1] or 0))):
        a=d.get(key);b=j.get(key);dif=[]
        if not a:dif.append('journal_only');counts['journal_only']+=1
        if not b:dif.append('dataset_only');counts['dataset_only']+=1
        if a and b:
            counts['matched']+=1
            bp='Absent' if b['talarico_journal']=='Absent, Excused' else b['talarico_journal']
            if bp=='unresolved':dif.append('position_unresolved');counts['position_unresolved']+=1
            elif a['talarico']!=bp:dif.append('position');counts['position_disagreements']+=1
            if set(x.strip() for x in a['bills'].split(';') if x.strip())!=set(x.strip() for x in b['bills'].split(';') if x.strip()):dif.append('bills');counts['bill_differences']+=1
            for f in ['yea','nay','nv','absent']:
                if a[f]!='' and b[f]!='' and int(a[f])!=int(b[f]):dif.append('tally_'+f);counts['tally_field_differences']+=1
            if a['date']!=b['date']:dif.append('date');counts['date_differences']+=1
            if b.get('bill_vote_exceptions'):
                dif.append('bill_specific_position');counts['records_with_bill_specific_positions']+=1
        if dif:
            rows.append(dict(session=key[0],rv=key[1],date=(b or a)['date'],differences='; '.join(dif),dataset_position=a['talarico'] if a else '',
                             journal_position=b['talarico_journal'] if b else '',dataset_bills=a['bills'] if a else '',journal_bills=b['bills'] if b else '',
                             dataset_tally=json.dumps({f:a[f] for f in ['yea','nay','nv','absent']}) if a else '',
                             journal_tally=json.dumps({f:b[f] for f in ['yea','nay','nv','absent']}) if b else '',journal_page=b['journal_page'] if b else '',
                             source_sha256=b['source_sha256'] if b else '',notes=(b['parse_notes']+' '+REVIEW.get(key,'')+(' Journal proceeding date differs from dataset date; see source text and date_difference_review.csv. Calendar-date versus legislative-day dating is reviewed separately.' if 'date' in dif else '')+(' Individual bill exceptions: '+b['bill_vote_exceptions'] if b.get('bill_vote_exceptions') else '')) if b else 'Record not located by the journal parser in the full saved corpus; see missing_record_review.csv for the documented reason.'))
    return rows,dict(counts)

def resolve_authors(docs,votes):
    offerings=[]
    for doc in docs:
        for i,(p,page) in enumerate(doc.paras):
            m=re.search(r'Representatives? (.+?) offered the following (?:substitute )?amendment',p)
            if not m:continue
            num=next((re.search(r'Amendment No\.\s*(\d+)',doc.paras[j][0]) for j in range(i-1,max(-1,i-5),-1) if re.search(r'Amendment No\.\s*(\d+)',doc.paras[j][0])),None)
            if not num:continue
            bs=bills(p)
            if not bs:
                for j in range(i-1,-1,-1):
                    if BILL.match(doc.paras[j][0]):bs=bills(doc.paras[j][0])[:1];break
            offerings.append(dict(session=doc.row['session'],date=doc.dates[i],path=doc.row['path'],offset=doc.starts[i],no=num[1],author=m[1],bills=bs,page=page,quote=p,sha=doc.row['sha256']))
    docmap={doc.row['path']:doc for doc in docs}
    for r in votes:
        if r['motion_kind'] not in ['amendment','motion_to_table'] or not r['amendment_no'] or r['amendment_author']:continue
        doc=docmap[r['source_path']]
        marker=next((m.start() for m in RV.finditer(doc.text) if m[1]==r['rv']),len(doc.text))
        found=[o for o in offerings if o['session']==r['session'] and o['no']==r['amendment_no'] and set(o['bills'])&set(r['bills'].split('; ')) and (o['date']<r['date'] or (o['path']==r['source_path'] and o['offset']<marker))]
        if found:
            o=max(found,key=lambda o:(o['date'],o['path']==r['source_path'],o['offset']))
            r['amendment_author']=o['author']
            r['parse_notes']+='; Amendment author from original offering: '+o['path']+' p. '+o['page']+'; '+o['quote']
    return offerings

def main():
    index=readcsv(ROOT/'registers/journal_index.csv');data=readcsv(DATA)
    docs=[Doc(r) for r in index if r['status']=='saved']
    allvotes=[];issues=[];ss=[]
    for doc in docs:
        rr,ii=parse_doc(doc);allvotes+=rr;issues+=ii;ss+=statements(doc)
    # Repeated mentions of the same recorded vote retain the first actual list.
    grouped=collections.defaultdict(list)
    for r in allvotes:grouped[r['session'],r['rv']].append(r)
    votes=[]
    for key,rr in grouped.items():
        first=dict(next((r for r in rr if r['talarico_journal']!='unresolved'),rr[0]))
        if len(rr)>1:
            first['parse_notes']+='; Multiple record-marker occurrences: '+str(len(rr))
            first['bills']='; '.join(sorted(set(b for r in rr for b in r['bills'].split('; ') if b)))
            first['motion_verbatim']=' '.join(dict.fromkeys(r['motion_verbatim'] for r in rr))
            exc=[x for r in rr for x in json.loads(r.get('bill_vote_exceptions') or '[]')]
            first['bill_vote_exceptions']=json.dumps(exc,ensure_ascii=False) if exc else ''
        votes.append(first)
    votes.sort(key=lambda r:(r['session'],int(r['rv'])))
    resolve_authors(docs,votes)
    ab=absences(docs,votes,data,index,ss);diff,counts=compare(votes,data)
    vcols=['session','rv','date','motion_verbatim','motion_kind','bills','tally','talarico_journal','journal_page','source_sha256','source_url','source_path','amendment_no','amendment_author','yea','nay','nv','absent','journal_listing','bill_vote_exceptions','parse_notes']
    writecsv('registers/journal_votes.csv',votes,vcols)
    writecsv('registers/parser_issues.csv',issues,vcols+['issue'])
    writecsv('registers/record_occurrences.csv',allvotes,vcols)
    exceptions=[dict(session=r['session'],rv=r['rv'],date=r['date'],**x,source_sha256=r['source_sha256'],source_url=r['source_url']) for r in votes for x in json.loads(r.get('bill_vote_exceptions') or '[]')]
    writecsv('registers/bill_vote_exceptions.csv',exceptions,['session','rv','date','bill','talarico','entry_verbatim','journal_page','source_sha256','source_url'])
    calendar=[dict(session=r['session'],rv=r['rv'],date=r['date'],**x,source_sha256=r['source_sha256'],source_url=r['source_url']) for r in allvotes for x in r.get('calendar_entries',[])]
    writecsv('registers/calendar_bill_votes.csv',calendar,['session','rv','date','bill','talarico_journal','tally','tally_source','bill_entry_verbatim','journal_page','source_sha256','source_url'])
    writecsv('registers/absences.csv',ab,['session','date','record_votes_absent','record_votes_that_day','journal_listing','leave_granted','reason_verbatim','moved_by','journal_page','source_sha256','notes','first_missed_rv','last_missed_rv','partial_day','missed_runs','missed_record_details'])
    writecsv('registers/statements_of_vote.csv',ss,['session','date','rv','statement_verbatim','authors','journal_page','source_sha256','source_url','source_path','statement_type','filed_by','notes'])
    writecsv('registers/discrepancies.csv',diff,['session','rv','date','differences','dataset_position','journal_position','dataset_bills','journal_bills','dataset_tally','journal_tally','journal_page','source_sha256','notes'])
    report=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),saved_documents=len(docs),expected_documents=len(index),dataset_votes=len(data),journal_records=len(votes),record_marker_occurrences=len(allvotes),absence_days=len(ab),statements=len(ss),bill_vote_exceptions=len(exceptions),calendar_bill_entries=len(calendar),parser_issues=len(issues),counts=counts)
    (ROOT/'registers/parse_report.json').write_text(json.dumps(report,indent=2)+'\n')
    with (ROOT/'ledger.jsonl').open('a') as f:f.write(json.dumps(dict(utc=report['utc'],slice='S1–S4',action='parse_saved_journal_text',exit=0,artifact_paths=['registers/journal_votes.csv','registers/absences.csv','registers/statements_of_vote.csv','registers/discrepancies.csv','registers/parse_report.json'],sha256='',cause='Only saved text layers; gaps explicit',next='Review parser diagnostics, quorum dates, and comparisons',report=report))+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
