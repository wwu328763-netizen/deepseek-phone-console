/* 手机远程控制台 · 管理面板（界面层）
   只做渲染与桥调用；业务全在 Python（console_core），这里不碰文件系统。
   桥约定：所有方法返回 {ok: bool, msg?: str, ...}；长任务靠 poll() 轮询。 */
'use strict';

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.prototype.slice.call(document.querySelectorAll(s));
const api = () => (window.pywebview && window.pywebview.api) || null;

const S = { ready: false, busy: false, view: 'status', qrUrl: '', logs: [], phase: '', lastLoggedPhase: '', phaseSince: 0, cycleAt: 0, dropDone: true };

/* ---------------- 开屏动画 ---------------- */
const _splash = $('#splash');
let _splashGone = false;
function dismissSplash(delay) {
  if (_splashGone || !_splash) return;
  _splashGone = true;
  const wait = Math.max(0, delay || 0);
  setTimeout(() => {
    _splash.classList.add('done');
    setTimeout(() => { try { _splash.remove(); } catch (e) { /* ignore */ } }, 520);
  }, wait);
}
// 兜底：桥没就绪也不能一直挡着
setTimeout(() => dismissSplash(0), 3400);
/* ---------------- 工具 ---------------- */
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function toast(text, kind) {
  const el = document.createElement('div');
  el.className = 'toast ' + (kind || '');
  el.textContent = text;
  $('#toasts').appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .2s, transform .2s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(6px)';
    setTimeout(() => el.remove(), 220);
  }, 3000);
}
function tickClock() {
  const d = new Date(), p = (n) => String(n).padStart(2, '0');
  $('#clock').textContent = p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
}
setInterval(tickClock, 1000);
tickClock();

/* 横幅秒表 */
setInterval(() => {
  const el = $('#pbSec');
  if (!el) return;
  if (!S.phaseSince) { el.textContent = '0.0s'; return; }
  el.textContent = ((Date.now() - S.phaseSince) / 1000).toFixed(1) + 's';
}, 100);

/* ---------------- 视图切换 ---------------- */
window.UI = { esc: null, toast: null };   // 供 usage.js 复用（下面赋值）

function showView(name) {
  S.view = name;
  $$('.rail-btn[data-view]').forEach((b) => b.classList.toggle('active', b.dataset.view === name));
  ['status', 'usage', 'logs', 'about'].forEach((v) => {
    const el = $('#view' + v.charAt(0).toUpperCase() + v.slice(1));
    if (el) el.hidden = v !== name;
  });
  window.dispatchEvent(new CustomEvent('viewchange', { detail: { view: name } }));
}
$$('.rail-btn[data-view]').forEach((b) => { b.onclick = () => showView(b.dataset.view); });
$$('[data-goto]').forEach((b) => { b.onclick = () => showView(b.dataset.goto); });

/* ---------------- 渲染 ---------------- */
function setChip(el, text, kind) {
  el.className = 'chip ' + (kind || '');
  el.innerHTML = '<i></i>' + esc(text);
}

