/* 用量统计页（从 Tk 版 App._apply_official_display / _range_filter / _render_donut / _render_trend 迁移）
   数据全部来自 Python 桥 api().usage()，本文件只做渲染（SVG 图表）与交互。 */
'use strict';

const uq = (s) => document.querySelector(s);
const U = { rng: '全部', from: '', to: '', data: null, loading: false, loaded: false, tokTimer: null };

/* ---------------- 格式化 ---------------- */
function uFmtCompact(n) {
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(n / 1e9 >= 100 ? 0 : 2).replace(/\.?0+$/, '') + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(n / 1e6 >= 100 ? 0 : 2).replace(/\.?0+$/, '') + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(n / 1e3 >= 100 ? 0 : 1).replace(/\.?0+$/, '') + 'K';
  return String(n);
}
function uFmtInt(n) { return (Number(n) || 0).toLocaleString('zh-CN'); }
function uFmtMoney(n) { return '¥' + (Number(n) || 0).toFixed(2); }
function uToast(text, kind) {
  if (window.UI && window.UI.toast) window.UI.toast(text, kind);
}

/* ---------------- 读取 ---------------- */
async function loadUsage(force) {
  if (U.loading) return;
  if (U.loaded && !force) return;
  U.loading = true;
  try {
    const d = await api().usage(U.rng, U.from, U.to);
    if (d && d.ok) { U.data = d; renderUsage(d); U.loaded = true; }
    else if (d && d.msg) uToast('用量读取失败：' + d.msg, 'err');
  } catch (e) {
    uToast('用量读取失败：' + e, 'err');
  } finally {
    U.loading = false;
  }
}

