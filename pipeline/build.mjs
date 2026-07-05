// CLOUD build: encrypt profit_data.js with DASH_SHARE_PASSWORD and inline it into ../index.html
// (password gate + client-side Web Crypto decrypt). Mirror of scripts/build_share.mjs, repo-relative.
import fs from 'node:fs';
import crypto from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const DATA_JS = path.join(ROOT, 'profit_data.js');
const SRC_HTML = path.join(HERE, 'dashboard_template.html');
const OUT = path.join(ROOT, 'index.html');
const ITER = 200000;

const PW = process.env.DASH_SHARE_PASSWORD;
if (!PW) { console.error('DASH_SHARE_PASSWORD not set'); process.exit(1); }

const raw = fs.readFileSync(DATA_JS, 'utf8');
const m = raw.match(/window\.PROFIT_DATA\s*=\s*(\{[\s\S]*\});/);
if (!m) { console.error('Cannot parse profit_data.js'); process.exit(1); }
const plaintext = m[1];
const salt = crypto.randomBytes(16), iv = crypto.randomBytes(12);
const key = crypto.pbkdf2Sync(PW, salt, ITER, 32, 'sha256');
const c = crypto.createCipheriv('aes-256-gcm', key, iv);
const ct = Buffer.concat([c.update(plaintext, 'utf8'), c.final()]);
const tag = c.getAuthTag();
const ENC = { salt: salt.toString('base64'), iv: iv.toString('base64'),
  data: Buffer.concat([ct, tag]).toString('base64'), iter: ITER };

let html = fs.readFileSync(SRC_HTML, 'utf8');
const gate = `const ENC = ${JSON.stringify(ENC)};
const b2b = b => Uint8Array.from(atob(b), c => c.charCodeAt(0));
async function unlock(pw){
  const km = await crypto.subtle.importKey('raw', new TextEncoder().encode(pw), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey({name:'PBKDF2',salt:b2b(ENC.salt),iterations:ENC.iter,hash:'SHA-256'},
    km, {name:'AES-GCM',length:256}, false, ['decrypt']);
  const pt = await crypto.subtle.decrypt({name:'AES-GCM',iv:b2b(ENC.iv)}, key, b2b(ENC.data));
  return JSON.parse(new TextDecoder().decode(pt));
}
(async function(){
  const KEY='pomy_dash_pw';
  const saved=localStorage.getItem(KEY);
  if(saved){ try{ const d=await unlock(saved); window.PROFIT_DATA=d; init(); return; }catch(e){ localStorage.removeItem(KEY); } }
  const ov = document.createElement('div');
  ov.style.cssText='position:fixed;inset:0;background:#0f1115;display:flex;align-items:center;justify-content:center;z-index:9999';
  ov.innerHTML='<div style="background:#fff;border-radius:16px;padding:30px 34px;max-width:340px;text-align:center;font-family:sans-serif">'
    +'<div style="font-size:30px">🔒</div><h2 style="margin:10px 0 4px">POMY — Profit Dashboard</h2>'
    +'<p style="color:#6b7280;font-size:13px;margin:0 0 16px">Enter password to view</p>'
    +'<input id="pw" type="password" placeholder="Password" style="width:100%;padding:11px;border:1px solid #e5e7eb;border-radius:9px;font-size:15px;text-align:center">'
    +'<div id="err" style="color:#ef4444;font-size:12px;height:16px;margin:8px 0"></div>'
    +'<button id="go" style="width:100%;padding:11px;background:#7c5cff;color:#fff;border:none;border-radius:9px;font-size:15px;font-weight:700;cursor:pointer">Enter</button></div>';
  document.body.appendChild(ov);
  const pw=ov.querySelector('#pw'), err=ov.querySelector('#err'), go=ov.querySelector('#go');
  async function attempt(){
    err.textContent=''; go.textContent='Decrypting…';
    try{ const data=await unlock(pw.value); localStorage.setItem(KEY,pw.value); window.PROFIT_DATA=data; ov.remove(); init(); }
    catch(e){ go.textContent='Enter'; err.textContent='Wrong password'; pw.value=''; pw.focus(); }
  }
  go.onclick=attempt; pw.addEventListener('keydown',e=>{if(e.key==='Enter')attempt();});
  pw.focus();
})();`;
const loaderRe = /\(function\(\)\{const s=document\.createElement\('script'\);s\.src='profit_data\.js[\s\S]*?\}\)\(\);/;
if (!loaderRe.test(html)) { console.error('loader block not found in template'); process.exit(1); }
html = html.replace(loaderRe, gate);
fs.writeFileSync(OUT, html, 'utf8');
console.log('Wrote', OUT);
