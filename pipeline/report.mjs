// CLOUD daily report: build the BeProfit-style HTML for "yesterday" and WhatsApp it to Nicole.
// Reads ../profit_data.js + env WHATSAPP_INSTANCE_ID / WHATSAPP_TOKEN. Sends only when run with --send.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const DATA_JS = path.join(ROOT, 'profit_data.js');
const OUT = path.join(ROOT, 'daily_report.html');
const SEND = process.argv.includes('--send');

const raw = fs.readFileSync(DATA_JS, 'utf8');
const PD = JSON.parse(raw.match(/window\.PROFIT_DATA\s*=\s*(\{[\s\S]*\});/)[1]);
const days = PD.days || [];
const y = new Date(PD.updated + 'T00:00:00Z'); y.setUTCDate(y.getUTCDate() - 1);
const yIso = y.toISOString().slice(0, 10);
const day = days.find(d => d.date === yIso) || days[days.length - 1];
if (!day) { console.log('no day data'); process.exit(0); }

const meta = day.meta_spend || 0, google = day.google_spend || 0, marketing = meta + google;
const net = day.net_sales || 0, gross = day.gross_sales || 0, total = day.total_sales || 0;
const cogs = day.cogs || 0, fees = day.fees || 0, disc = day.discounts || 0;
const conProfit = net - cogs - marketing - fees;
const conMargin = net ? conProfit / net : 0;
const roas = marketing ? total / marketing : 0;
const costsTotal = disc + cogs + fees;
const ils = n => '₪' + Math.round(n).toLocaleString('he-IL');
const pc = n => (n * 100).toFixed(0) + '%';
const dlabel = new Date(day.date + 'T00:00:00Z').toLocaleDateString('he-IL', { day: '2-digit', month: 'long', year: 'numeric' });

const chip = (l, v, c = '#6b4eff') => `<td style="padding:6px"><div style="background:#f4f1ff;border-radius:12px;padding:12px 10px;text-align:center"><div style="color:#8b8b9a;font-size:11px;margin-bottom:4px">${l}</div><div style="color:${c};font-size:18px;font-weight:800">${v}</div></div></td>`;
const costRow = (l, v, dim = false) => `<tr><td style="padding:9px 4px;color:#4b5563;border-bottom:1px solid #eef0f4">${l}</td><td style="padding:9px 4px;text-align:left;color:${dim ? '#b4b9c2' : '#1f2430'};font-weight:600;border-bottom:1px solid #eef0f4">${v}</td></tr>`;

const html = `<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#eef0f6;font-family:'Segoe UI',Arial,sans-serif;color:#1f2430">
<div style="max-width:480px;margin:0 auto;padding:16px"><div style="background:#fff;border-radius:18px;overflow:hidden;box-shadow:0 4px 18px rgba(20,24,40,.08)">
<div style="background:linear-gradient(135deg,#6b4eff,#8b6bff);padding:22px 24px;color:#fff"><div style="font-size:13px;opacity:.9;font-weight:700;letter-spacing:.5px">POMY SPORT</div><div style="font-size:21px;font-weight:800;margin-top:4px">📈 דוח רווחיות יומי</div><div style="font-size:13px;opacity:.9;margin-top:2px">${dlabel}</div></div>
<div style="padding:18px 22px"><p style="margin:0 0 14px;color:#4b5563;font-size:14px">הלקוחות שלך ביצעו <b style="color:#6b4eff">${day.orders}</b> הזמנות! המספרים של אתמול:</p>
<table style="width:100%;border-collapse:collapse"><tr>${chip('הזמנות', day.orders)}${chip('מכירות ברוטו', ils(gross))}${chip('סה״כ מכירות', ils(total))}${chip('ROAS', roas.toFixed(2))}</tr>
<tr>${chip('רווח תרומה', ils(conProfit), '#10b981')}${chip('מרווח', pc(conMargin), '#10b981')}${chip('COGS', ils(cogs), '#6366f1')}${chip('פרסום', ils(marketing), '#1877f2')}</tr></table>
<div style="margin-top:18px;background:#faf9ff;border-radius:12px;padding:14px 16px"><table style="width:100%;border-collapse:collapse;font-size:13px"><tr><td style="padding:6px 4px;color:#6b4eff;font-weight:800">מכירות ברוטו</td><td style="padding:6px 4px;text-align:left;font-weight:800">${ils(gross)}</td></tr><tr><td style="padding:6px 4px;color:#ef4444;font-weight:800">סך עלויות</td><td style="padding:6px 4px;text-align:left;color:#ef4444;font-weight:800">${ils(costsTotal)}</td></tr></table>
<table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:4px">${costRow('הנחות', ils(disc))}${costRow('עלות מוצר+משלוח', ils(cogs))}${costRow('עמלות סליקה', ils(fees))}</table></div>
<div style="margin-top:14px;background:#faf9ff;border-radius:12px;padding:14px 16px"><table style="width:100%;border-collapse:collapse;font-size:13px"><tr><td style="padding:6px 4px;color:#6b4eff;font-weight:800">הוצאות פרסום</td><td style="padding:6px 4px;text-align:left;font-weight:800">${ils(marketing)}</td></tr>${costRow('Facebook', ils(meta))}${costRow('Google', ils(google))}</table></div>
</div></div></div></body></html>`;
fs.writeFileSync(OUT, html, 'utf8');
console.log('Wrote', OUT, 'for', day.date);

const sign = conProfit >= 0 ? '✅' : '🔴';
const text = `📈 *דוח רווחיות יומי — POMY*\n🗓️ ${dlabel}\n\n🛒 הזמנות: *${day.orders}*  |  ROAS: *${roas.toFixed(2)}*\n💰 מכירות: *${ils(total)}*\n📣 פרסום: *${ils(marketing)}* (FB ${ils(meta)} · G ${ils(google)})\n📦 COGS: ${ils(cogs)}  |  💳 עמלות: ${ils(fees)}\n${sign} *רווח: ${ils(conProfit)}* (${pc(conMargin)})\n\nהדוח המלא מצורף 👇`;

if (SEND) {
  const ID = process.env.WHATSAPP_INSTANCE_ID, TOKEN = process.env.WHATSAPP_TOKEN;
  const chatId = '972505960311@c.us';
  const fd = new FormData();
  fd.append('chatId', chatId);
  fd.append('fileName', 'POMY-daily-report.html');
  fd.append('caption', text);
  fd.append('file', new Blob([fs.readFileSync(OUT)], { type: 'text/html' }), 'POMY-daily-report.html');
  const res = await fetch(`https://api.green-api.com/waInstance${ID}/sendFileByUpload/${TOKEN}`, { method: 'POST', body: fd });
  console.log('WhatsApp', res.status, (await res.text()).slice(0, 120));
} else {
  console.log('(no --send)');
}
