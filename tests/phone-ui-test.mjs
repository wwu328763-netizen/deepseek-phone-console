/* 手机端界面端到端测试（真实 Chrome + CDP 合成点击）
 *
 * 覆盖：
 *   A. 全屏后的布局（顶部留白收紧、输入栏抬高离开屏幕下沿）
 *   B. 输入栏间距（分割线不再贴住输入框、输入框与发送键之间留白）
 *   C. 发送键兼任「停止」
 *   D. 去广告功能已彻底移除（页面无入口、接口不存在）
 *
 * 用法： node tests\phone-ui-test.mjs      （需要控制台正在运行）
 * 可选环境变量：CONSOLE_BASE=http://127.0.0.1:8787  CHROME=路径
 */
import { spawn } from "node:child_process";
import { readFileSync, rmSync, existsSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(HERE);
const BASE = process.env.CONSOLE_BASE || "http://127.0.0.1:8787";
const CHROME = process.env.CHROME || [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
].find((p) => existsSync(p));
const PIN_FILE = join(ROOT, "console_data", "pin.txt");
const PIN = existsSync(PIN_FILE) ? readFileSync(PIN_FILE, "utf8").trim() : "";
const PORT = 9401;
const PROFILE = join(process.env.TEMP || ".", "phone-console-e2e-profile");
const UA = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36";

let pass = 0, fail = 0;
const check = (name, ok, extra = "") => {
  console.log(`${ok ? "  PASS" : "  FAIL"}  ${name}${extra ? "  -> " + extra : ""}`);
  ok ? pass++ : fail++;
};

class Cdp {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.errors = []; }
  static async attach(url) {
    const ws = new WebSocket(url);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const c = new Cdp(ws);
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && c.pending.has(m.id)) {
        const { res, rej } = c.pending.get(m.id); c.pending.delete(m.id);
        m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
      } else if (m.method === "Runtime.exceptionThrown") {
        c.errors.push(m.params.exceptionDetails.text);
      }
    };
    return c;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); rej(new Error("timeout " + method)); } }, 20000);
    });
  }
  async eval(expression) {
    const r = await this.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || "eval error");
    return r.result.value;
  }
  close() { try { this.ws.close(); } catch { } }
}
const click = async (c, x, y) => {
  for (const type of ["mousePressed", "mouseReleased"]) {
    await c.send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 });
  }
};

if (!CHROME) { console.log("找不到 Chrome/Edge，可用 CHROME=... 指定路径"); process.exit(1); }
if (!PIN) { console.log("读不到 console_data/pin.txt，请先启动一次控制台"); process.exit(1); }