function render(st) {
  const srv = st.server || {}, tun = st.tunnel || {};
  const running = !!srv.running;
  const url = st.accessUrl || '';

  /* 顶栏 chips */
  setChip($('#pillServer'), running ? '服务 运行中' : '服务 已停止', running ? 'ok' : 'bad');
  setChip($('#pillTunnel'), tun.url ? '隧道 已连通' : (tun.connected ? '隧道 等待地址' : '隧道 未连接'),
    tun.url ? 'ok' : (tun.connected ? 'warn' : 'bad'));

  /* hero */
  const hs = $('#heroState');
  hs.textContent = running ? '运行中' : '已停止';
  hs.classList.toggle('on', running);
  $('#heroNote').textContent = running
    ? ('端口 ' + (srv.port || 8787) + (srv.pid ? ' · PID ' + srv.pid : '') + (st.dshTarget ? ' · ' + st.dshTarget : ''))
    : '端口 ' + (srv.port || 8787) + ' · 未运行';
  $('#heroUrl').textContent = url || '还没有可用地址';
  $('#heroUrl').title = url || '';

  /* 指标 */
  const sn = $('#stServer');
  sn.textContent = running ? '运行中' : '已停止';
  sn.classList.toggle('ok', running);
  $('#stServerSub').textContent = '端口 ' + (srv.port || 8787) + (srv.pid ? ' · PID ' + srv.pid : '');
  const stn = $('#stTunnel');
  stn.textContent = tun.url ? '已连接' : (tun.connected ? '等待地址' : '未连接');
  stn.classList.toggle('ok', !!tun.url);
  $('#stTunnelSub').textContent = tun.url ? 'cloudflared · 公网' : 'cloudflared';
  $('#stDsh').textContent = st.dshTarget || (running ? '识别中…' : '未运行');
  const lan = (st.lanIps || [])[0] || '—';
  $('#stLan').textContent = lan;
  $('#stLan').title = (st.lanIps || []).join('\n');

  /* hero 关键信息 */
  const hp = $("#heroPin"); if (hp) hp.textContent = st.pin || "—";
  const hl = $("#heroLan"); if (hl) hl.textContent = (st.lanIps || [])[0] || "—";
  const hd = $("#heroDsh"); if (hd) hd.textContent = st.dshTarget || "—";

  /* 页脚小字 */
  const psPin = $("#psPin"); if (psPin) psPin.textContent = st.pin || "—";
  const psDir = $("#psDir"); if (psDir) { psDir.textContent = st.dataDir || "—"; psDir.title = st.dataDir || ""; }

  /* 二维码同步放在 phase 计算之后（这里 phase 还没声明） */

  /* 启动 / 停止动画阶段 -------------------------------------------------
     starting：状态胶囊转圈 + 按钮 spinner + 二维码 shimmer
     stopping：环形回收 + 琥珀色
     running / stopped：切换瞬间闪一下 */
  const statusTxt = st.status || '';
  let phase = 'stopped';
  if (st.busy) {
    phase = statusTxt.indexOf('停止') >= 0 ? 'stopping'
      : statusTxt.indexOf('启动') >= 0 ? 'starting' : 'working';
  } else if (running) {
    phase = 'running';
  }
  const appEl = $('#app');
  if (appEl) appEl.dataset.phase = phase;

  /* 周期开始：每次进 starting 都重新播（砖墙→二维码），进 stopping 也重置 */
  if ((phase === 'starting' || phase === 'working') && S.phase !== phase && S.phase !== 'starting') {
    S.cycleAt = Date.now();
    S.dropDone = false;
  }
  if (phase === 'stopping') S.dropDone = false;

  /* 状态胶囊文案跟着阶段走（否则启动中还写着"已停止"） */
  const hsEl = $('#heroState');
  if (hsEl) {
    if (phase === 'starting' || phase === 'working') hsEl.textContent = '启动中';
    else if (phase === 'stopping') hsEl.textContent = '停止中';
  }

  const setBtn = (sel, loading, label) => {
    const b = $(sel);
    if (!b) return;
    b.classList.toggle('is-loading', !!loading);
    const lb = b.querySelector('.btn-label');
    if (lb && label) lb.textContent = label;
  };
  setBtn('#btnStart', phase === 'starting', phase === 'starting' ? '启动中…' : '启动');
  setBtn('#btnStop', phase === 'stopping', phase === 'stopping' ? '停止中…' : '停止');

  /* 状态落定的一瞬间闪一下 */
  if (S.phase && S.phase !== phase && (phase === 'running' || phase === 'stopped')) {
    const hero = document.querySelector('.hero');
    if (hero) {
      hero.classList.remove('flash-ok', 'flash-off');
      void hero.offsetWidth;
      hero.classList.add(phase === 'running' ? 'flash-ok' : 'flash-off');
      setTimeout(() => hero.classList.remove('flash-ok', 'flash-off'), 950);
    }
  }
  S.phase = phase;

  /* 顶部阶段横幅 + 二维码遮罩：启动/停止时给足视觉反馈 */
  const banner = $('#phaseBanner');
  const busyPhase = (phase === 'starting' || phase === 'stopping' || phase === 'working');
  if (banner) {
    /* 常驻：不做展开/收起，只切换 data-kind 与文案，避免布局跳动 */
    if (busyPhase) {
      S.busySince = Date.now();
      S.busyKind = (phase === 'stopping') ? 'stop' : 'start';
    }
    const holdBusy = !busyPhase && S.busySince && (Date.now() - S.busySince < 900);
    banner.dataset.kind = busyPhase ? S.busyKind : (holdBusy ? S.busyKind : 'idle');
    const pbText = $('#pbText');
    if (pbText) {
      if (busyPhase || holdBusy) {
        pbText.textContent = phase === 'stopping' ? '正在停止服务与隧道…'
          : phase === 'working' ? '处理中…' : '正在启动电脑端服务与隧道…';
      } else {
        const tunOk = st.tunnel && st.tunnel.connected;
        pbText.textContent = running
          ? ('服务运行中' + (tunOk ? ' · 云端隧道已连接' : ' · 等待隧道连接'))
          : '服务未运行 · 点「启动」开始';
      }
    }
    if (busyPhase) {
      if (!S.phaseSince) S.phaseSince = Date.now();
    } else {
      S.phaseSince = 0;
    }
  }
  /* 二维码区：由 syncQr 统一处理（phase 已就绪） */
  syncQr(phase, url, running);
  /* 宽度采样诊断：进入 starting 后 5 秒内，宽度有变化就记一行 */
  if ((phase === 'starting' || phase === 'working') && S.phase !== phase && !S.widthProbe) {
    S.widthProbe = true;
    const t0 = Date.now();
    let base = '';
    const me = () => {
      const d = document.documentElement;
      const w = (sel) => { const e = document.querySelector(sel); return e ? Math.round(e.getBoundingClientRect().width) : 0; };
      return [w('.hero'), w('.qr'), w('.stat'), w('.events'), d.clientWidth,
        d.scrollHeight, d.clientHeight].join(',');
    };
    const timer = setInterval(() => {
      if (Date.now() - t0 > 5000) { clearInterval(timer); S.widthProbe = false; return; }
      const cur = me();
      if (!base) { base = cur; return; }
      if (cur !== base) {
        base = cur;
        try { const br = api(); if (br && br.ui_log) br.ui_log('width ' + cur); } catch (e) { /* ignore */ }
      }
    }, 80);
  }


  /* 二维码/布局诊断：状态变化时记一行（含滚动高度，真机排查用） */
  try {
    const bx = $('#qrBox');
    const qrState = !bx ? 'none' : bx.querySelector('svg.qr-blocks') ? 'qr'
      : bx.querySelector('.brick-wall') ? 'bricks'
      : (bx.textContent || '').trim() === '启动后显示' ? 'placeholder' : 'other';
    const key = phase + '|' + (url ? 'url' : 'nourl') + '|' + (running ? 'run' : 'stop') + '|' + qrState;
    if (key !== S.qrKey) {
      S.qrKey = key;
      const br = api();
      if (br && br.ui_log) {
        br.ui_log('qr ' + key + ' sh=' + document.documentElement.scrollHeight +
          ' ch=' + document.documentElement.clientHeight +
          ' inner=' + window.innerWidth + 'x' + window.innerHeight);
      }
    }
  } catch (e) { /* ignore */ }

  /* 阶段变化写日志（诊断用） */
  if (S.phase !== S.lastLoggedPhase) {
    S.lastLoggedPhase = phase;
    try {
      const br = api();
      if (br && br.ui_log) br.ui_log('phase -> ' + phase + ' (' + (statusTxt || '-') + ')');
    } catch (e) { /* ignore */ }
  }

  /* 进度条：busy 时走不确定动画 */
  const prog = document.querySelector('.progress');
  if (prog) prog.classList.toggle('busy', !!st.busy);

  /* 最近事件 */
  const ev = $('#eventList');
  const logs = (st.logs || []).slice(-4).reverse();
  ev.innerHTML = logs.length ? logs.map((l) => (
    '<div class="event ' + (l.k === 'ok' ? 'ok' : l.k === 'err' ? 'err' : '') + '">' +
    '<time>' + esc(l.t) + '</time><span class="tag"></span>' +
    '<span class="msg">' + esc(l.m) + '</span></div>'
  )).join('') : '<div class="event empty">还没有事件</div>';

  /* 日志页 */
  renderLogs(st.logs || []);

  /* 状态栏 */
  const dot = $('#statusDot');
  dot.className = 'status-dot' + (st.busy ? ' busy' : (running ? ' ok' : ''));
  $('#statusText').textContent = st.status || '就绪';
  const pct = st.busy ? (st.total ? Math.round(st.done * 100 / st.total) : 35) : 0;
  $('#bar').style.width = pct + '%';

  /* 按钮态 */
  const dis = (sel, v) => { const e = $(sel); if (e) e.disabled = !!v; };
  dis('#btnStart', st.busy || running);
  dis('#btnStop', st.busy || !running);
  dis('#btnTunnel', st.busy || !!tun.url);
  dis('#btnRestart', st.busy);
  dis('#btnOpen', !url);
  dis('#btnCopy', !url);
  dis('#btnCopy2', !url);
  S.busy = !!st.busy;
}

