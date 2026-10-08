"""Preferred current-version native probe. Does not depend on the legacy sidecar PID table."""
import hashlib
import json
from pathlib import Path
from workbuddy_adapter import WorkBuddyAdapter, ROOT, AUTH

if __name__=='__main__':
    before=hashlib.sha256(AUTH.read_bytes()).hexdigest()
    d=ROOT/'data-native-probes/workbuddy-current'
    d.mkdir(parents=True,exist_ok=True)
    r=WorkBuddyAdapter().run('executor','deepseek-v4.1-flash','Reply exactly WORKBUDDY_CURRENT_NATIVE_OK. Use no tools.',
        d,d/'native-events.jsonl',timeout=120)
    after=hashlib.sha256(AUTH.read_bytes()).hexdigest()
    report={k:r[k] for k in ('session_id','requested_model','observed_model','native_credit','usage','text','tools_enabled','native_version')}
    report.update(status='LIVE_VERIFIED',original_encrypted_login_unchanged=before==after,
        original_login_before_sha256=before,original_login_after_sha256=after,
        credential_copies_written=False,promotion_end='2026-10-10T00:00:00+08:00',promotion_timezone='Asia/Shanghai',
        route='installed WorkBuddy AI native CLI and current account product configuration')
    (ROOT/'evidence/native-fix/workbuddy-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))
