import json
import tempfile
import unittest
from enum import Enum
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch

from native_orchestrator.codex_sdk_adapter import CodexSdkAdapter, SdkRoleError, role_environment

ROOT = Path(__file__).resolve().parents[1]


class Sandbox(Enum):
    workspace_write = 'workspace-write'
    read_only = 'read-only'


class Approval(Enum):
    deny_all = 'deny_all'


class CodexSdkAdapterTests(unittest.TestCase):
    def setUp(self):
        self.cases = ROOT / '.runtime/sdk-adapter-tests'
        self.cases.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=self.cases)
        self.root = Path(self.tmp.name)
        self.turns = 0
        self.intents = 0
        self.account = 'chatgpt'
        self.efforts = ['max']
        self.observed_model = 'gpt-6-luna'
        self.observed_effort = 'max'
        self.cursor = None
        self.selected = True
        self.final = '{"summary":"final"}'
        self.closed = False
        self.options = None
        fixture = self

        class Thread:
            id = 'fresh-sdk-thread'
            def read(self):
                return N(thread=N(model=fixture.observed_model, reasoning_effort=N(value=fixture.observed_effort),
                    cwd=N(root=str(fixture.root)), cli_version='0.162.0'))
            def turn(self, prompt, **options):
                fixture.turns += 1
                fixture.turn_options = options
                return N(interrupt=lambda: None, run=lambda: N(status=N(value='completed'), id='sdk-turn', error=None,
                    final_response=fixture.final, usage=None, items=[{'type':'agentMessage','text':'{"summary":"intermediate"}'}]))

        class Client:
            metadata = N(userAgent='Codex/0.162.0')
            def __init__(self, config):
                fixture.config = config
            def __enter__(self):
                return self
            def __exit__(self, *args):
                fixture.closed = True
            def close(self):
                fixture.closed = True
            def account(self, **args):
                return N(model_dump=lambda **kw: {'account': {'type': fixture.account}})
            def models(self):
                values = [N(model='gpt-6-luna', supported_reasoning_efforts=[N(reasoning_effort=N(value=v)) for v in fixture.efforts])] if fixture.selected else []
                return N(data=values, next_cursor=fixture.cursor)
            def thread_start(self, **options):
                fixture.options = options
                return Thread()

        self.sdk = N(__version__='0.162.0', Codex=Client, CodexConfig=lambda **kw: kw, Sandbox=Sandbox, ApprovalMode=Approval)

    def tearDown(self):
        assert self.root.resolve().is_relative_to(self.cases.resolve())
        self.tmp.cleanup()

    def invoke(self, role='executor', authority=lambda: True, intent=None, effort='max'):
        def record_intent(sid):
            self.intents += 1
            return True
        return CodexSdkAdapter().run(role, 'gpt-6-luna', 'owned fixture', str(self.root), self.root/'role.json',
            schema={'type':'object'}, before_dispatch=authority, before_turn=intent or record_intent, sdk=self.sdk, effort=effort)

    def test_final_response_only_and_intent_before_one_turn(self):
        value = self.invoke()
        self.assertEqual(value['payload'], {'summary':'final'})
        self.assertEqual((self.intents,self.turns),(1,1))
        self.assertTrue(self.closed)
        self.assertEqual(json.loads((self.root/'role.json').read_text())['final_response'], self.final)

    def test_roles_set_workspace_or_readonly_and_deny_all(self):
        self.invoke('reviewer')
        self.assertEqual(self.options['sandbox'], Sandbox.read_only)
        self.assertEqual(self.turn_options['sandbox'], Sandbox.read_only)
        self.assertEqual(self.options['approval_mode'], Approval.deny_all)
        self.assertTrue(self.options['ephemeral'])

    def test_lost_authority_never_constructs_or_dispatches(self):
        with self.assertRaisesRegex(SdkRoleError,'AUTHORITY_LOST'):
            self.invoke(authority=lambda: False)
        self.assertEqual(self.turns,0)
        self.assertIsNone(self.options)

    def test_budget_refusal_never_starts_turn(self):
        with self.assertRaisesRegex(SdkRoleError,'TURN_INTENT_OR_BUDGET_REJECTED'):
            self.invoke(intent=lambda sid: False)
        self.assertEqual(self.turns,0)
        self.assertTrue(self.closed)

    def test_api_account_is_not_silently_used(self):
        self.account='apiKey'
        with self.assertRaisesRegex(SdkRoleError,'SUBSCRIPTION_ACCOUNT_UNVERIFIED'):
            self.invoke()
        self.assertEqual(self.turns,0)

    def test_effort_or_observed_identity_mismatch_stops_before_turn(self):
        self.efforts=['low']
        with self.assertRaisesRegex(SdkRoleError,'EFFORT_UNAVAILABLE'):
            self.invoke()
        self.efforts=['max']
        self.observed_model='other-model'
        with self.assertRaisesRegex(SdkRoleError,'MODEL_OR_EFFORT_MISMATCH'):
            self.invoke()
        self.assertEqual(self.turns,0)

    def test_unsearched_later_model_page_does_not_become_unavailable_or_fallback(self):
        self.selected=False
        self.cursor='page-two'
        with self.assertRaisesRegex(SdkRoleError,'MODEL_CATALOG_INCOMPLETE'):
            self.invoke()
        self.assertEqual(self.turns,0)

    def test_bad_or_oversized_final_json_preserves_log_without_replay(self):
        self.final='not final JSON'
        with self.assertRaises(json.JSONDecodeError):
            self.invoke()
        self.assertEqual(self.turns,1)
        self.assertTrue((self.root/'role.json').is_file())

    def test_environment_does_not_copy_credentials(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY':'synthetic-test-only','SERVICE_ACCESS_TOKEN':'synthetic-test-only','USERPROFILE':'profile'}, clear=True):
            env=role_environment()
        self.assertNotIn('OPENAI_API_KEY',env)
        self.assertNotIn('SERVICE_ACCESS_TOKEN',env)
        self.assertEqual(env['PYTHONDONTWRITEBYTECODE'],'1')

    def test_high_effort_is_explicitly_sent_to_thread_and_turn(self):
        self.efforts=['high'];self.observed_effort='high'
        result=self.invoke(effort='high')
        self.assertEqual(self.options['config']['model_reasoning_effort'],'high')
        self.assertEqual(self.turn_options['effort'],'high')
        self.assertEqual(result['effort'],'high')

    def test_preflight_required_reviewer_cannot_be_replaced_with_available_executor(self):
        with self.assertRaisesRegex(SdkRoleError,'BLOCKED_MODEL'):
            CodexSdkAdapter().preflight({'reviewer':{'model':'missing-reviewer','reasoning_effort':'max'}},str(self.root),before_dispatch=lambda:True,sdk=self.sdk)
        self.assertEqual(self.turns,0)


if __name__=='__main__':
    unittest.main()
