import json
import tempfile
import unittest
from pathlib import Path
from orchestrator import Controller,ROOT
from watch_project import snapshot

class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT)
        self.c=Controller(self.temp.name)
        spec=json.loads((ROOT/'demo.project.json').read_text(encoding='utf-8'))
        self.project=self.c.submit(spec,'watch-test')['project_id']
    def tearDown(self):self.c.db.close();self.temp.cleanup()
    def test_read_only_snapshot_does_not_dispatch_or_record_reply(self):
        before=self.c.db.execute('SELECT COUNT(*) FROM reply_audit').fetchone()[0]
        r=snapshot(self.temp.name,self.project)
        self.assertEqual(r['outcome'],'RUNNING')
        self.assertEqual(r['model_calls_made_by_watcher'],0)
        self.assertEqual(self.c.db.execute('SELECT COUNT(*) FROM calls').fetchone()[0],0)
        self.assertEqual(self.c.db.execute('SELECT COUNT(*) FROM reply_audit').fetchone()[0],before)
    def test_accepted_attempt_paths_and_master_wait(self):
        while self.c.run_one():pass
        r=snapshot(self.temp.name,self.project)
        self.assertEqual(r['outcome'],'ACCEPTED')
        first=next(x for x in r['accepted_outputs'] if x['task']=='csv-demo')
        self.assertEqual(first['attempt'],2)
        self.assertTrue(Path(first['artifacts_root']).is_dir())
        self.assertEqual(snapshot(self.temp.name,self.project,True)['outcome'],'WAITING_FOR_MASTER')
    def test_missing_database_is_not_created(self):
        missing=Path(self.temp.name)/'absent'
        with self.assertRaises(ValueError):snapshot(missing,'unknown')
        self.assertFalse(missing.exists())
    def test_unknown_project_is_not_success(self):
        with self.assertRaises(ValueError):snapshot(self.temp.name,'unknown')
    def test_expired_lease_needs_decision(self):
        t=self.c.claim()
        with self.c.db:self.c.decision(t,'INTERRUPTED_REQUIRES_RECONCILIATION')
        r=snapshot(self.temp.name,self.project)
        self.assertEqual(r['outcome'],'NEEDS_DECISION')
        self.assertEqual(r['decision_requests'][0]['reason'],'INTERRUPTED_REQUIRES_RECONCILIATION')

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WatchTests))
    (ROOT/'evidence/usage-guide-tests.json').write_text(json.dumps({'status':'MOCK_VERIFIED','tests_run':result.testsRun,
        'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()},indent=2),encoding='utf-8')
    raise SystemExit(not result.wasSuccessful())
