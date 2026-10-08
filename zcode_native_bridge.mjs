// Native ZCode RPC bridge. Existing login is restored in memory only, as explicitly authorized.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import readline from 'node:readline';
import {fileURLToPath} from 'node:url';
const request=JSON.parse(await new Promise(resolve=>{let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>resolve(s));}));
const root=path.dirname(fileURLToPath(import.meta.url));
const credentials=JSON.parse(fs.readFileSync('C:/Users/ASUS/.zcode/v2/credentials.json','utf8'));
const secret=process.env.ZCODE_CREDENTIAL_SECRET?.trim() || `zcode-credential-fallback:${process.platform}:${os.homedir()}:${os.userInfo().username}`;
const cipherKey=crypto.createHash('sha256').update(secret).digest();
function credential(name) {
  const v=credentials[name];if(typeof v!=='string')return '';
  if(!v.startsWith('enc:v1:'))return v;
  const [iv,tag,c]=v.slice(7).split('.');const d=crypto.createDecipheriv('aes-256-gcm',cipherKey,Buffer.from(iv,'base64url'));
  d.setAuthTag(Buffer.from(tag,'base64url'));return Buffer.concat([d.update(Buffer.from(c,'base64url')),d.final()]).toString('utf8');
}
let jwt='';let child;
function scrub(value) {
  if(Array.isArray(value))return value.map(scrub);
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,/api.?key|token|secret|authorization|user_plan_id|user.?id|uid|email|phone/i.test(k)?'[REDACTED]':scrub(v)]));
  if(typeof value==='string'&&jwt)return value.split(jwt).join('[REDACTED]');
  return value;
}
try {
  jwt=credential('zcodejwttoken');const family=credential('oauth:active_provider');
  if(family!=='bigmodel'||!jwt)throw Error('Native BigModel login unavailable');
  const model=request.model||'GLM-5.3-Flash';
  if(model!=='GLM-5.3-Flash')throw Error('Only the authorized native Flash model is enabled');
  const response=await fetch('https://zcode.z.ai/api/v1/zcode-plan/billing/current',{
    headers:{Authorization:'Bearer '+jwt,'X-App-Id':'zcode','X-Client-Version':'3.14.4.7912'},signal:AbortSignal.timeout(20000)});
  const billing=await response.json();if(!response.ok||billing.code!==0)throw Error('Native plan read failed');
  const active=billing.data.plans.filter(p=>p.status==='active'&&p.ends_at>billing.data.server_time&&p.entitlements.some(e=>e.capabilities.includes('model:glm-5.3-flash')));
  if(!active.length)throw Error('ENTITLEMENT_EXPIRED: native Flash grant unavailable; no paid fallback');
  const provider='account:bigmodel-start-plan';
  const builtin=path.resolve('D:/Downloads/ZCode/resources/config/provider/zcode-builtin.json');
  const table=JSON.parse(fs.readFileSync(builtin,'utf8'));
  const home=path.resolve(root,'.runtime','zcode-'+request.role+'-'+crypto.randomUUID().slice(0,12));
  fs.mkdirSync(path.join(home,'v2'),{recursive:true});fs.mkdirSync(path.join(home,'cli'),{recursive:true});
  const personal=path.join(home,'v2','provider_config.json');
  fs.writeFileSync(personal,JSON.stringify({schemaVersion:1,config:{providerConfigRules:{providerRules:[]},modelConfigRules:{providerModelRules:[],manualProviderModelRules:[]}}}));
  fs.writeFileSync(path.join(home,'v2','setting.json'),JSON.stringify({memoryEnabled:false,nativeSearchEnhancementsEnabled:false}));
  fs.writeFileSync(path.join(home,'cli','config.json'),JSON.stringify({features:{memory:false,mcp:false,subagent:false,skill:false},memory:{use:false},plugins:{enabled:false},permission:{mode:'plan'}}));
  const existingTelemetry=JSON.parse(fs.readFileSync('C:/Users/ASUS/.zcode/v2/telemetry-state.json','utf8'));
  const env={...process.env,ZCODE_HOME:home,ZCODE_APP_VERSION:'3.14.4',ZCODE_TELEMETRY_DEVICE_MID:existingTelemetry.deviceMid,
    ZCODE_BUILTIN_PROVIDER_CONFIG_FILE:builtin,ZCODE_PERSONAL_PROVIDER_CONFIG_FILE:personal};
  delete env.ZCODE_BASE_URL;delete env.ANTHROPIC_API_KEY;
  child=spawn(process.execPath,['D:/Downloads/ZCode/resources/glm/zcode.cjs','app-server'],{cwd:request.cwd,env,windowsHide:true,stdio:['pipe','pipe','pipe']});
  const pending=new Map();let seq=0;
  function log(direction,message){if(request.log)fs.appendFileSync(request.log,JSON.stringify({time:Date.now()/1000,direction,message:scrub(message)})+'\n');}
  function send(m){log('send',m);child.stdin.write(JSON.stringify(m)+'\n');}
  function call(method,params,timeout=30000){return new Promise((resolve,reject)=>{const id=String(++seq);const timer=setTimeout(()=>{pending.delete(id);reject(Error('Native RPC timeout: '+method));},timeout);pending.set(id,{resolve,reject,timer});send({id,method,params});});}
  readline.createInterface({input:child.stdout}).on('line',line=>{
    let m;try{m=JSON.parse(line);}catch{return;}log('receive',m);
    if(m.id!==undefined&&!m.method){const p=pending.get(String(m.id));if(p){clearTimeout(p.timer);pending.delete(String(m.id));m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}return;}
    if(m.id!==undefined&&m.method){
      const params=m.params||{};
      if(m.method==='interaction/requestProviderRuntimeHeaders')send({id:m.id,result:params.providerId===provider?{headersApplied:true,requestAuth:{apiKey:jwt}}:{headersApplied:false}});
      else if(m.method==='session/requestRuntimePreferences')send({id:m.id,result:{nativeSearchEnhancementsEnabled:false,memoryEnabled:false,askUserQuestionAutoResolutionEnabled:false}});
      else if(m.method==='interaction/requestPermission')send({id:m.id,result:{decision:'deny',reason:'Text-only isolated role'}});
      else send({id:m.id,error:{code:-32601,message:'Capability unavailable in isolated role'}});
    }
  });
  child.stderr.on('data',x=>log('stderr',{text:x.toString()}));
  child.on('exit',()=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Native process closed'));}pending.clear();});
  await call('runtime/capabilities',{});
  const revision=`zcode-builtin:${table.revision}:${crypto.createHash('sha256').update(builtin).digest('hex')}`;
  await call('provider/updateAccountConfig',{revision:'native-orchestrator:'+Date.now(),basedOnZCodeBuiltinRevision:revision,
    providers:{[provider]:{access:{type:'zhipu-account',entitled:true}}},states:{[provider]:{availability:'available',entitled:true,current:true}}});
  const workspace={workspaceKey:'native-orchestrator:'+crypto.randomUUID(),workspacePath:path.resolve(request.cwd)};
  const selection={providerId:provider,modelId:model,options:{reasoningLevel:'low'}};
  const snapshot=await call('session/create',{workspace,model:selection,persistence:'deferred',mode:'plan',mcpServers:[],toolAllowlist:['__no_tools__'],titleGenerationEnabled:false,dynamicWorkflowEnabled:false,offPeakToolEnabled:false});
  const result=await call('workspace/generateText',{workspace,selection,prompt:request.prompt,tools:[],querySource:'native_orchestrator_'+request.role,maxOutputTokens:request.maxOutputTokens||8192},(request.timeout_seconds||180)*1000);
  if(result.selection?.providerId!==provider||result.selection?.modelId!==model)throw Error('MODEL_MISMATCH: native selection changed');
  console.log(JSON.stringify(scrub({status:'LIVE_VERIFIED',session_id:snapshot.session.sessionId,initial_messages:snapshot.messages.length,
    requested_model:model,observed_model:result.selection.modelId,provider:result.selection.providerId,text:result.text,usage:result.usage,
    entitlement:{route:'native ZCode Start Plan',server_time:billing.data.server_time,plans:active.map(p=>({plan_id:p.plan_id,status:p.status,ends_at:p.ends_at,entitlements:p.entitlements}))},
    tools_enabled:0,memory_enabled:false,role_home:home})));
}catch(error){console.log(JSON.stringify({status:'BLOCKED',error:scrub(error.message)}));process.exitCode=1;}
finally{cipherKey.fill(0);jwt='';if(child){child.stdin.end();const timer=setTimeout(()=>child.kill(),4000);timer.unref();}}
