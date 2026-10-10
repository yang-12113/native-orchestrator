import tempfile
import unittest
from pathlib import Path

from native_orchestrator.model_policy import POLICY_PATH, load_policy

ROOT = Path(__file__).resolve().parents[1]


class ModelPolicyTests(unittest.TestCase):
    def test_chinese_policy_has_two_models_high_and_no_reviewer_downgrade(self):
        policy=load_policy()
        self.assertIn('模型策略',POLICY_PATH.read_text(encoding='utf-8'))
        self.assertEqual(len({x['model'] for x in policy['routes'].values()}),2)
        self.assertTrue(all(x['reasoning_effort']=='high' for x in policy['routes'].values()))
        self.assertFalse(policy['allow_reviewer_downgrade'])

    def invalid(self, old, new):
        parent=ROOT/'.runtime/model-policy-tests'
        parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            path=Path(directory)/'policy.toml'
            path.write_text(POLICY_PATH.read_text(encoding='utf-8').replace(old,new),encoding='utf-8')
            with self.assertRaises(ValueError):load_policy(path)

    def test_reviewer_downgrade_cannot_be_enabled(self):
        self.invalid('allow_reviewer_downgrade = false','allow_reviewer_downgrade = true')

    def test_alias_or_extra_setting_is_not_a_second_model_source(self):
        self.invalid('allow_reviewer_downgrade = false','allow_reviewer_downgrade = false\nalias = "other"')

    def test_worker_cannot_silently_differ_from_executor(self):
        self.invalid('[worker]\nmodel = "gpt-6-luna"','[worker]\nmodel = "other-model"')

    def test_invalid_effort_is_rejected(self):
        self.invalid('reasoning_effort = "high"','reasoning_effort = true')