function renderLogs(logs) {
  const box = $('#logs');
  if (!box) return;
  const last = logs.length ? logs[logs.length - 1].t + logs[logs.length - 1].m : '__';
  if (box.dataset.last === last) return;
  box.dataset.last = last;
  box.innerHTML = logs.length ? logs.map((l) => (
    '<div class="log-line ' + (l.k === 'ok' ? 'ok' : l.k === 'err' ? 'err' : '') + '">' +
    '<span class="t">' + esc(l.t) + '</span><span class="m">' + esc(l.m) + '</span></div>'
  )).join('') : '<div class="log-line"><span class="t">--:--:--</span><span class="m">还没有日志</span></div>';
  box.scrollTop = box.scrollHeight;
}

/* ---------------- 二维码区域：确定性同步 ----------------
   每次渲染根据 (phase, url, running) 推导"唯一正确显示"，不依赖缓存比较：
     stopping              → 二维码/砖墙都推倒
     未运行且不在启动中     → 必须回到占位
     启动中且没有地址       → 砖墙
     有地址                → 确保二维码存在（缺失就注入）
   注入用 qrBusy 防重入。 */

function clearQrArea() {
  const box = $('#qrBox');
  if (!box) return;
  box.className = 'qr-box empty';
  box.innerHTML = '<span>启动后显示</span>';
  box.dataset.url = '';
  box.dataset.toppling = '';
  S.qrUrl = '';
}

