"""One project model-policy file; no aliases or automatic downgrade."""

# Allow direct script entry points as well as package imports after relocation.
if __package__ in (None, ""):
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))

import hashlib
import tomllib
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[2] / 'config/model-policy.toml'
ROLES = ('executor', 'worker', 'reviewer', 'escalation')


def load_policy(path=POLICY_PATH):
    raw = Path(path).read_bytes()
    value = tomllib.loads(raw.decode('utf-8'))
    if set(value) != {'allow_reviewer_downgrade', *ROLES} or value['allow_reviewer_downgrade'] is not False:
        raise ValueError('MODEL_POLICY_INVALID: reviewer downgrade is prohibited')
    for role in ROLES:
        route = value[role]
        if not isinstance(route, dict) or set(route) != {'model', 'reasoning_effort'}:
            raise ValueError('MODEL_POLICY_INVALID: exact role fields required')
        if not isinstance(route['model'], str) or not route['model'] or len(route['model']) > 100:
            raise ValueError('MODEL_POLICY_INVALID: explicit model ID required')
        if route['reasoning_effort'] not in ('low', 'medium', 'high', 'xhigh', 'max'):
            raise ValueError('MODEL_POLICY_INVALID: explicit effort required')
    if value['worker'] != value['executor'] or value['escalation'] != value['reviewer']:
        raise ValueError('MODEL_POLICY_INVALID: worker/executor and reviewer/escalation must agree')
    if len({value[role]['model'] for role in ROLES}) != 2:
        raise ValueError('MODEL_POLICY_INVALID: exactly two model IDs required')
    return {'routes': {role: dict(value[role]) for role in ROLES},
            'allow_reviewer_downgrade': False, 'sha256': hashlib.sha256(raw).hexdigest()}
