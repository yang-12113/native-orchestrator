// Explicitly authorized credentials are used only as in-memory search needles.
// Outputs file counts and redacted findings, never a credential or key.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import * as protection from './native_support/workbuddy-credential-format.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));
const src='C:/Users/ASUS/AppData/Local/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop-ai.info';
const wrapped=protection.classifyDesktopAuthDocument(fs.readFileSync(src,'utf8')).wrapped;
const payload=JSON.parse(String(process._linkedBinding('electron_browser_workbuddy_storage').loggerGet()));
const wbKey=protection.deriveProtectorKey(payload.atRestSecretKey);
const needles=wrapped.fields.map(f=>protection.openAuthField(wbKey,f.envelope)).filter(Boolean);
needles.push(payload.atRestSecretKey,wbKey.toString('base64'));wbKey.fill(0);
const zc=JSON.parse(fs.readFileSync('C:/Users/ASUS/.zcode/v2/credentials.json','utf8'));
const nativeSecret=process.env.ZCODE_CREDENTIAL_SECRET?.trim()||`zcode-credential-fallback:${process.platform}:${os.homedir()}:${os.userInfo().username}`;
const zcKey=crypto.createHash('sha256').update(nativeSecret).digest();
const value=zc.zcodejwttoken;
if(value?.startsWith('enc:v1:')){const [iv,tag,c]=value.slice(7).split('.');const d=crypto.createDecipheriv('aes-256-gcm',zcKey,Buffer.from(iv,'base64url'));d.setAuthTag(Buffer.from(tag,'base64url'));needles.push(Buffer.concat([d.update(Buffer.from(c,'base64url')),d.final()]).toString('utf8'));}
else if(value)needles.push(value);zcKey.fill(0);
let files=0;const findings=[];
function inspect(folder){for(const item of fs.readdirSync(folder,{withFileTypes:true})){const file=path.join(folder,item.name);if(item.isDirectory()){if(!['node_modules','.runtime'].includes(item.name))inspect(file);}else if(/\.(json|jsonl|log|md|py|mjs|ps1|txt)$/.test(item.name)){files++;const text=fs.readFileSync(file,'utf8');if(needles.some(n=>n?.length>30&&text.includes(n)))findings.push(path.relative(root,file));}}}
inspect(path.join(root,'evidence'));
for(const folder of ['data-workbuddy-live','data-live'])inspect(path.join(root,folder));
console.log(JSON.stringify({credential_scan:'COMPLETED',files_checked:files,plaintext_credential_findings:findings,passed:findings.length===0}));
process.exitCode=findings.length?1:0;