function showBricksNow() {
  const box = $('#qrBox');
  if (!box || box.querySelector('.brick-wall')) return;
  box.dataset.url = '';
  S.qrUrl = '';
  const COLS = 6, ROWS = 6;
  let cells = '';
  for (let i = 0; i < COLS * ROWS; i++) {
    const row = Math.floor(i / COLS);
    const col = i % COLS;
    const delay = (ROWS - 1 - row) * 42 + col * 12;
    cells += '<i style="--i:' + i + ';--d:' + delay + 'ms"></i>';
  }
  box.className = 'qr-box empty building';
  box.innerHTML = '<div class="brick-wall" aria-label="正在启动">' + cells + '</div>';
  animHold(760);   // 36 块砌完约 610ms，留点余量
  box.dataset.toppling = '';
}

async function injectQr(url) {
  const box = $('#qrBox');
  if (!box) return;
  qrBusy = true;
  try {
    const r = await api().qr_svg();
    if (!r || !r.ok || !r.svg) return;
    const cur = $('#qrBox');
    if (!cur) return;
    cur.className = 'qr-box fresh';
    cur.dataset.toppling = '';
    cur.innerHTML = qrBlocksSvg(r.svg);
    cur.dataset.url = url;
    S.qrUrl = url;
    S.dropDone = true;
    const cap = $('#qrUrl');
    if (cap) cap.textContent = url;
    animHold(1150);   // 37 行逐行落下约 1.05s
    setTimeout(() => { const b = $('#qrBox'); if (b) b.classList.remove('fresh'); }, 900);
  } catch (e) { /* 下一轮再试 */ } finally {
    qrBusy = false;
  }
}

function syncQr(phase, url, running) {
  const box = $('#qrBox');
  if (!box) return;
  const hasQr = !!box.querySelector('svg.qr-blocks');
  const hasBricks = !!box.querySelector('.brick-wall');
  const starting = (phase === 'starting' || phase === 'working');
  const stopping = (phase === 'stopping');

  /* 每次启动都完整播一遍：砖墙至少砌 900ms，然后再落二维码 */
  if (starting && !S.dropDone && Date.now() - S.cycleAt < 900) {
    if (hasQr && !box.dataset.toppling) { box.dataset.url = ''; S.qrUrl = ''; toppleQr(box, showBricksNow); return; }
    if (!hasBricks && !hasQr) showBricksNow();
    return;
  }

  if (stopping || (!running && !starting)) {
    // 正在落/正在砌：等它播完再推倒（"完全启动/完全停止后再切换"）
    if ((hasQr || hasBricks) && !box.dataset.toppling && animBusy()) return;
    if (hasQr) { box.dataset.url = ''; S.qrUrl = ''; toppleQr(box, clearQrArea); return; }
    if (hasBricks) { clearBricks(); return; }
    if (!box.querySelector('span')) clearQrArea();
    return;
  }

  if (starting && !url) {
    if (hasQr && !box.dataset.toppling && animBusy()) return;   // 让二维码入场动画播完
    if (hasQr) { box.dataset.url = ''; S.qrUrl = ''; toppleQr(box, showBricksNow); return; }
    showBricksNow();
    return;
  }

  if (url) {
    if (hasQr && box.dataset.url === url) return;
    if (qrBusy) return;
    injectQr(url);
    return;
  }

  if (!box.querySelector('span')) clearQrArea();
}

