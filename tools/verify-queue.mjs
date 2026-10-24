// 验证排队消息：入队 → 重新编辑 → 内容回到输入框
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const PIN = process.argv[2];
const OUT = process.argv[3] || '.';
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9338;
const BASE = 'http://127.0.0.1:8787';
const profile = path.join(os.tmpdir(), 'cdp-q-' + Date.now());
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

  // 建一个会跑一会儿的手机任务
  const created = await ev(`(async () => {
    const pin = localStorage.getItem('console_pin') || '';
    const H = { 'X-Console-Pin': pin, 'Content-Type': 'application/json' };
    const r = await (await fetch('/api/threads', { method: 'POST', headers: H,
      body: JSON.stringify({ name: '排队编辑测试', prompt: '请从 1 数到 200，每行一个数字，不要省略。' }) })).json();
    return r.thread ? r.thread.id : null;
  })()`);
  console.log('  thread:', created);
  if (!created) { throw new Error('创建任务失败'); }
  await sleep(2500);

  // 打开侧栏 → 手机任务 → 点开该会话
  await ev(`document.querySelector('button[aria-label="会话列表"]')?.click()`);
  await sleep(900);
  await ev(`document.querySelectorAll('.seg button')[0]?.click()`);
  await sleep(1200);
  let opened = false;
  for (let tab = 0; tab < 2 && !opened; tab++) {
    await ev(`document.querySelectorAll('.seg button')[]?.click()`);
    await sleep(1600);
    const titles = await ev(`[...document.querySelectorAll('.drawer .row .row-title')].map((e) => e.textContent).join('|')`);
    console.log('  tab', tab, 'rows:', titles);
    opened = await ev(`(() => {
      const rows = [...document.querySelectorAll('.drawer .row')];
      const r = rows.find((x) => (x.querySelector('.row-title')?.textContent || '').includes('排队编辑测试'));
      if (r) { r.click(); return true; }
      return false;
    })()`);
  }
  console.log('  opened:', opened);
  await sleep(3500);

  // 输入文字并点发送（繁忙 → 入队）
  await ev(`(() => {
    const ta = document.querySelector('.composer-box textarea');
    if (!ta) return false;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(ta, '这条是排队的测试消息');
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  })()`);
  await sleep(600);
  await ev(`(() => { const btns=[...document.querySelectorAll('.composer-send, .composer-btn')];
    const send=btns.find((b)=>b.classList.contains('composer-send') && !b.classList.contains('stop'));
    if(send){ send.click(); return true; } return false; })()`);
  await sleep(2500);
  console.log('  queue chips:', await ev(`document.querySelectorAll('.queue-chip').length`));
  console.log('  chip width vs composer:', await ev(`(() => {
    const q = document.querySelector('.queue-chip'); const c = document.querySelector('.composer-box');
    if (!q || !c) return null;
    return { chip: Math.round(q.getBoundingClientRect().width), composer: Math.round(c.getBoundingClientRect().width) };
  })()`));
  await shot('screenshots/手机端-排队编辑.png');

  // 点「重新编辑」
  const clickedEdit = await ev(`(() => { const b = document.querySelector('.queue-edit'); if (b) { b.click(); return true; } return false; })()`);
  await sleep(1200);
  console.log('  clicked edit:', clickedEdit);
  console.log('  textarea value:', await ev(`document.querySelector('.composer-box textarea')?.value || ''`));
  console.log('  queue chips after:', await ev(`document.querySelectorAll('.queue-chip').length`));
  await shot('screenshots/手机端-排队重新编辑.png');

  // 清理
  await ev(`(async () => { const pin = localStorage.getItem('console_pin') || '';
    await fetch('/api/threads/${created}/delete', { method: 'POST', headers: { 'X-Console-Pin': pin } }); })()`);
  ws.close(); child.kill();
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch {}
}
main().catch((e) => { console.error('FAIL', e.message); try { child.kill(); } catch {}; process.exit(1); });