/* ---------------- 渲染 ---------------- */
function renderUsage(d) {
  const t = d.totals || {};

  /* 区间分段器 */
  const seg = uq('#rangeSeg');
  if (seg && seg.dataset.built !== '1') {
    seg.innerHTML = (d.ranges || []).map((r) =>
      '<button data-rng="' + r + '">' + r + '</button>').join('');
    seg.dataset.built = '1';
    seg.querySelectorAll('button').forEach((b) => {
      b.onclick = () => {
        U.rng = b.dataset.rng;
        const cr = uq('#customRange');
        if (cr) cr.hidden = (U.rng !== '自定义');
        loadUsage(true);
      };
    });
  }
  if (seg) {
    seg.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.rng === U.rng));
  }
  const cr = uq('#customRange');
  if (cr) cr.hidden = (U.rng !== '自定义');

  /* 指标 */
  const rate = Number(t.rate || 0);
  uq('#uRate').textContent = rate.toFixed(2) + '%';
  uq('#uRate').classList.toggle('ok', rate >= 90);
  uq('#uHit').textContent = uFmtCompact(t.hit);
  uq('#uMiss').textContent = uFmtCompact(t.miss);
  uq('#uOut').textContent = uFmtCompact(t.output);
  /* 消耗金额：每个板块都显示 */
  const costRange = Number(t.costRange || 0);
  const costAvg = Number(t.costAvg || 0);
  const costAll = Number(t.costAll || 0);
  if (uq('#uCostRange')) uq('#uCostRange').textContent = uFmtMoney(costRange);
  if (uq('#uCostAvg')) {
    uq('#uCostAvg').textContent = '日均 ' + uFmtMoney(costAvg) + ' · 共 ' + uFmtMoney(costAll);
  }

  /* 环形图 */
  uq('#donut').innerHTML = donutHTML(t);
  const total = (t.hit || 0) + (t.miss || 0) + (t.output || 0);
  const items = [
    ['命中缓存', t.hit, 'var(--accent)'],
    ['未命中', t.miss, 'var(--amber)'],
    ['输出', t.output, 'var(--cyan)'],
  ];
  uq('#donutLegend').innerHTML = items.map(([label, v, color]) =>
    '<span><i style="background:' + color + '"></i>' + label +
    ' <b class="mono">' + (total ? (v / total * 100).toFixed(1) : '0.0') + '%</b></span>').join('');

  /* 趋势图（可拖动 + 悬停详情） */
  const series = d.series || [];
  if (uq('#uDonutCost')) uq('#uDonutCost').textContent = '区间 ' + uFmtMoney(costRange);
  if (uq('#uTrendCost')) uq('#uTrendCost').textContent = '区间 ' + uFmtMoney(costRange);
  if (uq('#uDetailCost')) {
    const c7 = series.slice(-7).reduce((a, r) => a + (Number(r.cost) || 0), 0);
    uq('#uDetailCost').textContent = '近 7 天 ' + uFmtMoney(c7);
  }
  renderTrend(series);

  /* 元信息 */
  const src = d.source === 'official'
    ? ('官网用量' + (d.range && d.range !== '全部' ? ' · ' + d.range : ''))
    : '无数据';
  uq('#uSource').textContent = src;
  uq('#uCoverage').textContent = d.coverage
    ? (d.coverage.days + ' 天（' + (d.coverage.first || '—') + ' ~ ' + (d.coverage.last || '—') + '）')
    : '—';
  uq('#uReq').textContent = uFmtInt(t.requests);
  uq('#uCost').textContent = '¥' + (Number(d.cost || 0)).toFixed(2);
  const ts = d.tokenState || {};
  uq('#uToken').textContent = ts.pending ? '验证中…' : (ts.has ? '已设置（…' + ts.tail + '）' : '未设置');

  /* 最近 7 天明细 */
  const tbody = uq('#uTable') ? uq('#uTable').querySelector('tbody') : null;
  if (tbody) {
    const rows = series.slice(-7).reverse();
    uq('#uDetailRange').textContent = rows.length ? (rows[rows.length - 1].d + ' ~ ' + rows[0].d) : '—';
    tbody.innerHTML = rows.length ? rows.map((r) => {
      const sum = (r.hit || 0) + (r.miss || 0) + (r.output || 0);
      const money = (r.cost == null) ? '—' : uFmtMoney(r.cost);
      return '<tr><td>' + r.d + '</td><td>' + uFmtCompact(r.hit) + '</td><td>' +
        uFmtCompact(r.miss) + '</td><td>' + uFmtCompact(r.output) + '</td><td>' +
        uFmtInt(r.requests) + '</td><td>' + uFmtCompact(sum) + '</td><td>' + money + '</td></tr>';
    }).join('') : '<tr><td colspan="7" style="text-align:center;color:var(--muted)">没有数据</td></tr>';
  }

  /* 提示 */
  const hint = uq('#uHint');
  const cands = d.candidates || [];
  if (!d.hasOfficial) {
    hint.textContent = '还没有用量数据：把官网「用量」页导出的 amount-*.csv / zip 用「导入用量文件」导入，或设置 Token 后点「拉取官网」。';
  } else if (cands.length) {
    hint.textContent = '下载目录里发现 ' + cands.length + ' 个官网用量文件：' +
      cands.map((c) => c.name + (c.imported ? '（已导入）' : '')).join('、');
  } else {
    hint.textContent = '数据来源：' + src + '；命中率 = 命中 ÷（命中 + 未命中）；消耗金额取自官网 cost 导出（按 UTC 天，覆盖最近两个月）。';
  }
  if (d.futureDropped) {
    hint.textContent += '（已忽略 ' + d.futureDropped + ' 天未来日期，官网数据可能把账期尾日算进去了）';
  }
}

/* ---------------- 图表：环形 ----------------
   环 + 文字分开渲染：文字用 HTML（ClearType 次像素渲染，小字号不发虚），
   SVG 里只画环和弧 —— 之前 9px 中文放在 SVG 里在 150% DPI 下糊成一片。 */
function donutSVG(t) {
  const hit = Number(t.hit) || 0, miss = Number(t.miss) || 0, out = Number(t.output) || 0;
  const total = hit + miss + out || 1;
  const R = 54, C = 2 * Math.PI * R;
  const segs = [
    [hit, 'var(--accent)', '命中缓存'],
    [miss, 'var(--amber)', '未命中'],
    [out, 'var(--cyan)', '输出'],
  ];
  let off = 0, arcs = '';
  segs.forEach(([v, color, label]) => {
    if (!v) return;
    const len = C * (v / total);
    arcs += '<circle cx="70" cy="70" r="' + R + '" fill="none" stroke="' + color +
      '" stroke-width="15" stroke-dasharray="' + len.toFixed(2) + ' ' + (C - len).toFixed(2) +
      '" stroke-dashoffset="' + (-off).toFixed(2) + '" transform="rotate(-90 70 70)">' +
      '<title>' + label + ' ' + (v / total * 100).toFixed(1) + '%（' + uFmtCompact(v) + '）</title></circle>';
    off += len;
  });
  return '<svg viewBox="0 0 140 140" role="img" aria-label="用量构成">' +
    '<circle cx="70" cy="70" r="' + R + '" fill="none" stroke="var(--surface-3)" stroke-width="15"/>' +
    arcs + '</svg>';
}

