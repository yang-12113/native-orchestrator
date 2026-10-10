"""Meaningful fail-closed route tests. The native subprocess itself is a test replacement."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from native_orchestrator.workbuddy_adapter import WorkBuddyAdapter, ROOT
from native_orchestrator.native_rpc import RpcError
from native_orchestrator.orchestrator import classify_error

class FakeProcess:
    def __init__(self,output):self.output=output;self.returncode=0
    def communicate(self,*args,**kwargs):return self.output,''

def result(model='deepseek-v4.1-flash',credit=0,text='{"artifacts":[],"note":"done"}'):
    return json.dumps([{'type':'message','role':'assistant','providerData':{'model':model,'rawUsage':{'credit':credit}}},
        {'type':'result','subtype':'success','is_error':False,'result':text,'session_id':'independent-native-test','usage':{'input_tokens':1}}])

class AdapterTests(unittest.TestCase):
    def call(self,output):
        with tempfile.TemporaryDirectory(dir=ROOT) as d:
            with patch('native_orchestrator.workbuddy_adapter.subprocess.Popen',return_value=FakeProcess(output)):
                return WorkBuddyAdapter().run('executor','deepseek-v4.1-flash','task',d,Path(d)/'events.jsonl',schema={})
    def test_verified_model_and_credit(self):
        r=self.call(result());self.assertEqual(r['native_credit'],0);self.assertEqual(r['tools_enabled'],0)
    def test_model_mismatch_is_rejected(self):
        with self.assertRaises(RpcError):self.call(result(model='paid-model'))
    def test_nonzero_credit_is_rejected(self):
        with self.assertRaises(RpcError):self.call(result(credit=1))
    def test_unknown_credit_is_rejected(self):
        with self.assertRaises(RpcError):self.call(result(credit=None))
    def test_boolean_credit_is_not_a_billing_number(self):
        with self.assertRaises(RpcError):self.call(result(credit=False))
    def test_auth_failure_is_not_success(self):
        with self.assertRaises(RpcError):self.call('Authentication required. Please use /login')
    def test_missing_result_is_rejected(self):
        with self.assertRaises(RpcError):self.call('[]')
    def test_server_guard_and_expiry_classification(self):
        self.assertEqual(classify_error(RpcError('SERVICE_GUARD: unusual activity')),'SERVICE_GUARD')
        self.assertEqual(classify_error(RpcError('ENTITLEMENT_EXPIRED: promotion expired')),'ENTITLEMENT_EXPIRED')

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(AdapterTests)
    report=unittest.TextTestRunner(verbosity=2).run(suite)
    (ROOT/'evidence/native-fix/adapter-tests.json').write_text(json.dumps({'status':'MOCK_VERIFIED',
        'tests_run':report.testsRun,'failures':len(report.failures),'errors':len(report.errors),'passed':report.wasSuccessful()},indent=2),encoding='utf-8')
    raise SystemExit(not report.wasSuccessful())
