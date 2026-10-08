// Run the installed WorkBuddy AI CLI with an in-memory view of its existing login.
// Explicit user authorization: tokens never leave memory or enter logs/new files.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const input=JSON.parse(await new Promise(resolve=>{let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>resolve(s));}));
const sourceAuth='C:/Users/ASUS/AppData/Local/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop-ai.info';
const sourceProduct='C:/Users/ASUS/.workbuddy-ai/cache/acc-product-config-v3.json';
const product=JSON.parse(fs.readFileSync(sourceProduct,'utf8'));
const model=input.model||'deepseek-v4.1-flash';
if(model!=='deepseek-v4.1-flash'||!product.models.some(m=>m.id===model))throw Error('Explicit native free model unavailable; no fallback');
const promo=product.modelPromotions.find(p=>p.enabled&&p.modelIds.includes(model)&&p.discount?.factor===0&&Date.parse(p.schedule.validFrom)<=Date.now()&&Date.now()<Date.parse(p.schedule.validUntil));
if(!promo)throw Error('ENTITLEMENT_EXPIRED: native zero-credit promotion unavailable; no paid fallback');
const protection=await import('./native_support/workbuddy-credential-format.mjs');
const classified=protection.classifyDesktopAuthDocument(fs.readFileSync(sourceAuth,'utf8'));
const wrapped=classified.wrapped;
if(!wrapped)throw Error('Native login document could not be parsed');
const payload=JSON.parse(String(process._linkedBinding('electron_browser_workbuddy_storage').loggerGet()));
const key=protection.deriveProtectorKey(payload.atRestSecretKey);
const restored=structuredClone(wrapped.document);
for(const field of wrapped.fields){const value=protection.openAuthField(key,field.envelope);if(value===undefined)throw Error('Native encrypted login restoration failed');restored.auth[field.field]=value;}
const secrets=[restored.auth.accessToken,restored.auth.refreshToken,payload.atRestSecretKey];
key.fill(0);
if(restored.auth.domain!=='www.workbuddy.ai')throw Error('Native account region mismatch');
const memoryView=Buffer.from(JSON.stringify(restored));
function sameAuth(p){try{return path.resolve(String(p)).toLowerCase()===path.resolve(sourceAuth).toLowerCase();}catch{return false;}}
const readSync=fs.readFileSync.bind(fs),readAsync=fs.readFile.bind(fs),readPromise=fsp.readFile.bind(fsp);
fs.readFileSync=function(p,opts){if(sameAuth(p))return typeof opts==='string'||opts?.encoding?memoryView.toString(typeof opts==='string'?opts:opts.encoding):Buffer.from(memoryView);return readSync(p,opts);};
fs.readFile=function(p,opts,callback){if(typeof opts==='function'){callback=opts;opts=undefined;}if(sameAuth(p)){const v=typeof opts==='string'||opts?.encoding?memoryView.toString(typeof opts==='string'?opts:opts.encoding):Buffer.from(memoryView);queueMicrotask(()=>callback(null,v));return;}return readAsync(p,opts,callback);};
fsp.readFile=async function(p,opts){if(sameAuth(p))return typeof opts==='string'||opts?.encoding?memoryView.toString(typeof opts==='string'?opts:opts.encoding):Buffer.from(memoryView);return readPromise(p,opts);};
// Native CLI has an explicit in-memory credential policy; additionally guard original auth writes.
const authDirectory=path.resolve(path.dirname(sourceAuth)).toLowerCase();
function protectWrite(p){if(path.resolve(String(p)).toLowerCase().startsWith(authDirectory+path.sep))throw Error('Original native login storage is read-only in this role');}
for(const name of ['writeFileSync','unlinkSync','renameSync','openSync']){const original=fs[name].bind(fs);fs[name]=function(p,...args){if(name!=='openSync'||!String(args[0]).startsWith('r'))protectWrite(p);if(name==='renameSync')protectWrite(args[0]);return original(p,...args);};}
for(const name of ['writeFile','unlink','rename','open']){const original=fsp[name].bind(fsp);fsp[name]=async function(p,...args){if(name!=='open'||!String(args[0]).startsWith('r'))protectWrite(p);if(name==='rename')protectWrite(args[0]);return original(p,...args);};}
const home=path.join(root,'.runtime','workbuddy-'+input.role+'-'+crypto.randomUUID().slice(0,12));fs.mkdirSync(home,{recursive:true});
process.env.CODEBUDDY_CONFIG_DIR=home;process.env.WORKBUDDY_CONFIG_DIR=home;
process.env.ACC_PRODUCT_CONFIG_PATH=sourceProduct;
// This flag skips native file restoration entirely; the in-memory file view plus write guards is used instead.
delete process.env.CODEBUDDY_CREDENTIALS_IN_MEMORY;process.env.CODEBUDDY_DISABLE_IDE='1';
process.env.CODEBUDDY_DISABLE_AUTO_MEMORY='1';process.env.CODEBUDDY_CODE_DISABLE_TERMINAL_TITLE='1';
process.env.WORKBUDDY_APP_NAME='WorkBuddy AI';
delete process.env.ANTHROPIC_API_KEY;delete process.env.OPENAI_API_KEY;
const emptyMcp=path.join(home,'mcp-empty.json');fs.writeFileSync(emptyMcp,'{"mcpServers":{}}');
const settings=path.join(home,'settings.json');fs.writeFileSync(settings,JSON.stringify({memory:{enabled:false},permissions:{defaultMode:'dontAsk'},disableAllHooks:true}));
const output=process.stdout.write.bind(process.stdout),errorOutput=process.stderr.write.bind(process.stderr);
function scrub(s){let t=String(s);for(const secret of secrets)if(typeof secret==='string'&&secret)t=t.split(secret).join('[REDACTED]');return t;}
process.stdout.write=function(chunk,encoding,callback){return output(scrub(Buffer.isBuffer(chunk)?chunk.toString('utf8'):chunk),typeof encoding==='function'?encoding:callback);};
process.stderr.write=function(chunk,encoding,callback){return errorOutput(scrub(Buffer.isBuffer(chunk)?chunk.toString('utf8'):chunk),typeof encoding==='function'?encoding:callback);};
const cli='D:/Downloads/workbuddy/WorkBuddyAI/resources/app.asar.unpacked/cli/bin/codebuddy';
process.argv=[process.execPath,cli,'--print','--output-format','json','--model',model,'--tools','',
  '--permission-mode','dontAsk','--no-session-persistence','--strict-mcp-config','--mcp-config',emptyMcp,
  '--setting-sources','','--settings',settings,'--max-turns','1','--effort','low','--system-prompt',
  'You are an isolated text-artifact executor. Follow only the supplied task and output JSON when asked. No tools, memories, delegation, filesystem writes, or external services.',input.prompt];
process.chdir(input.cwd);
const {createRequire}=await import('node:module');createRequire(import.meta.url)(cli);