function donutHTML(t) {
  const total = (t.hit || 0) + (t.miss || 0) + (t.output || 0);
  const rate = Number(t.rate || 0);
  return '<div class="donut-figure">' + donutSVG(t) +
    '<div class="donut-center"><b>' + rate.toFixed(1) + '%</b><em>命中率</em></div>' +
    '</div>';
}
/* ---------------- 图表：每日趋势（面积 + 折线 + HTML 文字层） ----------------
   SVG 只负责画图形（网格/面积/折线/光标）；刻度、日期、提示全部是 HTML 文本：
   SVG 文字会随 viewBox 缩放，在 150% DPI 下小字号会被缩放/hinting 弄糊（用户反馈"发光"），
   HTML 文本走系统 ClearType，字号就是最终像素，清晰可控。
   拖动平移 / 滚轮 / 悬停浮层逻辑不变。 */
var TREND = {
  series: [], win: 0, end: 0, dragging: false,
  dragX: 0, dragEnd: 0, W: 640, H: 200,
  pad: { l: 12, r: 12, t: 18, b: 24 },
};

function trendSum(s) { return (s.hit || 0) + (s.miss || 0) + (s.output || 0); }

function trendGeometry() {
  var n = TREND.series.length;
  var paintWin = Math.min(n, 30);
  if (!TREND.win) TREND.win = paintWin;
  if (!TREND.end) TREND.end = n - 1;
  TREND.win = Math.max(2, Math.min(TREND.win, n));
  if (n <= paintWin) { TREND.win = n; TREND.end = n - 1; }
  TREND.end = Math.min(Math.max(TREND.end, TREND.win - 1), n - 1);
  var i0 = Math.max(0, TREND.end - TREND.win + 1);
  var view = TREND.series.slice(i0, TREND.end + 1);
  var W = TREND.W, H = TREND.H, pad = TREND.pad;
  var m = view.length;
  var vals = view.map(trendSum);
  var max = Math.max.apply(null, vals.concat([1]));
  var x = function (k) { return pad.l + (W - pad.l - pad.r) * (m === 1 ? 0.5 : k / (m - 1)); };
  var y = function (v) { return pad.t + (H - pad.t - pad.b) * (1 - v / max); };
  return { view: view, vals: vals, max: max, m: m, x: x, y: y, W: W, H: H, pad: pad };
}

