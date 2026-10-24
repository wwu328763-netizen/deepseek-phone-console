// 验证：计划条 + 斜杠命令菜单（先打开一个带 plan 的会话）
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const PIN = process.argv[2];
const OUT = process.argv[3] || '.';
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9337;
const BASE = 'http://127.0.0.1:8787';
const profile = path.join(os.tmpdir(), 'cdp-v2-' + Date.now());
const child = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
  '--remote-debugging-port=' + PORT, '--user-data-dir=' + profile, 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  for (let i = 0; i < 60; i++) { try { await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); break; } catch { await sleep(200); } }
  const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  let id = 0; const pending = new Map();
  ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
  await new Promise((r) => ws.addEventListener('open', r));
  const send = (method, params = {}) => new Promise((res) => { const mid = ++id; pending.set(mid, (m) => res(m.result ?? m)); ws.send(JSON.stringify({ id: mid, method, params })); });
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true, screenWidth: 390, screenHeight: 844 });
  await send('Page.navigate', { url: BASE + '/?pin=' + PIN });
  await sleep(5000);
  const ev = async (expr) => (await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result?.value;
  const shot = async (name) => {
    const r = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(OUT, name), Buffer.from(r.data, 'base64'));
    console.log('  saved', name);
  };

  // 找一个带 plan/todos 的电脑端会话
  const target = await ev(`(async () => {
    const pin = localStorage.getItem('console_pin') || '';
    const H = { 'X-Console-Pin': pin };
    const list = await (await fetch('/api/sessions', { headers: H })).json();
    for (const s of (list.sessions || [])) {
      if (s.source !== 'desktop') continue;
      try {
        const d = await (await fetch('/api/sessions/' + s.id, { headers: H })).json();
        if (d.plan && d.plan.goal && d.plan.goal.objective) {
          return { id: s.id, name: s.name, todos: (d.plan.todos || []).length, goal: !!(d.plan.goal && d.plan.goal.objective) };
        }
      } catch (e) {}
    }
    return null;
  })()`);
  console.log('  plan session:', JSON.stringify(target));

  if (target) {
    // 打开侧栏 → 电脑端 → 点击该行
    await ev(`document.querySelector('button[aria-label="会话列表"]')?.click()`);
    await sleep(900);
    await ev(`document.querySelectorAll('.seg button')[1]?.click()`);
    await sleep(1400);
    const clicked = await ev(`(() => {
      const rows = [...document.querySelectorAll('.drawer .row')];
      const r = rows.find((x) => (x.querySelector('.row-title')?.textContent || '') === ${JSON.stringify((target && target.name) || '')});
      if (r) { r.click(); return true; }
      return false;
    })()`);
    console.log('  clicked row:', clicked);
    await sleep(4500);
    console.log('  plan-bar present:', await ev(`!!document.querySelector('.plan-bar')`));
    console.log('  plan text:', await ev(`document.querySelector('.plan-bar .plan-cur')?.textContent || ''`));
    await shot('screenshots/手机端-目标.png');
    await ev(`document.querySelector('.slash-glyph')?.closest('button')?.click()`);
    await sleep(900);
    console.log('  cmd rows:', await ev(`document.querySelectorAll('.cmd-row').length`));
    console.log('  cmd names:', await ev(`[...document.querySelectorAll('.cmd-name')].map((e)=>e.textContent).join('|')`));
    await shot('screenshots/手机端-命令菜单.png');
  } else {
    console.log('  没有找到带 plan 的会话');
  }
  ws.close(); child.kill();
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch {}
}
main().catch((e) => { console.error('FAIL', e.message); try { child.kill(); } catch {}; process.exit(1); });