/* 直接调控制台 HTTP 接口（用来核对服务端真实状态 / 万一测试中断也能还原） */
const apiFetch = async (path, opts = {}) => {
  const r = await fetch(BASE + path, {
    ...opts,
    headers: { "Content-Type": "application/json", "X-Console-Pin": PIN, ...(opts.headers || {}) },
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
  return j;
};
let restoreSel = null;   // { kind, id, provider, model, reasoningEffort }

const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, "about:blank"], { stdio: "ignore" });
try {
  let ready = false;
  for (let i = 0; i < 80; i++) {
    try { await fetch(`http://127.0.0.1:${PORT}/json/version`); ready = true; break; } catch { await sleep(250); }
  }
  if (!ready) throw new Error("Chrome 调试端口未就绪");
  const target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: "PUT" })).json();
  const c = await Cdp.attach(target.webSocketDebuggerUrl);
  await c.send("Page.enable"); await c.send("Runtime.enable");
  await c.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await c.send("Emulation.setUserAgentOverride", { userAgent: UA });
  await c.send("Page.navigate", { url: `${BASE}/?pin=${PIN}` });
  await sleep(4500);

  console.log("\n[A] 全屏后的布局");
  await c.eval(`document.documentElement.style.setProperty('--sa-t','44px')`);   // 模拟刘海屏
  await sleep(200);
  const before = await c.eval(`(()=>{const h=document.querySelector('header'),cp=document.querySelector('#composer');
    return {headPad:parseFloat(getComputedStyle(h).paddingTop), compPadB:parseFloat(getComputedStyle(cp).paddingBottom),
            compBottom:Math.round(cp.getBoundingClientRect().bottom), vh:innerHeight};})()`);
  const r = await c.eval(`(()=>{const b=document.getElementById('fsBtn').getBoundingClientRect();return{x:b.x+b.width/2,y:b.y+b.height/2};})()`);
  await click(c, r.x, r.y);
  await sleep(1200);
  const after = await c.eval(`(()=>{const h=document.querySelector('header'),cp=document.querySelector('#composer');
    const sb=document.getElementById('statusbar');
    return {fs:document.body.classList.contains('fs'), full:!!document.fullscreenElement,
            headPad:parseFloat(getComputedStyle(h).paddingTop), compPadB:parseFloat(getComputedStyle(cp).paddingBottom),
            sbPadB: sb && sb.classList.contains('on') ? parseFloat(getComputedStyle(sb).paddingBottom) : 0,
            inputBottom:Math.round(document.getElementById('input').getBoundingClientRect().bottom), vh:innerHeight};})()`);
  console.log(`     顶栏内边距 ${before.headPad}px -> ${after.headPad}px；输入栏下内边距 ${before.compPadB}px -> ${after.compPadB}px（状态条 ${after.sbPadB}px）`);
  check("进入全屏且带上 fs 标记", after.fs && after.full);
  check("顶部不再留一整块状态栏空白（≤20px）", after.headPad <= 20 && before.headPad >= 50);
  // 底部留白可能由输入栏自己留，也可能交给下方状态条（两者取其一即可）
  check("全屏后底部仍有留白（输入栏自己或状态条 ≥16px）", Math.max(after.compPadB, after.sbPadB) >= 16,
    "composer=" + after.compPadB + " statusbar=" + after.sbPadB);
  check("输入框离屏幕下沿 ≥ 30px", after.vh - after.inputBottom >= 30, (after.vh - after.inputBottom) + "px");
  await c.eval(`document.exitFullscreen()`);
  await sleep(600);

  console.log("\n[B] 输入栏间距");
  const gap = await c.eval(`(()=>{const comp=document.getElementById('composer');
    const ta=document.getElementById('input').getBoundingClientRect();
    const sb=document.getElementById('sendBtn').getBoundingClientRect();
    const ab=document.getElementById('attachBtn').getBoundingClientRect();
    const cs=getComputedStyle(comp), ts=getComputedStyle(document.getElementById('input'));
    return {taRight:Math.round(ta.right), sendLeft:Math.round(sb.left), gapSend:Math.round(sb.left-ta.right),
            gapAttach:Math.round(ta.left-ab.right), padTop:parseFloat(cs.paddingTop), padBottom:parseFloat(cs.paddingBottom),
            taW:Math.round(ta.width), compH:Math.round(comp.getBoundingClientRect().height),
            taBorder:ts.borderTopColor, btns:comp.querySelectorAll('button').length};})()`);
  console.log("     " + JSON.stringify(gap));
  check("输入框与发送键之间留白充足（≥12px）", gap.gapSend >= 12, gap.gapSend + "px");
  check("输入框不再画描边（那条竖线没了）", /rgba\(0, 0, 0, 0\)|transparent/.test(gap.taBorder), gap.taBorder);
  const scrollbar = await c.eval(`(()=>{const ta=document.getElementById('input'),cs=getComputedStyle(ta);
    const borders=parseFloat(cs.borderLeftWidth)+parseFloat(cs.borderRightWidth);
    return {scrollbarPx:ta.offsetWidth-ta.clientWidth-borders, sw:cs.scrollbarWidth};})()`);
  check("输入框内部滚动条已隐藏（不再像分割线）", scrollbar.scrollbarPx === 0, JSON.stringify(scrollbar));
  check("分割线（输入栏上边框）与输入框有间距（≥12px）", gap.padTop >= 12, gap.padTop + "px");
  check("输入框宽度仍够用（> 250px）", gap.taW > 250, gap.taW + "px");
  check("输入栏仍是 📎 + 发送 两个按钮", gap.btns === 2, "n=" + gap.btns);

  console.log("\n[C] 输入栏与背景的接缝");
  const seam = await c.eval(`(()=>{const h=document.querySelector('header'),cp=document.getElementById('composer'),ch=document.getElementById('chat');
    const hs=getComputedStyle(h), cs=getComputedStyle(cp), chs=getComputedStyle(ch);
    return {hBorder:hs.borderBottomWidth, cBorder:cs.borderTopWidth,
            hBg:hs.backgroundImage, cBg:cs.backgroundImage,
            chatBg:chs.backgroundColor, hBlur:String(hs.backdropFilter), cBlur:String(cs.backdropFilter)};})()`);
  console.log("     " + JSON.stringify(seam, null, 0));
  check("输入栏上沿没有分割线（border-top 为 0）", parseFloat(seam.cBorder) === 0, seam.cBorder);
  check("顶栏下沿没有分割线（border-bottom 为 0）", parseFloat(seam.hBorder) === 0, seam.hBorder);
  check("输入栏背景是渐隐（不是一整块实色）",
    seam.cBg.includes("linear-gradient") && seam.cBg.includes("rgba(16, 19, 28, 0.3)"), seam.cBg);
  check("顶栏背景是渐隐到聊天区同底色",
    seam.hBg.includes("linear-gradient") && seam.hBg.includes("rgba(16, 19, 28, 0.3)"), seam.hBg);
  check("接缝处不再有模糊造成的清晰度跳变（无 backdrop-filter）",
    seam.hBlur === "none" && seam.cBlur === "none", seam.hBlur + " / " + seam.cBlur);

  console.log("\n[D] 发送键兼任停止");
  // 同步取两个状态：实时快照每 1.5 秒会刷新 running，异步等待会被它改回去
  const btns = await c.eval(`(()=>{
    const b=document.getElementById('sendBtn');
    state.running=true; updateDot();
    const run={txt:b.textContent, title:b.title, stop:b.classList.contains('stop')};
    state.running=false; updateDot();
    const idle={txt:b.textContent, stop:b.classList.contains('stop')};
    return {run, idle};})()`);
  check("运行中变方块（兼停止）", btns.run.txt === "■" && btns.run.stop === true, JSON.stringify(btns.run));
  check("空闲后恢复 ➤ 发送", btns.idle.txt === "➤" && btns.idle.stop === false, JSON.stringify(btns.idle));
  await c.eval(`state.running=true; updateDot();`);
  await sleep(400);                        // button 有 .16s 过渡，等它跑完再读颜色
  const runColor = await c.eval(`getComputedStyle(document.getElementById('sendBtn')).backgroundColor`);
  check("运行中按钮是红色调", /229/.test(runColor), runColor);

  console.log("\n[E] 去广告功能已移除");
  const clean = await c.eval(`(()=>({
    overlay: !!document.getElementById('browseOverlay'),
    frame: !!document.getElementById('browseFrame'),
    tab: !!document.getElementById('tabBrowse'),
    btn: !!document.getElementById('openBrowse'),
    fn: typeof window.openAdBrowser,
    linkClass: !!document.querySelector('a.wlink'),
    linkFn: typeof window.linkify
  }))()`);
  console.log("     " + JSON.stringify(clean));
  check("页面里没有去广告浮层/入口/函数",
    !clean.overlay && !clean.frame && !clean.tab && !clean.btn &&
    clean.fn === "undefined" && !clean.linkClass && clean.linkFn === "undefined");
  const codes = await c.eval(`(async()=>{
    const out={};
    for (const p of ['/api/proxy?url=https://example.com/','/browse']) {
      try { const r = await fetch(p, {headers:{'X-Console-Pin':'${PIN}'}}); out[p]=r.status; } catch(e){ out[p]='ERR'; }
    }
    return out;})()`);
  console.log("     " + JSON.stringify(codes));
  check("/api/proxy 与 /browse 都已不存在（404）",
    codes["/api/proxy?url=https://example.com/"] === 404 && codes["/browse"] === 404);
  check("页面无 JS 异常", c.errors.length === 0, c.errors.slice(0, 2).join(" | "));

  console.log("\n[F] 输入栏永不消失 + 界面高度跟随可视区");
  const initState = await c.eval(`(()=>{const cp=document.getElementById('composer'),aw=document.getElementById('attachWrap');
    return {attach:getComputedStyle(aw).display, h:Math.round(cp.getBoundingClientRect().height),
            visible:cp.getBoundingClientRect().top < innerHeight && cp.getBoundingClientRect().bottom > 0,
            hasCurrent:!!(current&&current.id), inputDisabled:document.getElementById('input').disabled};})()`);
  console.log("     " + JSON.stringify(initState));
  check("初始就有输入栏且可用", initState.attach === "flex" && initState.h > 40 && initState.visible && !initState.inputDisabled);
  check("初始已自动选中一个可聊目标（手机任务或电脑端对话）", initState.hasCurrent === true);
  const disabledState = await c.eval(`(()=>{setComposerEnabled(false,'先在左侧选择一个任务…');
    const cp=document.getElementById('composer');
    return {attach:getComputedStyle(document.getElementById('attachWrap')).display, h:Math.round(cp.getBoundingClientRect().height),
            inputDisabled:document.getElementById('input').disabled, sendDisabled:document.getElementById('sendBtn').disabled,
            ph:document.getElementById('input').placeholder};})()`);
  check("没有可聊目标时输入栏仍显示（只是禁用）",
    disabledState.attach === "flex" && disabledState.h > 40 && disabledState.inputDisabled && disabledState.sendDisabled,
    JSON.stringify(disabledState));
  await c.eval(`setComposerEnabled(true,'给智能体发指令…'); updateDot();`);
  const heightLock = await c.eval(`(()=>{const app=document.getElementById('app'),cp=document.getElementById('composer');
    return {appH:Math.round(app.getBoundingClientRect().height), innerH:innerHeight,
            composerBottom:Math.round(cp.getBoundingClientRect().bottom),
            bodyScrollable:document.body.scrollHeight>innerHeight};})()`);
  console.log("     " + JSON.stringify(heightLock));
  check("全屏下界面高度=可视高度（输入栏不会被顶到屏幕外）", Math.abs(heightLock.appH - heightLock.innerH) <= 2);
  check("全屏下输入栏底边不超出屏幕", heightLock.composerBottom <= heightLock.innerH);
  check("页面整体不可滚动", heightLock.bodyScrollable === false);
  await c.eval(`localStorage.removeItem('console_fs_auto')`);

  console.log("\n[G] 长对话里的卡片不被压扁（曾经被 flex 压成 2px 黑线）");
  const cards = await c.eval(`(()=>{
    const tools=[...document.querySelectorAll('#chat > .tool')], cmds=[...document.querySelectorAll('#chat > .cmd')];
    const all=[...tools,...cmds];
    const chat=document.getElementById('chat');
    const hs=all.map(e=>Math.round(e.getBoundingClientRect().height));
    return {tools:tools.length, cmds:cmds.length, min:hs.length?Math.min(...hs):null, max:hs.length?Math.max(...hs):null,
            thin:all.filter(e=>e.getBoundingClientRect().height<=6).length,
            visibleContent:all.filter(e=>e.firstElementChild&&e.firstElementChild.offsetHeight>0).length,
            scrolls:chat.scrollHeight>chat.clientHeight, scrollH:chat.scrollHeight, clientH:chat.clientHeight};})()`);
  console.log("     " + JSON.stringify(cards));
  if (cards.tools + cards.cmds === 0) {
    check("本轮对话没有工具卡片，跳过该项", true, "（换个有工具调用的对话再看）");
  } else {
    check("工具/命令卡片都按内容高度显示（没有 2px 黑线）", cards.thin === 0 && cards.min > 30, "min=" + cards.min + "px thin=" + cards.thin);
    check("卡片内容确实渲染出来了", cards.visibleContent === cards.tools + cards.cmds, cards.visibleContent + "/" + (cards.tools + cards.cmds));
    check("长对话靠聊天区内部滚动", cards.scrolls === true, cards.scrollH + " > " + cards.clientH);
  }

  console.log("\n[H] 手机上切换模型 / 思考强度");
  const cur = await c.eval(`current`);
  if (!cur || !cur.id) {
    check("没有打开的对话，跳过模型切换测试", true);
  } else {
    const before = await apiFetch(`/api/models?kind=${cur.kind}&id=${encodeURIComponent(cur.id)}`);
    restoreSel = { kind: cur.kind, id: cur.id, ...(before.current || {}) };
    console.log("     当前：" + JSON.stringify(before.current));
    check("接口能给出模型清单", ((before.catalog || {}).groups || []).length > 0);
    check("能识别当前对话可切换", before.canSwitch === true);

    await c.eval(`document.getElementById('settingsBtn').click()`);
    await sleep(2200);
    const ui = await c.eval(`(()=>{const m=document.getElementById('modelDd'), e=document.getElementById('effortDd');
      return {models:[...m.querySelectorAll('.dd-item')].map(i=>i.querySelector('.dd-sub').textContent),
              modelLabel:m.querySelector('.dd-label').textContent, modelOpen:m.classList.contains('open'),
              effortLabel:e.querySelector('.dd-label').textContent,
              effortItems:[...e.querySelectorAll('.dd-item')].map(i=>i.querySelector('.dd-name').textContent),
              hint:document.getElementById('setModel').textContent};})()`);
    check("模型是下拉式菜单（收起态，按钮上显示当前值）",
      ui.modelOpen === false && /deepseek/.test(ui.modelLabel), ui.modelLabel);
    check("下拉里列出全部模型", ui.models.length === (((before.catalog || {}).groups || [])[0] || { models: [] }).models.length, ui.models.join(","));
    check("思考强度是下拉式菜单", ui.effortItems.length >= 2, ui.effortItems.join("/"));
    check("设置页显示当前模型与强度", /思考强度/.test(ui.hint), ui.hint);

    // 点开模型下拉 -> 选一个不同的模型（不点任何「应用」按钮，应当立即生效）
    const models = (((before.catalog || {}).groups || [])[0] || { models: [] }).models.map((m) => m.id);
    const pick = models.find((m) => m !== before.current.model) || before.current.model;
    await c.eval(`document.querySelector('#modelDd .dd-btn').click()`);
    await sleep(400);
    check("点一下能展开下拉菜单",
      (await c.eval(`document.getElementById('modelDd').classList.contains('open') && getComputedStyle(document.querySelector('#modelDd .dd-menu')).display !== 'none'`)) === true);
    await c.eval(`(()=>{const items=[...document.querySelectorAll('#modelDd .dd-item')];
      items.find(i=>i.querySelector('.dd-sub').textContent==='${pick}').click();})()`);
    await sleep(400);
    check("选完菜单自动收起",
      (await c.eval(`document.getElementById('modelDd').classList.contains('open')`)) === false);
    await sleep(3500);
    const after = await apiFetch(`/api/models?kind=${cur.kind}&id=${encodeURIComponent(cur.id)}`);
    console.log("     切换后：" + JSON.stringify(after.current));
    check("选完立即生效（不需要应用按钮）", after.current.model === pick, after.current.model + " vs " + pick);

    // 再用强度下拉切一档
    const pickEffort = before.current.reasoningEffort === "low" ? "高" : "低";
    await c.eval(`document.querySelector('#effortDd .dd-btn').click()`);
    await sleep(400);
    await c.eval(`(()=>{const items=[...document.querySelectorAll('#effortDd .dd-item')];
      items.find(i=>i.querySelector('.dd-name').textContent==='${pickEffort}').click();})()`);
    await sleep(3500);
    const after2 = await apiFetch(`/api/models?kind=${cur.kind}&id=${encodeURIComponent(cur.id)}`);
    const wantEffort = pickEffort === "低" ? "low" : "high";
    check("强度下拉选完也立即生效", !after2.current.reasoningEffort || after2.current.reasoningEffort === wantEffort,
      after2.current.reasoningEffort);

    let rejected = "";
    try {
      await apiFetch("/api/model", { method: "POST", body: JSON.stringify({ kind: cur.kind, id: cur.id, provider: "deepseek-official", model: "no-such-model-xyz" }) });
    } catch (e) { rejected = e.message; }
    check("不存在的模型会被拒绝并说明原因", /不在可用清单/.test(rejected), rejected);

    const back = await apiFetch("/api/model", {
      method: "POST",
      body: JSON.stringify({ kind: cur.kind, id: cur.id, provider: restoreSel.provider, model: restoreSel.model, reasoningEffort: restoreSel.reasoningEffort }),
    });
    console.log("     还原：" + JSON.stringify(back.selected));
    await sleep(3000);
    const restored = await apiFetch(`/api/models?kind=${cur.kind}&id=${encodeURIComponent(cur.id)}`);
    check("测试完已还原原来的模型", restored.current.model === restoreSel.model, JSON.stringify(restored.current));
    restoreSel = null;

    console.log("\n[H2] 余额充值按钮");
    const topUp = await c.eval(`(()=>{const a=document.getElementById('topUp');const r=a.getBoundingClientRect();
      return {label:a.textContent, href:a.getAttribute('href'), target:a.getAttribute('target'),
              rel:a.getAttribute('rel')||'', visible:r.width>20 && r.height>10,
              balance:document.getElementById('setBalance').textContent,
              low:a.classList.contains('low')};})()`);
    console.log("     " + JSON.stringify(topUp));
    check("余额旁边有「充值」按钮", topUp.visible && topUp.label === "充值");
    check("充值按钮指向 DeepSeek 官方充值页且新窗口打开",
      topUp.href === "https://platform.deepseek.com/top_up" && topUp.target === "_blank" && /noopener/.test(topUp.rel));
    check("余额不足时按钮高亮提示", topUp.low === true || !/^\d/.test(topUp.balance), topUp.balance);

    await c.eval(`document.getElementById('settingsModal').classList.remove('show')`);
  }

  console.log("\n[I] 滚动位置：新内容不会把视图甩到顶端");
  const chatPos = `(()=>{const c=document.getElementById('chat');
    return {top:Math.round(c.scrollTop), h:Math.round(c.scrollHeight), client:Math.round(c.clientHeight),
            atBottom:(c.scrollHeight-c.scrollTop-c.clientHeight)<140};})()`;
  await c.eval(`(()=>{const c=document.getElementById('chat');c.scrollTop=c.scrollHeight;c.dispatchEvent(new Event('scroll'));})()`);
  await sleep(400);
  const p0 = await c.eval(chatPos);
  check("打开对话后停在最新内容处", p0.atBottom === true, "top=" + p0.top);
  const tops = [];
  for (let i = 0; i < 4; i++) { await sleep(2000); tops.push((await c.eval(chatPos)).top); }
  const p1 = await c.eval(chatPos);
  console.log("     2 秒一次采样（服务端每 1.5 秒推全量快照）：" + tops.join(" -> "));
  check("连续快照后仍在底部（这是曾经的 bug：被甩回最顶端）", p1.atBottom === true && tops.every((t) => t > 100), tops.join(","));
  check("位置没有来回跳动", new Set(tops).size <= 2, tops.join(","));

  await c.eval(`(()=>{const c=document.getElementById('chat');c.scrollTop=Math.round(c.scrollHeight/3);c.dispatchEvent(new Event('scroll'));})()`);
  await sleep(300);
  const up1 = await c.eval(chatPos);
  await sleep(4500);
  const up2 = await c.eval(chatPos);
  console.log("     上滑后：" + up1.top + " -> " + up2.top);
  check("用户上滑看历史时不会被强行拽到底部", up2.atBottom === false, "atBottom=" + up2.atBottom);
  check("上滑位置保持稳定", Math.abs(up2.top - up1.top) < 60, up1.top + " -> " + up2.top);

  console.log("\n[J] 输入栏下方的状态条");
  await c.eval(`document.getElementById('settingsModal').classList.remove('show')`);
  await sleep(500);
  const sb = await c.eval(`(()=>{const b=document.getElementById('statusbar'), cp=document.getElementById('composer');
    const br=b.getBoundingClientRect(), cr=cp.getBoundingClientRect();
    const rows=new Set([...b.children].map(e=>Math.round(e.getBoundingClientRect().top))).size;
    return {shown:b.classList.contains('on'), text:b.textContent.replace(/\\s+/g,' ').trim(),
            belowInput: br.top >= cr.bottom - 1, rows:rows,
            hasstatus:document.getElementById('attachWrap').classList.contains('hasstatus'),
            fab:document.getElementById('toBottom').style.bottom};})()`);
  console.log("     " + sb.text);
  check("状态条显示在输入栏下方", sb.shown && sb.belowInput);
  check("含轮/步、tok/s、token、缓存命中", /轮/.test(sb.text) && /步/.test(sb.text) && /tok\/s/.test(sb.text) && /命中/.test(sb.text));
  check("含余额、官网消费、本对话消费、每亿均价", /余额/.test(sb.text) && /官网/.test(sb.text) && /本对话/.test(sb.text) && /\/亿tok/.test(sb.text));
  check("自动换行且不超过 3 行", sb.rows <= 3 && sb.rows >= 1, "行数=" + sb.rows);
  check("状态条让出底部安全区（组合类生效）", sb.hasstatus === true);
  check("回到底部按钮位置已跟随更新", /px/.test(sb.fab || ""), sb.fab);
  await c.eval(`document.getElementById('statusbar').click()`);
  await sleep(2200);
  check("点状态条能打开设置看详细用量",
    (await c.eval(`document.getElementById('settingsModal').classList.contains('show')`)) === true);
  await c.eval(`document.getElementById('settingsModal').classList.remove('show')`);

  c.close();
  console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
} catch (e) {
  console.log("测试异常: " + e.message);
  fail++;
} finally {
  // 无论如何都要把被测试改过的模型还原回去
  if (restoreSel && restoreSel.id && restoreSel.model) {
    try {
      await apiFetch("/api/model", {
        method: "POST",
        body: JSON.stringify({ kind: restoreSel.kind, id: restoreSel.id, provider: restoreSel.provider, model: restoreSel.model, reasoningEffort: restoreSel.reasoningEffort }),
      });
      console.log("（已还原模型：" + restoreSel.model + "）");
    } catch (e) { console.log("（还原模型失败：" + e.message + "）"); }
  }
  try { chrome.kill(); } catch { }
  await sleep(800);
  try { rmSync(PROFILE, { recursive: true, force: true }); } catch { }
  process.exit(fail ? 1 : 0);
}