function renderTrend(series) {
  var box = uq('#trend');
  if (!box) return;
  TREND.series = series || [];
  var range = uq('#trendRange');
  if (!TREND.series.length) {
    box.innerHTML = '<div class="trend-empty">还没有每日数据</div>';
    if (range) range.textContent = '没有数据';
    return;
  }
  var g = trendGeometry();
  var view = g.view, m = g.m, x = g.x, y = g.y, W = g.W, H = g.H, pad = g.pad;
  var line = g.vals.map(function (v, k) {
    return (k ? 'L' : 'M') + x(k).toFixed(1) + ' ' + y(v).toFixed(1);
  }).join(' ');
  var base = H - pad.b;
  var area = 'M' + x(0).toFixed(1) + ' ' + base.toFixed(1) + ' ' +
    g.vals.map(function (v, k) { return 'L' + x(k).toFixed(1) + ' ' + y(v).toFixed(1); }).join(' ') +
    ' L' + x(m - 1).toFixed(1) + ' ' + base.toFixed(1) + ' Z';

  /* SVG：只画网格线 / 面积 / 折线 / 悬停光标 */
  var grid = '';
  var yTicks = [];
  for (var gi = 0; gi < 3; gi++) {
    var yy = pad.t + (H - pad.t - pad.b) * (gi / 3);
    grid += '<line x1="0" y1="' + yy.toFixed(1) + '" x2="' + W + '" y2="' + yy.toFixed(1) +
      '" stroke="var(--line)" stroke-width="1" vector-effect="non-scaling-stroke"/>';
    yTicks.push({ top: yy / H * 100, text: uFmtCompact(Math.round(g.max * (1 - gi / 3))) });
  }
  grid += '<line x1="0" y1="' + base.toFixed(1) + '" x2="' + W + '" y2="' + base.toFixed(1) +
    '" stroke="var(--line-strong)" stroke-width="1" vector-effect="non-scaling-stroke"/>';

  var svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img" aria-label="每日用量趋势">' +
    '<defs><linearGradient id="uArea" x1="0" y1="0" x2="0" y2="1">' +
    '<stop offset="0%" stop-color="var(--accent)" stop-opacity=".26"/>' +
    '<stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs>' +
    grid +
    '<path d="' + area + '" fill="url(#uArea)"/>' +
    '<path d="' + line + '" fill="none" stroke="var(--accent)" stroke-width="1.7" ' +
    'vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"/>' +
    '<g class="tcursor" opacity="0">' +
    '<line class="tline" x1="0" y1="' + pad.t + '" x2="0" y2="' + base +
    '" stroke="var(--line-strong)" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/>' +
    '<circle class="tdot" cx="0" cy="' + pad.t + '" r="3.4" fill="var(--accent)"/>' +
    '<circle class="tdot-halo" cx="0" cy="' + pad.t + '" r="7" fill="var(--accent)" opacity=".16"/>' +
    '</g></svg>';

  /* HTML 文字层：y 刻度（左侧）+ x 日期（底部） */
  var htmlY = '<div class="t-y">' + yTicks.map(function (t) {
    return '<span style="top:' + t.top.toFixed(2) + '%">' + t.text + '</span>';
  }).join('') + '</div>';
  var xLabels = [0, Math.floor((m - 1) / 2), m - 1];
  var htmlX = '<div class="t-x">' + xLabels.map(function (k, idx) {
    var cls = idx === 0 ? 'start' : (idx === 2 ? 'end' : 'mid');
    return '<span class="' + cls + '" style="left:' + (x(k) / W * 100).toFixed(2) + '%">' +
      view[k].d + '</span>';
  }).join('') + '</div>';

  box.innerHTML = svg + htmlY + htmlX +
    '<div class="trend-tip" hidden></div>' +
    '<div class="trend-hint">' +
    'Ctrl+滚轮 缩放 · Alt+滚轮 平移 · 拖动/滚轮 平移 · 悬停看详情</div>';

  if (range) {
    range.textContent = view[0].d + ' ~ ' + view[m - 1].d + ' · ' +
      m + ' / ' + TREND.series.length + ' 天';
  }
  if (!box.dataset.bound) { bindTrend(box); box.dataset.bound = '1'; }
}

/* 鼠标 → viewBox 坐标（preserveAspectRatio=none：x/y 各自按比例映射） */
function trendPoint(box, clientX, clientY) {
  var svg = box.querySelector('svg');
  if (!svg) return null;
  var r = svg.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  return {
    x: (clientX - r.left) / r.width * TREND.W,
    y: (clientY - r.top) / r.height * TREND.H,
    rect: r,
  };
}

function trendIndexAt(box, vx) {
  var g = trendGeometry();
  var best = 0, bd = 1e9;
  for (var k = 0; k < g.m; k++) {
    var d = Math.abs(g.x(k) - vx);
    if (d < bd) { bd = d; best = k; }
  }
  return best;
}

