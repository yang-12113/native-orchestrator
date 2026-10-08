"""Native ZCode Start Plan route. Fresh entitlement is checked before every isolated call."""
import json
import os
import shutil
import subprocess
from pathlib import Path
from native_rpc import RpcError

ROOT=Path(__file__).resolve().parent

class ZCodeAdapter:
    def run(self,role,model,prompt,cwd,log,schema=None,timeout=180,on_session=None,**options):
        if role!='executor':raise RpcError('Native ZCode dynamic-tool review is not enabled')
        if model!='GLM-5.3-Flash':raise RpcError('MODEL_UNAVAILABLE: explicit authorized Flash model required')
        if schema:prompt+='\nReturn only JSON matching this schema:\n'+json.dumps(schema,ensure_ascii=False)
        request={'role':role,'model':model,'prompt':prompt,'cwd':str(Path(cwd).resolve()),'log':str(log),'timeout_seconds':timeout}
        try:
            process=subprocess.run([shutil.which('node'),str(ROOT/'zcode_native_bridge.mjs')],input=json.dumps(request,ensure_ascii=False),
                text=True,encoding='utf-8',capture_output=True,timeout=timeout+35,env=os.environ.copy(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except subprocess.TimeoutExpired:
            raise TimeoutError('Native ZCode model timeout; reconcile before retrying') from None
        result=json.loads(process.stdout.strip().splitlines()[-1])
        if result.get('status')!='LIVE_VERIFIED':
            message=result.get('error','Native ZCode model route failed')
            if 'unusual activity' in message.lower():message='SERVICE_GUARD: native server rejected the independent request for unusual activity; no automatic retry or fallback'
            raise RpcError(message)
        if result.get('observed_model')!=model:raise RpcError('MODEL_MISMATCH: native response selection differs')
        if on_session:on_session(result['session_id'])
        return result
