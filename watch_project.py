"""Read-only project watcher. Polling uses code, not model turns or writable Controller APIs."""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def snapshot(data,project,await_master=False):
    db=Path(data).resolve()/'state.sqlite'
    if not db.is_file():raise ValueError('No existing state database at the requested data directory')
    c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=10);c.row_factory=sqlite3.Row
    try:
        if not c.execute('SELECT 1 FROM projects WHERE id=?',(project,)).fetchone():raise ValueError('Unknown project ID')
        c.execute('BEGIN')
        tasks=c.execute('SELECT local_id,state,attempt,error_class,manifest_hash FROM tasks WHERE project_id=? ORDER BY rowid',(project,)).fetchall()
        counts={}
        for task in tasks:counts[task['state']]=counts.get(task['state'],0)+1
        decisions=[dict(x) for x in c.execute('SELECT rowid AS cursor,id,reason FROM decisions WHERE project_id=? AND resolved=0 ORDER BY rowid LIMIT 10',(project,))]
        decision_count=c.execute('SELECT COUNT(*) FROM decisions WHERE project_id=? AND resolved=0',(project,)).fetchone()[0]
        version=c.execute('SELECT COALESCE(MAX(cursor),0) FROM events WHERE project_id=?',(project,)).fetchone()[0]
        has_master=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='master_notices'").fetchone()
        notice=c.execute('SELECT state,result_ref FROM master_notices WHERE project_id=? AND state_version=?',(project,version)).fetchone() if has_master else None
        master=notice['state'] if notice else 'NOT_YET_RECORDED'
        accepted=bool(tasks) and counts.get('ACCEPTED',0)==len(tasks)
        stopped=bool(tasks) and all(x['state'] in ('ACCEPTED','NEEDS_DECISION','CANCELLED') for x in tasks)
        if decisions or counts.get('NEEDS_DECISION',0):outcome='NEEDS_DECISION'
        elif counts.get('CANCELLED',0) and stopped:outcome='CANCELLED'
        elif accepted and (not await_master or master=='COMPLETED'):outcome='ACCEPTED'
        elif accepted and master in ('NEEDS_DECISION','BUDGET_EXHAUSTED'):outcome='ARTIFACTS_ACCEPTED_MASTER_NEEDS_DECISION'
        elif accepted:outcome='WAITING_FOR_MASTER'
        else:outcome='RUNNING'
        report={'project_id':project,'state_version':version,'outcome':outcome,'task_counts':counts,
            'decision_requests':decisions,'decision_count':decision_count,'decisions_has_more':decision_count>len(decisions),
            'decision_next_cursor':decisions[-1]['cursor'] if decisions else 0,
            'decision_query':'orchestrator.py resume '+project+' --cursor <decision_next_cursor> --state-version '+str(version),
            'master_state':master,'model_calls_made_by_watcher':0}
        if stopped:
            roots=[]
            for task in tasks:
                if task['state']=='ACCEPTED':
                    item={'task':task['local_id'],'attempt':task['attempt'],'manifest_hash':task['manifest_hash'],
                        'artifacts_root':str(Path(data).resolve()/'projects'/project/task['local_id']/str(task['attempt'])/'artifacts')}
                    candidate={**report,'accepted_outputs':roots+[item],'more_outputs':True}
                    if len(json.dumps(candidate,ensure_ascii=False).encode('utf-8'))>7000:break
                    roots.append(item)
            report['accepted_outputs']=roots;report['more_outputs']=len(roots)<counts.get('ACCEPTED',0)
        if notice and notice['result_ref']:report['master_notice_ref']=notice['result_ref']
        return report
    finally:c.close()

def main():
    p=argparse.ArgumentParser(description='Wait for stored project state without making model calls')
    p.add_argument('project')
    p.add_argument('--data',default=str(ROOT/'data-live'))
    p.add_argument('--timeout',type=float,default=900)
    p.add_argument('--await-master',action='store_true')
    p.add_argument('--once',action='store_true')
    args=p.parse_args()
    if args.timeout<0:p.error('Timeout must not be negative')
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    deadline=time.monotonic()+args.timeout;last=None
    while True:
        report=snapshot(args.data,args.project,args.await_master)
        raw=json.dumps(report,ensure_ascii=False,separators=(',',':'))
        if raw!=last:print(raw,flush=True);last=raw
        if args.once:return
        if report['outcome']=='ACCEPTED':return
        if report['outcome'] in ('NEEDS_DECISION','CANCELLED','ARTIFACTS_ACCEPTED_MASTER_NEEDS_DECISION'):raise SystemExit(2)
        if time.monotonic()>=deadline:
            print(json.dumps({'project_id':args.project,'watch_timeout':True,'task_cancelled':False,'next_action':'Use the same project ID to check again'},ensure_ascii=False),flush=True)
            raise SystemExit(3)
        time.sleep(min(1,max(0,deadline-time.monotonic())))

if __name__=='__main__':main()