function bindTrend(box) {
  var tip = function () { return box.querySelector('.trend-tip'); };
  var cursor = function () { return box.querySelector('.tcursor'); };
  var tline = function () { return box.querySelector('.tline'); };
  var td = function () { return box.querySelector('.tdot'); };
  var th = function () { return box.querySelector('.tdot-halo'); };

  function hide() {
    var t = tip(); if (t) t.hidden = true;
    var c = cursor(); if (c) c.setAttribute('opacity', '0');
  }

  function show(ev) {
    var p = trendPoint(box, ev.clientX, ev.clientY);
    if (!p) return;
    var g = trendGeometry();
    var k = trendIndexAt(box, p.x);
    var s = g.view[k];
    var px = g.x(k), py = g.y(trendSum(s));
    var l = tline(); if (l) { l.setAttribute('x1', px); l.setAttribute('x2', px); }
    var d = td(); if (d) { d.setAttribute('cx', px); d.setAttribute('cy', py); }
    var h = th(); if (h) { h.setAttribute('cx', px); h.setAttribute('cy', py); }
    var c = cursor(); if (c) c.setAttribute('opacity', '1');
    var t = tip();
    if (!t) return;
    t.hidden = false;
    t.innerHTML =
      '<div class="tt-d">' + s.d + '</div>' +
      '<div class="tt-row"><span>合计</span><b class="mono">' + uFmtCompact(trendSum(s)) + '</b></div>' +
      '<div class="tt-row"><span>命中缓存</span><b class="mono">' + uFmtCompact(s.hit) + '</b></div>' +
      '<div class="tt-row"><span>未命中</span><b class="mono">' + uFmtCompact(s.miss) + '</b></div>' +
      '<div class="tt-row"><span>输出</span><b class="mono">' + uFmtCompact(s.output) + '</b></div>' +
      '<div class="tt-row"><span>请求</span><b class="mono">' + uFmtInt(s.requests) + '</b></div>' +
      '<div class="tt-row"><span>消耗</span><b class="mono">' +
      ((s.cost == null) ? '—' : uFmtMoney(s.cost)) + '</b></div>';
    var br = box.getBoundingClientRect();
    var bw = t.offsetWidth || 148, bh = t.offsetHeight || 126;
    var left = ev.clientX - br.left + 16;
    var top = ev.clientY - br.top - bh - 12;
    if (left + bw > br.width - 8) left = ev.clientX - br.left - bw - 16;
    if (top < 6) top = ev.clientY - br.top + 16;
    t.style.left = Math.max(6, Math.min(left, br.width - bw - 8)) + 'px';
    t.style.top = Math.max(6, Math.min(top, br.height - bh - 6)) + 'px';
  }

  function stepPx() {
    var r = box.getBoundingClientRect();
    var m = Math.min(TREND.series.length, 30);
    return m > 1 ? r.width / (m - 1) : 12;
  }

  box.addEventListener('pointermove', function (ev) {
    if (TREND.dragging) {
      var shift = Math.round(-(ev.clientX - TREND.dragX) / Math.max(stepPx(), 1));
      var n = TREND.series.length;
      var end = Math.min(n - 1, Math.max(TREND.win - 1, TREND.dragEnd + shift));
      if (end !== TREND.end) { TREND.end = end; renderTrend(TREND.series); }
      return;
    }
    show(ev);
  });

  box.addEventListener('pointerdown', function (ev) {
    if (TREND.series.length <= TREND.win) return;
    TREND.dragging = true;
    TREND.dragX = ev.clientX;
    TREND.dragEnd = TREND.end;
    box.classList.add('dragging');
    try { box.setPointerCapture(ev.pointerId); } catch (e) { /* ignore */ }
    hide();
    ev.preventDefault();
  });

  function endDrag() { TREND.dragging = false; box.classList.remove('dragging'); }
  box.addEventListener('pointerup', endDrag);
  box.addEventListener('pointercancel', endDrag);
  box.addEventListener('pointerleave', function () { if (!TREND.dragging) hide(); });

  /* 滚轮：
     - Ctrl + 滚轮 = 缩放显示区间（天数）
     - Alt  + 滚轮 = 左右平移区间
     - 普通滚轮   = 快速平移（保留旧手感） */
  box.addEventListener('wheel', function (ev) {
    var n = TREND.series.length;
    if (!n) return;
    if (ev.ctrlKey) {
      var factor = ev.deltaY > 0 ? 1.25 : 0.8;
      TREND.win = Math.round((TREND.win || n) * factor);
      TREND.win = Math.max(2, Math.min(n, TREND.win));
    } else {
      var step = ev.altKey ? Math.max(1, Math.round((TREND.win || n) * 0.15))
                           : Math.max(1, Math.round(n * 0.03));
      var dir = ev.deltaY > 0 ? 1 : -1;
      TREND.end = Math.min(n - 1, Math.max((TREND.win || 2) - 1, TREND.end + dir * step));
    }
    renderTrend(TREND.series);
    hide();
    ev.preventDefault();
  }, { passive: false });
}