/* 砖块墙：启动时逐块砌起来（每块 --i 控制延迟，循环有呼吸波） */
const BRICK_COLS = 6;
const BRICK_ROWS = 6;

function clearBricks() {
  const box = $('#qrBox');
  if (!box) return;
  const wall = box.querySelector('.brick-wall');
  if (!wall) return;
  wall.classList.add('toppling');
  setTimeout(() => {
    // 期间二维码可能已经注入，别再用占位把二维码盖掉
    if (box.querySelector('.brick-wall') !== wall) return;
    box.className = 'qr-box empty';
    box.innerHTML = '<span>启动后显示</span>';
  }, 620);
}

function clearBrandArea() {
  const box = $('#qrBox');
  if (!box) return;
  if (!box.querySelector('.brick-wall')) {
    box.className = 'qr-box empty';
    box.innerHTML = '<span>启动后显示</span>';
  }
}

/* ---------------- 二维码（Python 出 SVG；前端拆成方块做积木动画） ----------------
   Python 给的是 SvgPathImage：每个模块一段 "M x,y H x+1 V y+1 H x z"。
   这里把 path 解析成模块坐标，自己重建成 <rect>，每块带 --din/--dout/--r/--dx/--r2，
   于是可以"逐块落下堆好"（blockIn）和"从左到右推倒"（blockOut）。 */
function parseQrModules(svgText) {
  const vb = svgText.match(/viewBox="0 0\s+([\d.]+)\s+([\d.]+)"/);
  const W = vb ? Number(vb[1]) : 0;
  const H = vb ? Number(vb[2]) : 0;
  const mods = [];
  const re = /M(\d+(?:\.\d+)?),(\d+(?:\.\d+)?)H(\d+(?:\.\d+)?)V(\d+(?:\.\d+)?)H(\d+(?:\.\d+)?)z/g;
  let m;
  while ((m = re.exec(svgText))) mods.push({ x: Number(m[1]), y: Number(m[2]) });
  return { W: W, H: H, mods: mods };
}

function qrBlocksSvg(svgText) {
  const parsed = parseQrModules(svgText);
  const mods = parsed.mods;
  if (!mods.length || mods.length > 1600) return svgText;

  /* 按行分组动画：800 多个 rect 各自动画会卡；分成 ~37 个 <g> 组，
     每行一个 transform 动画（GPU 合成），观感仍是"一行行砖块堆上去"。 */
  const rows = new Map();
  mods.forEach(function (m) {
    if (!rows.has(m.y)) rows.set(m.y, []);
    rows.get(m.y).push(m);
  });
  const ys = Array.from(rows.keys()).sort(function (a, b) { return a - b; });
  const maxY = ys[ys.length - 1];
  const minY = ys[0];

  const groups = ys.map(function (y) {
    // 底行先落，行间 18ms 错开
    const delay = Math.round((maxY - y) * 18);
    const cells = rows.get(y).map(function (m) {
      return '<rect x="' + m.x + '" y="' + m.y + '" width="1" height="1"/>';
    }).join('');
    return '<g class="qrrow" style="--rd:' + delay + 'ms">' + cells + '</g>';
  }).join('');

  return '<svg class="qr-blocks" viewBox="0 0 ' + parsed.W + ' ' + parsed.H +
    '" shape-rendering="crispEdges" role="img" aria-label="手机扫码连接二维码">' +
    '<rect class="qbg" x="0" y="0" width="' + parsed.W + '" height="' + parsed.H + '" fill="#fff"/>' +
    groups + '</svg>';
}

/* 推倒：给方块加 .toppling，等动画播完再换占位 */
function toppleQr(box, done) {
  const svg = box.querySelector('svg.qr-blocks');
  if (!svg) { done(); return; }
  if (box.dataset.toppling === '1') return;   // 已在推倒中，别重复排队（否则每轮 poll 都重置计时）
  box.dataset.toppling = '1';
  animHold(700);   // 推倒动画 620ms
  svg.classList.add('toppling');
  setTimeout(() => {
    box.dataset.toppling = '';
    done();
  }, 620);
}

