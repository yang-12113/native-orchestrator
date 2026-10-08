// User-authorized, read-only restoration of the existing ZCode login. No credential output or disk copy.
import fs from 'node:fs';
import os from 'node:os';
import crypto from 'node:crypto';
const document=JSON.parse(fs.readFileSync('C:/Users/ASUS/.zcode/v2/credentials.json','utf8'));
const secret=process.env.ZCODE_CREDENTIAL_SECRET?.trim() || `zcode-credential-fallback:${process.platform}:${os.homedir()}:${os.userInfo().username}`;
const key=crypto.createHash('sha256').update(secret).digest();
function read(name) {
  const value=document[name];
  if(typeof value!=='string') return '';
  if(!value.startsWith('enc:v1:')) return value;
  const [iv,tag,ciphertext]=value.slice(7).split('.');
  const decipher=crypto.createDecipheriv('aes-256-gcm',key,Buffer.from(iv,'base64url'));
  decipher.setAuthTag(Buffer.from(tag,'base64url'));
  return Buffer.concat([decipher.update(Buffer.from(ciphertext,'base64url')),decipher.final()]).toString('utf8');
}
let jwt='';
try { jwt=read('zcodejwttoken'); } catch { console.log(JSON.stringify({status:'BLOCKED',stage:'native credential restoration'}));process.exit(1); }
const family=read('oauth:active_provider');
let expiresAt=null;
try { expiresAt=JSON.parse(Buffer.from(jwt.split('.')[1],'base64url').toString()).exp; } catch {}
console.log(JSON.stringify({status:'NATIVE_LOGIN_FOUND',family,jwt_present:!!jwt,jwt_expiry_unix:expiresAt}));
if(!jwt) process.exit(1);
for(const suffix of ['current','balance']) {
  try {
    const target='https://zcode.z.ai/api/v1/zcode-plan/billing/'+suffix+(suffix==='balance'?'?app_version=3.14.4.7912':'');
    const response=await fetch(target,{
      headers:{Authorization:jwt,'X-App-Id':'zcode','X-Client-Version':'3.14.4.7912'},signal:AbortSignal.timeout(20000)});
    const body=await response.json();
    function safe(value) {
      if(Array.isArray(value)) return value.map(safe);
      if(value&&typeof value==='object') return Object.fromEntries(Object.entries(value).map(([k,v])=>
        [k,/token|secret|key|uid|user_plan_id|user.?id|phone|email|account.?id|order|logid/i.test(k)?'[REDACTED]':safe(v)]));
      return value;
    }
    console.log(JSON.stringify({endpoint:suffix,status:response.status,billing:safe(body)}));
  } catch(error) { console.log(JSON.stringify({endpoint:suffix,error:error.name+': billing read failed'})); }
}
try {
  const response=await fetch('https://zcode.z.ai/api/v1/client/configs?app_version=3.14.4.7912&platform=win32-x64',{signal:AbortSignal.timeout(15000)});
  const cfg=await response.json();
  console.log(JSON.stringify({endpoint:'native-client-config',status:response.status,
    captcha:cfg.data?.configs?.captcha??null,keys:Object.keys(cfg.data?.configs??{})}));
}catch {console.log(JSON.stringify({endpoint:'native-client-config',status:'UNKNOWN'}));}
key.fill(0);