/* ---------------- Token 弹窗 ---------------- */
function tokMsg(text, kind) {
  const el = uq('#tokState');
  el.className = 'tok-state ' + (kind || '');
  el.textContent = text || '';
}
function openTokenModal() {
  uq('#tokenModal').hidden = false;
  tokMsg('');
  const st = (U.data && U.data.tokenState) || {};
  uq('#tokState').textContent = st.has ? ('当前 Token：…' + st.tail + (st.pending ? '（验证中）' : '')) : '还没有设置 Token';
  uq('#tokenInput').value = '';
  uq('#tokenInput').focus();
}
async function waitTokenResult(deadlineMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < (deadlineMs || 30000)) {
    await new Promise((r) => setTimeout(r, 800));
    try {
      const s = await api().usage_token_state();
      if (!s || !s.ok) continue;
      if (s.state === 'ok') {
        tokMsg('已保存（验证通过）', 'ok');
        uToast('官网 Token 已保存', 'ok');
        loadUsage(true);
        setTimeout(() => { uq('#tokenModal').hidden = true; }, 900);
        return;
      }
      if (s.state === 'err') {
        tokMsg('验证失败：' + (s.msg || '未知原因'), 'err');
        return;
      }
    } catch (e) { /* 继续等 */ }
  }
  tokMsg('验证超时（网络不通？），请稍后重试', 'err');
}

function bindUsage() {
  uq('#btnTopup').onclick = () => api().open_topup();
  uq('#btnUsageImport').onclick = async () => {
    try {
      const r = await api().usage_import();
      if (!r || r.ok === false) { uToast((r && r.msg) || '导入失败', 'err'); return; }
      if (r.canceled) return;
      uToast('已导入 ' + (r.name || '') + (r.span ? ' · ' + r.span : ''), 'ok');
      U.rng = '全部';
      loadUsage(true);
    } catch (e) { uToast('导入失败：' + e, 'err'); }
  };
  uq('#btnUsagePull').onclick = async () => {
    try {
      const r = await api().usage_pull();
      if (r && r.ok === false) { uToast(r.msg || '拉取失败', 'err'); return; }
      uToast('已开始拉取官网用量…', 'ok');
      setTimeout(() => loadUsage(true), 2600);
      setTimeout(() => loadUsage(true), 9000);
    } catch (e) { uToast('拉取失败：' + e, 'err'); }
  };
  uq('#btnToken').onclick = openTokenModal;
  uq('#btnTokClose').onclick = () => { uq('#tokenModal').hidden = true; };
  uq('#btnTokOpen').onclick = () => api().open_topup();
  uq('#btnTokPaste').onclick = async () => {
    try {
      const t = (await navigator.clipboard.readText() || '').trim();
      if (t.length < 20) { tokMsg('剪贴板里没有可用 Token（太短或为空）', 'err'); return; }
      uq('#tokenInput').value = t;
      tokMsg('已从剪贴板填入，点「验证并保存」');
    } catch (e) {
      tokMsg('读取剪贴板被拒绝，请手动粘贴', 'err');
    }
  };
  uq('#btnTokSave').onclick = async () => {
    const t = (uq('#tokenInput').value || '').trim();
    if (t.length < 20) { tokMsg('Token 太短，请确认复制的是 userToken', 'err'); return; }
    tokMsg('验证中…');
    try {
      const r = await api().usage_set_token(t);
      if (r && r.ok === false) { tokMsg(r.msg || '提交失败', 'err'); return; }
      waitTokenResult(30000);
    } catch (e) { tokMsg('提交失败：' + e, 'err'); }
  };
  uq('#btnTokClear').onclick = async () => {
    try {
      await api().usage_clear_token();
      tokMsg('已清除 Token');
      uToast('已清除官网 Token', 'ok');
      loadUsage(true);
    } catch (e) { tokMsg('清除失败：' + e, 'err'); }
  };
  uq('#btnApplyRange').onclick = () => {
    const f = uq('#dFrom').value, t = uq('#dTo').value;
    if (!f || !t || f > t) { uToast('请选择正确的起止日期', 'err'); return; }
    U.from = f; U.to = t;
    loadUsage(true);
  };
}

/* ---------------- 触发 ---------------- */
window.addEventListener('viewchange', (e) => {
  if (e.detail && e.detail.view === 'usage') loadUsage(false);
});
window.addEventListener('pywebviewready', () => {
  bindUsage();
  const today = new Date();
  const iso = (d) => d.toISOString().slice(0, 10);
  const ago = new Date(today.getTime() - 29 * 86400000);
  if (uq('#dFrom')) uq('#dFrom').value = iso(ago);
  if (uq('#dTo')) uq('#dTo').value = iso(today);
});