/* ---------------- 二维码（Python 出 SVG，前端只注入） ---------------- */
var qrBusy = false;

/* 动画时间线：任何一次"开始播"的动画都会把 until 推后；
   动画没播完之前，syncQr / 横幅都保持当前画面，不被下一次轮询掐断。 */
const ANIM = { until: 0 };
function animHold(ms) { ANIM.until = Math.max(ANIM.until, Date.now() + ms); }
function animBusy() { return Date.now() < ANIM.until; }

/* ---------------- 轮询 ----------------
   setInterval(poll, 900) 驱动整个界面。这里必须把异常吃掉：
   一次渲染失败不能让后续轮询一起停掉（之前删代码时误删过这个函数，
   表现就是界面冻结在某个状态、"一直显示正在启动"）。 */
async function poll() {
  try {
    const st = await api().poll();
    if (st && st.ok) render(st);
  } catch (e) {
    /* 单次失败忽略，下一轮继续 */
  }
}

/* ---------------- 动作 ---------------- */
async function act(name, fn) {
  try {
    const r = await fn();
    if (r && r.ok === false) toast(r.msg || (name + '失败'), 'err');
    else toast(name + '已开始', 'ok');
    setTimeout(poll, 260);
  } catch (e) {
    toast(name + '失败：' + e, 'err');
  }
}

async function copyUrl() {
  try {
    const r = await api().copy_access_url();
    if (!r || !r.ok || !r.url) { toast('还没有可用地址', 'err'); return; }
    await navigator.clipboard.writeText(r.url);
    toast('地址已复制', 'ok');
  } catch (e) {
    toast('复制失败：' + e, 'err');
  }
}

function bind() {
  $('#btnStart').onclick = () => act('启动', () => api().start_all());
  $('#btnStop').onclick = () => act('停止', () => api().stop_all());
  $('#btnTunnel').onclick = () => act('启动隧道', () => api().start_tunnel_only());
  $('#btnRestart').onclick = () => act('重启隧道', () => api().restart_tunnel());
  $('#btnOpen').onclick = () => act('打开手机页', () => api().open_phone_page());
  $('#btnCopy').onclick = copyUrl;
  $('#btnCopy2').onclick = copyUrl;
  $('#btnDataDir').onclick = () => act('打开数据目录', () => api().open_data_dir());
  $('#btnOpenData').onclick = () => act('打开数据目录', () => api().open_data_dir());
  $('#btnOpenPage').onclick = () => act('打开手机页', () => api().open_phone_page());
  $('#btnSaveAddr').onclick = async () => {
    try {
      const r = await api().save_phone_address();
      toast(r && r.ok ? '已写入 phone-address.txt' : ((r && r.msg) || '保存失败'), r && r.ok ? 'ok' : 'err');
    } catch (e) { toast('保存失败：' + e, 'err'); }
  };
  const cl = $('#btnClearLogs');
  if (cl) cl.onclick = () => { const b = $('#logs'); b.innerHTML = ''; b.dataset.last = ''; };
}

/* ---------------- 启动 ---------------- */
window.UI.esc = esc;
window.UI.toast = toast;

window.addEventListener('pywebviewready', async () => {
  S.ready = true;
  bind();
  try {
    const st = await api().poll();
    if (st && st.ok) render(st);
    dismissSplash(760);
  } catch (e) { /* ignore */ dismissSplash(300); }
  setInterval(poll, 900);
  setTimeout(poll, 200);
  // 诊断：把真实 WebView2 视口写进 panel.log，方便对断点
  try {
    const br = api();
    if (br && br.ui_log) br.ui_log('viewport ' + window.innerWidth + 'x' + window.innerHeight +
      ' dpr=' + (window.devicePixelRatio || 1) + ' outer=' + window.outerWidth + 'x' + window.outerHeight);
  } catch (e) { /* ignore */ }
});

window.addEventListener('error', (e) => {
  try {
    const br = api();
    if (br && br.ui_log) br.ui_log('JS ERROR ' + (e.message || '') + ' @ ' + (e.filename || '') + ':' + (e.lineno || 0));
  } catch (_) { /* ignore */ }
});

setTimeout(() => {
  if (!S.ready) {
    const t = $('#statusText');
    if (t) t.textContent = '等待 pywebview 桥…（用浏览器直接打开时不会有数据）';
  }
}, 3000);
