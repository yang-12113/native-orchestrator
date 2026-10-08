"""First-party WorkBuddy AI CLI adapter, with a time-checked zero-credit model route."""
import json
import os
import subprocess
from pathlib import Path
from native_rpc import RpcError

ROOT=Path(__file__).resolve().parent
AUTH=Path('C:/Users/ASUS/AppData/Local/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop-ai.info')
APP=Path('D:/Downloads/workbuddy/WorkBuddyAI/WorkBuddyAI.exe')

class WorkBuddyAdapter:
    def run(self,role,model,prompt,cwd,log,schema=None,timeout=180,on_session=None,**options):
        if role!='executor':
            raise RpcError('Native WorkBuddy dynamic read-tool review is not enabled; keep the verified independent reviewer route')
        if model!='deepseek-v4.1-flash':
            raise RpcError('MODEL_UNAVAILABLE: exact authorized WorkBuddy model required')
        if schema:
            prompt+='\nReturn ONLY a JSON object matching this schema, without markdown fences:\n'+json.dumps(schema,ensure_ascii=False)
        env=os.environ.copy();env['ELECTRON_RUN_AS_NODE']='1';env['PYTHONIOENCODING']='utf-8'
        request={'role':role,'model':model,'prompt':prompt,'cwd':str(Path(cwd).resolve())}
        process=subprocess.Popen([str(APP),str(ROOT/'workbuddy_native_bridge.mjs')],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',env=env,
            cwd=cwd,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            output,errors=process.communicate(json.dumps(request,ensure_ascii=False),timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill();output,errors=process.communicate()
            raise TimeoutError('Native WorkBuddy turn timed out; no automatic model fallback') from None
        Path(log).write_text(json.dumps({'native_client':'WorkBuddy AI','requested_model':model,
            'stdout':output,'stderr':errors},ensure_ascii=False),encoding='utf-8')
        if process.returncode!=0:
            raise RpcError('Native WorkBuddy CLI failed; see task-local redacted evidence')
        try:
            messages=json.loads(output)
        except ValueError:
            if 'Authentication required' in output:
                raise RpcError('Native WorkBuddy login restoration failed') from None
            raise RpcError('Native WorkBuddy response did not contain valid protocol JSON') from None
        if not isinstance(messages,list):messages=[messages]
        result=next((m for m in reversed(messages) if m.get('type')=='result'),None)
        if not result or result.get('is_error') or result.get('subtype')!='success':
            raise RpcError('Native WorkBuddy did not finish successfully')
        observed={m.get('providerData',{}).get('model') for m in messages if m.get('providerData',{}).get('model')}
        if observed!={model}:
            raise RpcError('MODEL_MISMATCH: native reported model does not match explicit request')
        assistant=[m for m in messages if m.get('role')=='assistant' and m.get('type')=='message']
        credits=[m.get('providerData',{}).get('rawUsage',{}).get('credit') for m in assistant]
        if not credits or any(type(x) not in (int,float) or x!=0 for x in credits):
            raise RpcError('Native zero-credit route could not be verified; stop rather than assume free coverage')
        sid=result['session_id']
        if on_session:on_session(sid)
        text=result['result']
        if schema:
            json.loads(text)  # Invalid proposals remain invalid; no markdown/code extraction.
        return {'session_id':sid,'requested_model':model,'observed_model':model,'text':text,
            'usage':result.get('usage'),'native_credit':sum(credits),'account_type':'existing WorkBuddy AI native login',
            'native_version':'5.6.2','tools_enabled':0,'native_session_persistence':False,
            'memory_isolation':'private CLI config directory; no inherited conversation; no model memory tools'}
