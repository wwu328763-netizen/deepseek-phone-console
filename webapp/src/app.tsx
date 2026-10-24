/* 手机远程控制台 · 新界面（TypeScript + Preact）
   设计参考 Codex 移动端：单色、扁平、终端气质的排版；无气泡；等宽元信息。 */
import { h, Fragment, JSX } from 'preact';
import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import {
  ApiError, api, answerQuestion, getBalance, getInfo, getModels, uploadWithProgress, getPin, getUsage, listFiles,
  makeDir, setModel, setPin, stream, blobUrl, cachedBlobUrl, downloadRaw, getBg, saveBg,
  getArchived, setArchived, refreshUsage,
  type Item, type ModelInfo, type ModelsPayload, type Snap,
} from './api';
import {
  applyBg, applyTheme, copyText, readBg, relativeTime, set, state, toast, useStore, writeBg,
  type BgState, type Theme,
} from './store';

/* ────────────────────────── 图标 ────────────────────────── */
const ICON: Record<string, JSX.Element> = {
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  plus: <path d="M12 5v14M5 12h14" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  send: <path d="M5 12l14-7-5 7 5 7z" />,
  stop: <rect x="7" y="7" width="10" height="10" rx="2" />,
  bolt: <path d="M13 2 4.5 13.5H11l-1 8.5 8.5-11.5H12l1-8.5z" />,
  up: <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" />,
  archive: <path d="M3 7h18v4H3zM5 11v9h14v-9M10 15h4" />,
  list: <path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01" />,
  download: <path d="M12 3v12M7 10l5 5 5-5M4 21h16" />,
  target: <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="2.5" /></>,
  lock: <><rect x="4.5" y="10.5" width="15" height="10" rx="2" /><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5" /></>,
  clip: <path d="M9 12.5V7a3 3 0 0 1 6 0v8a4.5 4.5 0 0 1-9 0V8" />,
  gear: <><circle cx="12" cy="12" r="3" /><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4" /></>,
  chevron: <path d="M9 6l6 6-6 6" />,
  code: <path d="M8 6l-5 6 5 6M16 6l5 6-5 6" />,
  back: <path d="M15 5l-7 7 7 7" />,
  dot: <circle cx="12" cy="12" r="4" />,
};

function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none"
      stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      {ICON[name] || null}
    </svg>
  );
}

/* ────────────────────────── markdown-lite ────────────────────────── */
function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] as string));
}
function inline(s: string): string {
  return esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function renderRich(text: string): string {
  const lines = String(text || '').split('\n');
  const out: string[] = [];
  let code: string[] | null = null;
  let codeLang = '';
  let list: string[] = [];
  const flushList = () => {
    if (list.length) { out.push('<ul>' + list.map((li) => '<li>' + inline(li) + '</li>').join('') + '</ul>'); list = []; }
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].replace(/\s+$/, '');
    if (code) {
      if (/^```/.test(line.trim())) {
        out.push('<pre><code>' + esc(code.join('\n')) + '</code></pre>');
        code = null; codeLang = '';
      } else code.push(lines[i]);
      continue;
    }
    const fence = line.trim().match(/^```(\w*)/);
    if (fence) { flushList(); code = []; codeLang = fence[1] || ''; continue; }
    if (!line.trim()) { flushList(); out.push(''); continue; }
    const hd = line.match(/^(#{1,4})\s+(.*)$/);
    if (hd) { flushList(); const lv = Math.min(hd[1].length + 2, 5); out.push(`<h${lv}>${inline(hd[2])}</h${lv}>`); continue; }
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (li) { list.push(li[1]); continue; }
    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ol) { list.push(ol[1]); continue; }
    // 表格：表头 | 分隔行(---) | 若干数据行
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$/.test(lines[i + 1] || '')) {
      flushList();
      const parseRow = (s: string) => s.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
      const head = parseRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(parseRow(lines[i])); i++; }
      i--; // 外层 for 会再 ++
      out.push('<div class="table-wrap"><table><thead><tr>' + head.map((c) => '<th>' + inline(c) + '</th>').join('') +
        '</tr></thead><tbody>' + rows.map((r) => '<tr>' + head.map((_, ci) => '<td>' + inline(r[ci] || '') + '</td>').join('') + '</tr>').join('') +
        '</tbody></table></div>');
      continue;
    }
    const quote = line.match(/^>\s?(.*)$/);
    if (quote) { flushList(); out.push('<blockquote>' + inline(quote[1]) + '</blockquote>'); continue; }
    flushList();
    out.push('<p>' + inline(line) + '</p>');
  }
  if (code) out.push('<pre><code>' + esc(code.join('\n')) + '</code></pre>');
  flushList();
  return out.join('');
}
const Rich = ({ text }: { text: string }) => (
  <div class="rich" dangerouslySetInnerHTML={{ __html: renderRich(text) }} />
);

/* ────────────────────────── 长按复制 ────────────────────────── */
/** 按住 520ms 触发；手指一滑（>10px）就当滚动，不触发；触发后吞掉紧随的 click
    （避免长按折叠块时把块也展开）。 */
function useLongPress(onLong: () => void, ms = 520) {
  const timer = useRef(0);
  const fired = useRef(false);
  const origin = useRef({ x: 0, y: 0 });
  const cancel = () => {
    if (timer.current) { clearTimeout(timer.current); timer.current = 0; }
  };
  return {
    onPointerDown: (e: PointerEvent) => {
      if (e.button > 0) return;
      fired.current = false;
      origin.current = { x: e.clientX, y: e.clientY };
      cancel();
      timer.current = window.setTimeout(() => {
        timer.current = 0;
        fired.current = true;
        onLong();
      }, ms);
    },
    onPointerMove: (e: PointerEvent) => {
      if (!timer.current) return;
      const dx = e.clientX - origin.current.x;
      const dy = e.clientY - origin.current.y;
      if (dx * dx + dy * dy > 100) cancel();
    },
    onPointerUp: cancel,
    onPointerLeave: cancel,
    onPointerCancel: cancel,
    onClickCapture: (e: MouseEvent) => {
      if (!fired.current) return;
      fired.current = false;
      e.stopPropagation();
      e.preventDefault();
    },
  };
}

/** 壁纸压缩：和旧版同口径（最长边 1280、JPEG 0.85），dataURL 存 localStorage / 服务端 */
function compressImage(file: File, maxDim = 1280, quality = 0.85): Promise<string> {
  return new Promise((resolve, reject) => {
    const objUrl = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      try {
        const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
        const w = Math.max(1, Math.round(img.width * scale));
        const h = Math.max(1, Math.round(img.height * scale));
        const cv = document.createElement('canvas');
        cv.width = w; cv.height = h;
        const ctx = cv.getContext('2d');
        if (!ctx) { reject(new Error('画布不可用')); return; }
        ctx.drawImage(img, 0, 0, w, h);
        resolve(cv.toDataURL('image/jpeg', quality));
      } catch (e) { reject(e as Error); }
      finally { URL.revokeObjectURL(objUrl); }
    };
    img.onerror = () => { URL.revokeObjectURL(objUrl); reject(new Error('图片读取失败')); };
    img.src = objUrl;
  });
}

/* ────────────────────────── 图片缩略图 / 大图 ────────────────────────── */
type AttLike = { name: string; path: string; image?: boolean };

const IMG_EXT = /\.(png|jpe?g|webp|gif|bmp)$/i;
const extOf = (name: string): string => {
  const m = String(name || '').match(/\.([A-Za-z0-9]{1,6})$/);
  return m ? m[1].toUpperCase() : 'FILE';
};
const badgeKind = (ext: string): string => {
  if (ext === 'PDF') return 'pdf';
  if (['DOC', 'DOCX', 'RTF', 'TXT', 'MD'].includes(ext)) return 'doc';
  if (['XLS', 'XLSX', 'CSV'].includes(ext)) return 'sheet';
  if (['PPT', 'PPTX'].includes(ext)) return 'slide';
  if (['ZIP', 'RAR', '7Z', 'GZ', 'TAR'].includes(ext)) return 'zip';
  if (['JS', 'TS', 'TSX', 'JSX', 'PY', 'JAVA', 'KT', 'GO', 'RS', 'C', 'CPP', 'H', 'JSON', 'YAML', 'YML', 'HTML', 'CSS', 'SH', 'XML'].includes(ext)) return 'code';
  if (['PNG', 'JPG', 'JPEG', 'WEBP', 'GIF', 'BMP', 'SVG', 'HEIC'].includes(ext)) return 'img';
  return 'generic';
};
const isDocType = (ext: string) => ['PDF', 'DOC', 'DOCX', 'TXT', 'MD', 'CSV', 'XLS', 'XLSX', 'PPT', 'PPTX'].includes(ext);
const isImageAtt = (a: AttLike) => !!a.image || IMG_EXT.test(a.name || a.path || '');

function Thumb({ path, name, onOpen }: { path: string; name: string; onOpen?: (path: string, name: string) => void }) {
  const [src, setSrc] = useState<string | null>(() => cachedBlobUrl(path));
  const [bad, setBad] = useState(false);
  useEffect(() => {
    let alive = true;
    const hit = cachedBlobUrl(path);
    if (hit) { setSrc(hit); return () => { alive = false; }; }
    blobUrl(path).then((u) => { if (alive) setSrc(u); }).catch(() => { if (alive) setBad(true); });
    return () => { alive = false; };
  }, [path]);
  if (bad) {
    return <span class="att-chip"><Icon name="clip" size={11} /><span class="att-name">{name}</span></span>;
  }
  return (
    <button class="thumb" title={name} onClick={() => onOpen?.(path, name)}>
      {src ? <img src={src} alt={name} loading="lazy" /> : <span class="thumb-load" />}
    </button>
  );
}

function ImageViewer({ path, name, onClose }: { path: string; name: string; onClose: () => void }) {
  const [src, setSrc] = useState<string | null>(() => cachedBlobUrl(path));
  useEffect(() => {
    let alive = true;
    const hit = cachedBlobUrl(path);
    if (hit) setSrc(hit);
    else blobUrl(path).then((u) => { if (alive) setSrc(u); }).catch(() => null);
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => { alive = false; document.removeEventListener('keydown', onKey); };
  }, [path]);
  return (
    <div class="viewer" onClick={onClose}>
      {src
        ? <img src={src} alt={name} onClick={(e) => e.stopPropagation()} />
        : <div class="viewer-load">加载中…</div>}
      <div class="viewer-bar" onClick={(e) => e.stopPropagation()}>
        <span class="viewer-name">{name}</span>
        <button class="viewer-btn" onClick={() => { downloadRaw(path, name).catch(() => toast('下载失败', 'err')); }}>下载</button>
        <button class="viewer-btn" onClick={onClose}>关闭</button>
      </div>
    </div>
  );
}

/* ────────────────────────── 登录 ────────────────────────── */
function Login({ onSubmit }: { onSubmit: (pin: string) => Promise<void> }) {
  const [pin, setLocal] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const inp = useRef<HTMLInputElement>(null);
  useEffect(() => { setTimeout(() => inp.current?.focus(), 120); }, []);

  const submit = async (e?: Event) => {
    e?.preventDefault();
    if (pin.length < 4 || busy) return;
    setBusy(true); setErr('');
    try { await onSubmit(pin); setBusy(false); }
    catch (e2) {
      setBusy(false);
      setErr((e2 as ApiError)?.message || '连接失败');
      setPin('');
    }
  };

  return (
    <div class="login">
      <form class="login-card" onSubmit={submit}>
        <div class="login-mark"><span>⌘</span></div>
        <h1>手机远程控制台</h1>
        <p class="login-sub">在手机上继续电脑上的 DSH 会话</p>
        <label class="login-label" for="pin">访问 PIN</label>
        <input id="pin" ref={inp} class="login-input" inputMode="numeric"
          autocomplete="one-time-code" placeholder="8 位数字" value={pin} maxLength={12}
          onInput={(e) => setLocal((e.currentTarget as HTMLInputElement).value.replace(/\D/g, ''))}
          onKeyDown={(e) => { if (e.key === 'Enter') submit(); }} />
        {err ? <div class="login-err">{err}</div> : null}
        <button class="login-btn" type="submit" disabled={pin.length < 4 || busy}>
          {busy ? '连接中…' : '连接'}
        </button>
        <p class="login-hint">PIN 在电脑端管理面板 / 二维码里（链接自带 PIN 可直接进入）</p>
      </form>
      <a class="login-legacy" href="/legacy">打开旧版界面 →</a>
    </div>
  );
}

/* ────────────────────────── 顶栏 ────────────────────────── */
function TopBar(props: {
  title: string; running: boolean; status: string;
  onMenu: () => void; onNew: () => void; onSettings: () => void;
}) {
  return (
    <header class="topbar">
      <button class="ghost-btn" onClick={props.onMenu} aria-label="会话列表"><Icon name="menu" /></button>
      <div class="topbar-title">
        <b>{props.title || '会话'}</b>
        <span class={'status ' + (props.running ? 'run' : '')}>
          <i />{props.running ? (props.status || '运行中') : '空闲'}
        </span>
      </div>
      <button class="ghost-btn" onClick={props.onNew} aria-label="新会话"><Icon name="plus" /></button>
      <button class="ghost-btn" onClick={props.onSettings} aria-label="设置"><Icon name="gear" /></button>
    </header>
  );
}

/* ────────────────────────── 消息 ────────────────────────── */
const FOLD_KINDS = new Set(['thinking', 'reasoning', 'plan']);
const TOOL_KINDS = new Set(['tool', 'command', 'command_update', 'exec', 'shell']);
const META_KINDS = new Set(['status', 'turn_done', 'notice']);

function MessageBlock({ item, onOpenImage }: { item: Item; onOpenImage?: (path: string, name: string) => void }) {
  const kind = (item.kind || '').toLowerCase();
  const [open, setOpen] = useState(false);

  // 长按复制：用户消息复制原文，智能体消息复制正文/输出
  const copyable = kind === 'user' ? (item.displayText || item.text || '') : (item.text || item.output || '');
  const longPress = useLongPress(() => {
    if (!copyable) return;
    copyText(copyable).then((ok) => toast(ok ? '已复制' : '复制失败', ok ? 'ok' : 'err'));
  });

  if (kind === 'user') {
    // attachments / images / files 三个来源合并（服务端不同版本只填其中一部分），按 path 去重
    const merged: AttLike[] = [];
    const seen = new Set<string>();
    const pushAtt = (a: AttLike) => {
      const key = a.path || a.name;
      if (!key || seen.has(key)) return;
      seen.add(key);
      merged.push(a);
    };
    (item.attachments || []).forEach((a: any) => pushAtt({ name: a.name || baseName(a.path || ''), path: a.path, image: !!a.image }));
    (item.images || []).forEach((p: string) => pushAtt({ name: baseName(p), path: p, image: true }));
    (item.files || []).forEach((p: string) => pushAtt({ name: baseName(p), path: p, image: false }));
    const atts: AttLike[] = merged;
    const imgs = atts.filter(isImageAtt);
    const files = atts.filter((a) => !isImageAtt(a));
    return (
      <div class="msg msg-user" {...longPress}>
        <div class="msg-role">你</div>
        <Rich text={item.displayText || item.text || ''} />
        {imgs.length ? (
          <div class="thumbs">
            {imgs.map((a, i) => <Thumb key={(a.path || '') + i} path={a.path} name={a.name} onOpen={onOpenImage} />)}
          </div>
        ) : null}
        {files.length ? (
          <div class="atts">
            {files.map((a, i) => (
              <button class="file-card" key={(a.path || '') + i} title={'下载 ' + a.name}
                onClick={() => { downloadRaw(a.path, a.name).catch(() => toast('下载失败', 'err')); }}>
                <span class={'file-badge ' + badgeKind(extOf(a.name))}>{extOf(a.name)}</span>
                <span class="file-meta">
                  <span class="file-name">{a.name}</span>
                  <span class="file-sub">{badgeKind(extOf(a.name)).toUpperCase()} · 点一下下载</span>
                </span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
    );
  }
  if (kind === 'question' || (item.questions && item.questions.length)) {
    return <QuestionCard item={item} />;
  }
  if (META_KINDS.has(kind)) {
    const t = kind === 'turn_done' ? '本轮完成' : (item.text || '');
    if (!t) return null;
    return <div class="msg-meta"><i />{t}</div>;
  }
  if (FOLD_KINDS.has(kind)) {
    const running = item.stream || item.status === 'run';
    return (
      <div class="msg msg-fold">
        <button class="fold-head" onClick={() => setOpen(!open)}>
          <span class={'fold-chev' + (open ? ' open' : '')}><Icon name="chevron" size={14} /></span>
          <span class="fold-label">{kind === 'plan' ? '计划' : '思考'}</span>
          {running ? <span class="fold-run">进行中</span> : null}
          <span class="fold-preview">{firstLine(item.text || '')}</span>
        </button>
        {open ? <div class="fold-body"><Rich text={item.text || ''} /></div> : null}
      </div>
    );
  }
  if (TOOL_KINDS.has(kind)) {
    const name = item.name || (kind === 'tool' ? 'tool' : kind);
    const cmd = item.command || item.args || '';
    const failed = item.status === 'fail' || !!item.error;
    return (
      <div class="msg msg-fold">
        <button class="fold-head" onClick={() => setOpen(!open)}>
          <span class={'fold-chev' + (open ? ' open' : '')}><Icon name="chevron" size={14} /></span>
          <span class="fold-label">{name}</span>
          {item.status === 'run' ? <span class="fold-run">执行中</span> : null}
          {failed ? <span class="fold-err">失败</span> : null}
          <span class="fold-preview">{firstLine(cmd || item.text || item.output || '')}</span>
        </button>
        {open ? (
          <div class="fold-body">
            {cmd ? <pre class="mono-block">{cmd}</pre> : null}
            {item.error ? <pre class="mono-block err">{item.error}</pre> : null}
            {item.text ? <Rich text={item.text} /> : null}
            {item.output ? <pre class="mono-block out">{item.output}</pre> : null}
          </div>
        ) : null}
      </div>
    );
  }
  if (kind === 'error') {
    return (
      <div class="msg msg-error" {...longPress}>
        <div class="msg-role">错误</div>
        <pre class="mono-block">{item.text || item.output || '出错了'}</pre>
      </div>
    );
  }
  return (
    <div class="msg msg-agent" {...longPress}>
      <div class="msg-role">智能体</div>
      <Rich text={item.text || item.output || ''} />
      {item.stream ? <span class="cursor" /> : null}
    </div>
  );
}

function baseName(p: string): string {
  const t = String(p || '');
  const i = Math.max(t.lastIndexOf('\\'), t.lastIndexOf('/'));
  return i >= 0 ? t.slice(i + 1) : t;
}

function firstLine(s: string): string {
  const t = String(s || '').replace(/\s+/g, ' ').trim();
  return t.length > 60 ? t.slice(0, 60) + '…' : t;
}

/* ────────────────────────── 问答卡（智能体提问 → 手机回答） ────────────────────────── */
function QuestionCard({ item }: { item: Item }) {
  const qs = item.questions || [];
  const [sel, setSel] = useState<Record<string, string>>({});
  const [custom, setCustom] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async () => {
    if (!item.sessionId || !item.rpc_id) { toast('这条提问缺少会话信息，请在旧版界面回答', 'err'); return; }
    setBusy(true);
    try {
      const answers = qs.map((q) => ({
        id: q.id,
        selected: sel[q.id] ? [sel[q.id]] : [],
        custom: (custom[q.id] || '').trim() || undefined,
      }));
      await answerQuestion(item.sessionId, item.rpc_id, answers);
      setDone(true);
      toast('已回答', 'ok');
    } catch (e) {
      toast('回答失败：' + (e as Error).message, 'err');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div class="msg qcard">
      <div class="qhead">智能体在等你的回答</div>
      {qs.map((q, qi) => (
        <div class="qitem" key={q.id || qi}>
          <div class="qtext">{q.question || ''}</div>
          {(q.options || []).map((o, oi) => (
            <label class="qopt" key={oi}>
              <input type="radio" name={'q' + (q.id || qi)} checked={sel[q.id] === o.label}
                onChange={() => setSel((v) => ({ ...v, [q.id]: o.label }))} />
              <span>{o.label}</span>
            </label>
          ))}
          <input class="qcustom" placeholder="自定义回答（可选）" value={custom[q.id] || ''}
            onInput={(e) => setCustom((v) => ({ ...v, [q.id]: (e.currentTarget as HTMLInputElement).value }))} />
        </div>
      ))}
      <button class="primary-btn" disabled={busy || done} onClick={submit}>
        {done ? '已回答' : busy ? '发送中…' : '回答'}
      </button>
    </div>
  );
}

/* ────────────────────────── 输入栏 ────────────────────────── */
type Attachment = {
  key: string; name: string; size: number; image: boolean;
  path?: string; pct: number; error?: string;
  /** 本地预览（图片选择后立刻显示，不用等上传） */
  preview?: string;
};

/* 手机/平板（粗指针）：回车换行，发送只走按钮或 Ctrl+Enter */
const COARSE_POINTER = typeof window !== 'undefined' && !!window.matchMedia
  && window.matchMedia('(pointer: coarse)').matches;

function Composer(props: {
  disabled: boolean; running: boolean;
  modelName?: string; effortName?: string; onOpenModel?: () => void;
  onCommands?: () => void;
  pickToken?: number;
  queue?: { text: string; images: string[]; files: string[] }[];
  onDropQueue?: (i: number) => void;
  onPromoteQueue?: (i: number) => void;
  onInsert?: (text: string, images: string[], files: string[]) => Promise<void>;
  onSend: (text: string, images: string[], files: string[]) => Promise<void>;
  onStop: () => void; upload: (f: File, onPct: (p: number) => void) => Promise<{ name: string; path: string; size: number } | null>;
}) {
  const [text, setText] = useState('');
  const [attach, setAttach] = useState<Attachment[]>([]);
  const ta = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (props.pickToken) fileInput.current?.click();
  }, [props.pickToken]);
  const uploading = attach.some((a) => !a.path && !a.error);
  const ready = attach.filter((a) => a.path);

  useEffect(() => {
    const el = ta.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 140) + 'px';
  }, [text]);

  const setA = (key: string, patch: Partial<Attachment>) =>
    setAttach((list) => list.map((a) => (a.key === key ? { ...a, ...patch } : a)));

  const doSend = async () => {
    const t = text.trim();
    if (uploading || props.disabled) return;
    if (!t && !ready.length) return;
    const images = ready.filter((a) => a.image).map((a) => a.path as string);
    const files = ready.filter((a) => !a.image).map((a) => a.path as string);
    const placeholder = images.length ? '[图片附件]' : files.length ? '[文件附件]' : '';
    const keepText = text;
    const keepAttach = attach;
    setText(''); setAttach([]);
    try {
      await props.onSend(t || placeholder, images, files);
      keepAttach.forEach((a) => { if (a.preview) URL.revokeObjectURL(a.preview); });
    } catch (e) {
      // 发送失败：把文字和附件原样放回输入栏，直接再点发送即可重试
      toast(((e as Error).message || '发送失败') + '，已保留输入内容', 'err');
      setText(keepText);
      setAttach(keepAttach);
    }
  };

  const pick = async (list: FileList | null) => {
    if (!list || !list.length) return;
    for (const f of Array.from(list)) {
      const key = 'a' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
      const isImg = /^image\//.test(f.type);
      setAttach((a) => a.concat([{
        key, name: f.name, size: f.size, image: isImg, pct: 0,
        preview: isImg ? URL.createObjectURL(f) : undefined,
      }]));
      try {
        const r = await props.upload(f, (p) => setA(key, { pct: p }));
        if (r) setA(key, { path: r.path, name: r.name, size: r.size, pct: 1 });
        else setA(key, { error: '上传失败' });
      } catch (e) {
        setA(key, { error: (e as Error).message || '上传失败' });
        toast('上传失败：' + ((e as Error).message || '未知原因'), 'err');
      }
    }
  };

  const dropAtt = (a: Attachment) => {
    if (a.preview) URL.revokeObjectURL(a.preview);
    setAttach((list) => list.filter((x) => x.key !== a.key));
  };

  return (
    <div class="composer">
      {attach.length ? (
        <div class="attach-row">
          {attach.map((a) => (a.image ? (
            <div class={'attach-thumb' + (a.error ? ' bad' : '')} key={a.key} title={a.name}>
              {a.preview ? <img src={a.preview} alt={a.name} /> : null}
              {!a.path && !a.error
                ? <span class="attach-thumb-bar"><i style={{ width: Math.round(a.pct * 100) + '%' }} /></span>
                : null}
              {a.error ? <span class="attach-thumb-err">{a.error}</span> : null}
              <button class="attach-thumb-x" onClick={() => dropAtt(a)}><Icon name="close" size={11} /></button>
            </div>
          ) : (
            <span class={'attach-chip' + (a.error ? ' bad' : a.path ? ' ok' : ' up')} key={a.key}>
              <span class={'attach-badge ' + badgeKind(extOf(a.name))}>{extOf(a.name)}</span>
              <span class="attach-col">
                <span class="attach-name">{a.name}</span>
                {a.error ? <span class="attach-pct err">{a.error}</span>
                  : a.path ? <span class="attach-pct">{fmtSize(a.size)}</span>
                  : <span class="attach-pct">{a.pct > 0.02 ? Math.round(a.pct * 100) + '%' : '上传中…'}</span>}
                {!a.path && !a.error ? <span class="attach-bar"><i style={'width:' + Math.round(a.pct * 100) + '%'} /></span> : null}
              </span>
              <button onClick={() => dropAtt(a)}>
                <Icon name="close" size={12} />
              </button>
            </span>
          )))}
        </div>
      ) : null}
      {props.queue && props.queue.length ? (
        <div class="queue-row">
          {props.queue.map((q, i) => (
            <span class="queue-chip" key={i}>
              <b>排队 {i + 1}</b>
              <span class="queue-text">{(q.text || (q.images.length || q.files.length ? '[附件]' : '')).slice(0, 24)}</span>
              <button class="queue-go" title="插队：立即中止当前回答并发送这条"
                onClick={() => props.onPromoteQueue?.(i)}>
                <Icon name="up" size={13} />
              </button>
              <button class="queue-x" title="取消排队" onClick={() => props.onDropQueue?.(i)}>✕</button>
            </span>
          ))}
        </div>
      ) : null}
      <div class="composer-box">
        <div class="composer-top">
          <textarea ref={ta} rows={2} value={text} disabled={props.disabled}
            placeholder={props.disabled ? '先选择一个会话…' : uploading ? '附件上传中…'
              : (props.running ? '正在回答…输入后点 ➤ 排队（长按=立即插入）' : '发消息给智能体…（回车换行）')}
            onInput={(e) => setText((e.currentTarget as HTMLTextAreaElement).value)}
            onKeyDown={(e) => {
              if ((e as any).isComposing) return;
              const withMod = e.ctrlKey || e.metaKey;
              if (e.key === 'Enter' && (withMod || (!COARSE_POINTER && !e.shiftKey))) {
                e.preventDefault();
                doSend();
              }
            }} />
          <div class="composer-btns">
            {/* 只留一个按钮：DSH 风格 —— 忙时输入为空=停止，有文字=排队，长按=立即插入 */}
            <button
              class={'composer-send' + (props.running && !text.trim() && !ready.length ? ' stop' : (props.running ? ' queue' : ''))}
              disabled={props.disabled || uploading || (!props.running && !text.trim() && !ready.length)}
              title={props.running
                ? (text.trim() || ready.length ? '排队发送（长按 = 立即插入）' : '停止')
                : '发送'}
              onPointerDown={() => {
                if (!props.running) return;
                if (!text.trim() && !ready.length) return;
                (window as any).__holdTimer = setTimeout(() => {
                  (window as any).__holdTimer = 0;
                  const t = text.trim();
                  const images = ready.filter((a) => a.image).map((a) => a.path as string);
                  const files = ready.filter((a) => !a.image).map((a) => a.path as string);
                  const placeholder = images.length ? '[图片附件]' : files.length ? '[文件附件]' : '';
                  props.onInsert?.(t || placeholder, images, files);
                  setText(''); setAttach([]);
                  toast('已插入：中止当前回答并立即发送', 'ok');
                }, 620);
              }}
              onPointerUp={() => {
                const t = (window as any).__holdTimer;
                if (t) { clearTimeout(t); (window as any).__holdTimer = 0; }
              }}
              onPointerLeave={() => {
                const t = (window as any).__holdTimer;
                if (t) { clearTimeout(t); (window as any).__holdTimer = 0; }
              }}
              onClick={() => {
                if (props.running && !text.trim() && !ready.length) { props.onStop(); return; }
                doSend();
              }}>
              {props.running && !text.trim() && !ready.length ? <Icon name="stop" /> : <Icon name="send" />}
            </button>
          </div>
        </div>
        <div class="composer-bar">
          <button class="composer-btn" title="命令（/）" disabled={props.disabled}
            onClick={() => props.onCommands?.()}>
            <span class="slash-glyph">/</span>
          </button>
          <button class="composer-btn" title="添加图片/文件" disabled={props.disabled}
            onClick={() => fileInput.current?.click()}>
            <Icon name="clip" />
          </button>
          <input ref={fileInput} type="file" hidden multiple
            onChange={(e) => { pick((e.currentTarget as HTMLInputElement).files); (e.currentTarget as HTMLInputElement).value = ''; }} />
          <button class="meta-chip" type="button" onClick={() => props.onOpenModel?.()}>
            {props.modelName || '选择模型'}
          </button>
          <button class="meta-chip" type="button" onClick={() => props.onOpenModel?.()}>
            强度 · {props.effortName || '默认'}
          </button>
        </div>
        </div>
      </div>
  );
}

/* ────────────────────────── 斜杠命令（对齐 DSH 菜单） ────────────────────────── */
const REPO_URL = 'https://github.com/wwu328763-netizen/deepseek-phone-console';

function CommandSheet(props: {
  open: boolean; onClose: () => void; plan: any; active: any;
  onFile: () => void; onModel: () => void; onExport: () => void;
}) {
  if (!props.open) return null;
  const hasGoal = !!(props.plan && props.plan.goal && props.plan.goal.objective);
  const hasTodos = !!(props.plan && (props.plan.todos || []).length);
  const todo = (ev: string, fn?: () => void) => {
    if (!fn) { toast('这个指令需要在电脑端 DSH 里执行', 'err'); return; }
    fn();
    props.onClose();
  };
  return (
    <div class="sheet-wrap">
      <div class="sheet-mask" onClick={props.onClose} />
      <div class="sheet">
        <div class="sheet-grab" />
        <div class="sheet-head"><b>命令</b><button class="ghost-btn" onClick={props.onClose}><Icon name="close" /></button></div>
        <div class="cmd-group">添加</div>
        <button class="cmd-row" onClick={() => todo('file', props.onFile)}>
          <span class="cmd-ico"><Icon name="clip" size={15} /></span>
          <span class="cmd-name">文件<em>file</em></span>
          <span class="cmd-desc">上传图片或文档</span>
        </button>
        <button class="cmd-row" onClick={() => {
          if (!hasTodos) { toast('当前会话还没有计划；DSH 生成计划后会自动出现在输入框上方', 'err'); return; }
          window.dispatchEvent(new CustomEvent('plan:toggle', { detail: true }));
          props.onClose();
        }}>
          <span class="cmd-ico"><Icon name="list" size={15} /></span>
          <span class="cmd-name">计划<em>plan</em></span>
          <span class="cmd-desc">{hasTodos ? '查看当前计划进度' : '本会话暂无计划'}</span>
        </button>
        <button class="cmd-row" onClick={() => {
          if (!hasGoal) { toast('当前会话没有目标；长期目标需在电脑端 DSH 里设置', 'err'); return; }
          window.dispatchEvent(new CustomEvent('plan:toggle', { detail: true }));
          props.onClose();
        }}>
          <span class="cmd-ico"><Icon name="target" size={15} /></span>
          <span class="cmd-name">目标<em>goal</em></span>
          <span class="cmd-desc">{hasGoal ? '查看长期任务目标' : '本会话未设置目标'}</span>
        </button>
        <div class="cmd-group">指令</div>
        <button class="cmd-row" onClick={() => todo('model', props.onModel)}>
          <span class="cmd-ico"><Icon name="gear" size={15} /></span>
          <span class="cmd-name">模型<em>model</em></span>
          <span class="cmd-desc">切换本会话模型与强度</span>
        </button>
        <button class="cmd-row" onClick={() => todo('export', props.onExport)}>
          <span class="cmd-ico"><Icon name="download" size={15} /></span>
          <span class="cmd-name">导出<em>export</em></span>
          <span class="cmd-desc">把当前对话导出为 JSON</span>
        </button>
        <button class="cmd-row" onClick={() => { window.open(REPO_URL + '/issues/new', '_blank'); props.onClose(); }}>
          <span class="cmd-ico"><Icon name="send" size={15} /></span>
          <span class="cmd-name">反馈<em>feedback</em></span>
          <span class="cmd-desc">去 GitHub 提 issue</span>
        </button>
        <button class="cmd-row dim" onClick={() => todo('compact')}>
          <span class="cmd-ico"><Icon name="archive" size={15} /></span>
          <span class="cmd-name">压缩<em>compact</em></span>
          <span class="cmd-desc">电脑端 DSH 里执行</span>
        </button>
        <button class="cmd-row dim" onClick={() => todo('permission')}>
          <span class="cmd-ico"><Icon name="lock" size={15} /></span>
          <span class="cmd-name">权限<em>permission</em></span>
          <span class="cmd-desc">电脑端 DSH 里执行</span>
        </button>
      </div>
    </div>
  );
}

/* ────────────────────────── 计划 / 目标（DSH 镜像） ────────────────────────── */
const PLAN_OPEN_KEY = 'console_plan_open';

function PlanBar({ plan }: { plan: any }) {
  const [open, setOpen] = useState<boolean>(() => localStorage.getItem(PLAN_OPEN_KEY) !== '0');
  const todos: any[] = (plan && plan.todos) || [];
  const goal = plan && plan.goal ? plan.goal : null;
  if (!todos.length && !(goal && goal.objective)) return null;
  const done = todos.filter((t) => t.status === 'completed').length;
  const cur = todos.find((t) => t.status === 'in_progress');
  useEffect(() => {
    const onOpen = (e: any) => {
      const want = e?.detail;
      const v = want === undefined ? !open : !!want;
      setOpen(v);
      localStorage.setItem(PLAN_OPEN_KEY, v ? '1' : '0');
    };
    window.addEventListener('plan:toggle', onOpen as any);
    return () => window.removeEventListener('plan:toggle', onOpen as any);
  }, [open]);

  const toggle = () => {
    const v = !open;
    setOpen(v);
    localStorage.setItem(PLAN_OPEN_KEY, v ? '1' : '0');
  };
  return (
    <div class={'plan-bar' + (open ? ' open' : '')}>
      <button class="plan-head" onClick={toggle}>
        <Icon name="list" size={14} />
        <span class="plan-title">{goal && goal.objective ? '目标' : '计划'}</span>
        <span class="plan-progress">{todos.length ? done + '/' + todos.length : ''}</span>
        <span class="plan-cur">{goal && goal.objective ? goal.objective : (cur ? cur.content : (todos.length && done === todos.length ? '全部完成' : ''))}</span>
        <span class="plan-arrow">{open ? '▾' : '▸'}</span>
      </button>
      {open ? (
        <div class="plan-body">
          {goal && goal.objective ? <div class="plan-goal">{goal.objective}</div> : null}
          <div class="plan-list">
            {todos.map((t, i) => (
              <div class={'plan-item ' + (t.status || 'pending')} key={i}>
                <span class="plan-ico">
                  {t.status === 'completed' ? '✓' : t.status === 'in_progress' ? '●' : '○'}
                </span>
                <span class="plan-text">{t.content}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function fmtSize(n: number): string {
  if (!n) return '';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(0) + ' KB';
  return (n / 1024 / 1024).toFixed(1) + ' MB';
}

/* ────────────────────────── 会话列表（抽屉） ────────────────────────── */

/* ────────────────────────── 用量与计费 ────────────────────────── */
function compactNum(n: number): string {
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return String(Math.round(n));
}

function UsageSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [usage, setUsage] = useState<any>(null);
  const [bal, setBal] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const load = async (refresh = false) => {
    setBusy(true);
    try {
      if (refresh) await refreshUsage().catch(() => null);
      const [u, b] = await Promise.all([
        getUsage().catch(() => null),
        getBalance().catch(() => null),
      ]);
      if (u) setUsage(u);
      if (b) setBal(b);
    } finally { setBusy(false); }
  };
  useEffect(() => { if (open) load(); }, [open]);

  if (!open) return null;
  const o = usage?.official;
  const days: string[] = (o?.days || []).slice();
  const per: Record<string, any> = o?.per_day || {};
  const last7 = days.slice(-7);
  const sumOf = (d: string) => {
    const r = per[d] || {};
    return (r.hit || 0) + (r.miss || 0) + (r.output || 0);
  };
  const maxV = Math.max(1, ...last7.map(sumOf));
  const coin = bal?.balance_infos?.[0];
  const totalTokens = o ? (o.hit || 0) + (o.miss || 0) + (o.output || 0) : 0;

  return (
    <div class="sheet-wrap">
      <div class="sheet-mask" onClick={onClose} />
      <div class="sheet">
        <div class="sheet-grab" />
        <div class="sheet-head">
          <b>用量与计费</b>
          <div class="row-actions">
            <button class="ghost-btn" onClick={() => load(true)} title="从 DeepSeek 官网刷新">{busy ? '…' : '刷新'}</button>
            <button class="ghost-btn" onClick={onClose}><Icon name="close" /></button>
          </div>
        </div>

        <div class="usage-hero">
          <div class="usage-hero-label">DeepSeek 账户余额</div>
          <div class="usage-hero-value">
            {coin ? (coin.currency === 'CNY' ? '¥' : '') + coin.total_balance : '—'}
          </div>
          <div class="usage-hero-sub">
            {coin ? (coin.currency === 'CNY' ? '人民币' : coin.currency) + ' · 已充值 ' + (coin.topped_up_balance ?? '—') : (bal && bal.is_available === false ? '未配置 API Token，去桌面端面板设置' : '读取中…')}
          </div>
          <a class="primary-btn" href="https://platform.deepseek.com/top_up" target="_blank" rel="noopener">去充值</a>
        </div>

        <div class="field">
          <label>官方用量（全部时间）</label>
          <div class="usage-grid">
            <div><span>覆盖</span><b>{days.length} 天</b></div>
            <div><span>请求</span><b>{(o?.requests || 0).toLocaleString()}</b></div>
            <div><span>总 tokens</span><b>{compactNum(totalTokens)}</b></div>
            <div><span>缓存命中率</span><b>{o ? Number(o.hit_rate || 0).toFixed(2) + '%' : '—'}</b></div>
            <div><span>命中缓存</span><b>{compactNum(o?.hit || 0)}</b></div>
            <div><span>未命中</span><b>{compactNum(o?.miss || 0)}</b></div>
            <div><span>输出</span><b>{compactNum(o?.output || 0)}</b></div>
            <div><span>统计区间</span><b>{days.length ? days[0].slice(5) + ' ~ ' + days[days.length - 1].slice(5) : '—'}</b></div>
          </div>
        </div>

        <div class="field">
          <label>近 7 天</label>
          {last7.length ? (
            <div class="usage-bars">
              {last7.map((d) => (
                <div class="usage-bar" key={d}>
                  <div class="usage-bar-track">
                    <i style={{ height: Math.max(3, Math.round(sumOf(d) / maxV * 72)) + 'px' }} />
                  </div>
                  <div class="usage-bar-label">{d.slice(5)}</div>
                </div>
              ))}
            </div>
          ) : <div class="hint">还没有官方用量数据</div>}
          <div class="usage-list">
            {last7.slice().reverse().map((d) => {
              const r = per[d] || {};
              return (
                <div class="usage-row" key={d}>
                  <span class="usage-date">{d.slice(5)}</span>
                  <span>{compactNum(sumOf(d))}</span>
                  <span class="usage-muted">命中 {compactNum(r.hit || 0)}</span>
                  <span class="usage-muted">{(r.requests || 0).toLocaleString()} 次</span>
                </div>
              );
            })}
          </div>
        </div>
        <div class="hint">数据来自电脑端 console_data/usage 的官网用量 CSV，由桌面面板定时拉取。</div>
      </div>
    </div>
  );
}

function Drawer(props: {
  open: boolean; onClose: () => void;
  onPick: (kind: 'thread' | 'session', id: string, title: string) => void;
  onNew: () => void; active: string | null;
}) {
  const s = useStore();
  const [tab, setTab] = useState<'thread' | 'session'>('thread');
  const [showArch, setShowArch] = useState(false);
  const [arch, setArch] = useState<{ thread: string[]; session: string[] }>({ thread: [], session: [] });
  const [usageOpen, setUsageOpen] = useState(false);

  useEffect(() => {
    if (!props.open) return;
    setShowArch(false);
    getArchived().then(setArch).catch(() => null);
  }, [props.open]);

  const archSet = new Set((tab === 'thread' ? arch.thread : arch.session) || []);
  const all = (tab === 'thread' ? s.threads : s.sessions) || [];
  const list = all.filter((it: any) => (showArch ? archSet.has(String(it.id)) : !archSet.has(String(it.id))));
  const archCount = all.filter((it: any) => archSet.has(String(it.id))).length;

  const toggleArchive = async (id: string, ev: any) => {
    ev.stopPropagation();
    const next = !archSet.has(String(id));
    try {
      await setArchived(tab, id, next);
      setArch(await getArchived());
      toast(next ? '已归档，可在「查看已归档」里找回' : '已取消归档', 'ok');
    } catch (e) {
      toast('归档失败：' + (e as Error).message, 'err');
    }
  };

  return (
    <div class={'drawer' + (props.open ? ' open' : '')}>
      <div class="drawer-mask" onClick={props.onClose} />
      <aside class="drawer-panel">
        <div class="drawer-head">
          <b>{showArch ? '已归档' : '会话'}</b>
          <button class="ghost-btn" onClick={props.onNew}><Icon name="plus" /></button>
        </div>
        <div class="seg">
          <button class={tab === 'thread' ? 'on' : ''} onClick={() => setTab('thread')}>手机任务</button>
          <button class={tab === 'session' ? 'on' : ''} onClick={() => setTab('session')}>电脑端</button>
        </div>
        <div class="drawer-list">
          {list.length === 0 ? <div class="drawer-empty">{showArch ? '没有归档的会话' : '还没有会话'}</div> : null}
          {list.map((it: any) => {
            const id = it.id;
            const title = it.name || it.cwd || id;
            const active = props.active === tab + ':' + id;
            return (
              <div key={id} class="row-wrap">
                <button class={'row' + (active ? ' active' : '')}
                  onClick={() => { props.onPick(tab, id, title); }}>
                  <span class={'row-dot' + (it.running ? ' run' : '')} />
                  <span class="row-title">{title}</span>
                  <span class="row-time">{relativeTime(it.created_at || it.updated)}</span>
                </button>
                <button class="row-arch" title={showArch ? '取消归档' : '归档'}
                  onClick={(ev) => toggleArchive(id, ev)}>
                  <Icon name="archive" size={14} />
                </button>
              </div>
            );
          })}
        </div>
        <button class="drawer-usage-btn" onClick={() => setUsageOpen(true)}>
          <Icon name="archive" size={14} />
          <span>用量与计费</span>
        </button>
        <button class="drawer-arch-toggle" onClick={() => setShowArch(!showArch)}>
          {showArch ? '返回会话列表' : '查看已归档' + (archCount ? '（' + archCount + '）' : '')}
        </button>
      </aside>
      <UsageSheet open={usageOpen} onClose={() => setUsageOpen(false)} />
    </div>
  );
}

/* ────────────────────────── 设置 ────────────────────────── */
type ActiveRef = { kind: 'thread' | 'session'; id: string; title: string } | null;

function Settings({ open, onClose, active }: { open: boolean; onClose: () => void; active: ActiveRef }) {
  const s = useStore();
  const [models, setModels] = useState<ModelsPayload | null>(null);
  const [modelId, setModelId] = useState('');
  const [effort, setEffort] = useState('');
  const [usage, setUsage] = useState<any>(null);
  const [bal, setBal] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [picker, setPicker] = useState(false);
  const [usageOpen, setUsageOpen] = useState(false);
  const [bg, setBg] = useState<BgState>(() => readBg());
  const [bgBusy, setBgBusy] = useState(false);
  const bgFile = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setBg(readBg());
    getModels(active?.kind || 'thread', active?.id || '').then((m) => {
      setModels(m);
      setModelId(m?.current?.model || '');
      setEffort(m?.current?.reasoningEffort || '');
    }).catch(() => null);
    getUsage().then(setUsage).catch(() => null);
    getBalance().then(setBal).catch(() => null);
  }, [open, active?.kind, active?.id]);

  /* 背景：改一个字段 → 立刻写 CSS 变量 + localStorage（滑块拖动要跟手） */
  const changeBg = (patch: Partial<BgState>) => {
    const next = { ...bg, ...patch };
    setBg(next);
    writeBg(patch);
    applyBg(next);
  };
  const pickBg = async (f: File | null | undefined) => {
    if (!f) return;
    setBgBusy(true);
    try {
      const url = await compressImage(f);
      changeBg({ url });
      saveBg({ url }).catch(() => toast('壁纸只在本机生效（服务端没保存上）', 'err'));
      toast('壁纸已设置', 'ok');
    } catch (e) {
      toast('壁纸设置失败：' + (e as Error).message, 'err');
    } finally { setBgBusy(false); }
  };
  const clearBg = () => {
    changeBg({ url: '' });
    saveBg({ url: '' }).catch(() => null);
    toast('壁纸已清除', 'ok');
  };

  const themes: { key: Theme; label: string }[] = [
    { key: 'auto', label: '跟随系统' }, { key: 'dark', label: '深色' }, { key: 'light', label: '浅色' },
  ];
  const groups = models?.catalog?.groups || [];
  const allModels = groups.reduce<ModelInfo[]>((acc, g) => acc.concat(g.models || []), []);
  const curModel = allModels.find((m) => m.id === modelId);
  const efforts = curModel?.reasoning?.efforts || [];
  const providerOf = (mid: string) => {
    for (const g of groups) { if ((g.models || []).some((x) => x.id === mid)) return g.id; }
    return '';
  };
  const canSwitch = !!(models && models.canSwitch && active);

  const applyPick = async (provider: string, mid: string, eff: string) => {
    if (!active || !canSwitch) { toast('先打开一段会话再切换模型', 'err'); return; }
    setBusy(true);
    try {
      await setModel(active.kind, active.id, provider, mid, eff || undefined);
      toast('已切换：' + mid + (eff ? ' · ' + eff : ''), 'ok');
      const m = await getModels(active.kind, active.id).catch(() => null);
      if (m) {
        setModels(m);
        setModelId(m.current?.model || mid);
        setEffort(m.current?.reasoningEffort || '');
      }
    } catch (e) {
      toast('切换失败：' + (e as Error).message, 'err');
    } finally { setBusy(false); }
  };

  const official = usage?.official || null;
  const hit = Number(official?.hit || 0), miss = Number(official?.miss || 0);
  const rate = hit + miss ? (hit / (hit + miss) * 100) : 0;
  const totalTokens = hit + miss + Number(official?.output || 0);
  const coin = bal?.balance_infos?.[0];

  if (!open) return null;
  return (
    <div class="sheet-wrap">
      <div class="sheet-mask" onClick={onClose} />
      <div class="sheet">
        <div class="sheet-grab" />
        <div class="sheet-head"><b>设置</b><button class="ghost-btn" onClick={onClose}><Icon name="close" /></button></div>

        <div class="field">
          <label>外观</label>
          <div class="seg">
            {themes.map((t) => (
              <button key={t.key} class={s.theme === t.key ? 'on' : ''} onClick={() => applyTheme(t.key)}>{t.label}</button>
            ))}
          </div>
        </div>

        <div class="field">
          <label>聊天背景</label>
          <div class="bg-row">
            <div class="bg-swatch" style={bg.url ? 'background-image:url("' + bg.url + '")' : ''}>
              {bg.url ? '' : <span>无壁纸</span>}
            </div>
            <div class="bg-btns">
              <button class="outline-btn sm" disabled={bgBusy} onClick={() => bgFile.current?.click()}>
                {bgBusy ? '处理中…' : bg.url ? '更换壁纸' : '选择壁纸'}
              </button>
              {bg.url ? <button class="outline-btn sm" onClick={clearBg}>清除壁纸</button> : null}
            </div>
          </div>
          <input ref={bgFile} type="file" accept="image/*" hidden
            onChange={(e) => {
              const el = e.currentTarget as HTMLInputElement;
              pickBg(el.files?.[0]);
              el.value = '';
            }} />
          <label>壁纸遮罩（{bg.veil}%）</label>
          <input class="range" type="range" min={0} max={100} value={bg.veil} disabled={!bg.url}
            onInput={(e) => changeBg({ veil: +(e.currentTarget as HTMLInputElement).value })} />
          <div class="hint">
            没设壁纸时，这一层就是聊天区的浅灰底；设了壁纸就是壁纸上的同色蒙层。壁纸会存到服务端，手机和电脑两个入口共用。
          </div>
        </div>

        <div class="field">
          <label>模型与思考强度{active ? '（对当前会话生效）' : ''}</label>
          <button class="picker-row" disabled={!canSwitch || busy} onClick={() => setPicker(true)}>
            <span class="picker-main">{curModel?.name || modelId || (active ? '加载中…' : '先打开会话')}</span>
            <span class="picker-sub">强度 · {efforts.find((x) => x.id === effort)?.name || effort || '默认'}</span>
            <span class="picker-arrow"><Icon name="chevron" size={14} /></span>
          </button>
          {!canSwitch ? <div class="hint">{active ? '当前会话不支持切换模型' : '打开一段会话后可以切换'}</div> : null}
        </div>
        {usageOpen ? <UsageSheet open={usageOpen} onClose={() => setUsageOpen(false)} /> : null}
        {picker ? (
          <ModelSheet open={picker} onClose={() => setPicker(false)} models={models}
            modelId={modelId} effort={effort} onApply={applyPick} busy={busy} />
        ) : null}

        <div class="field">
          <label>用量与余额</label>
          <div class="about-line"><span>余额</span><b>{coin ? coin.total_balance + ' ' + coin.currency : '—'}</b></div>
          <div class="about-line"><span>官网用量</span><b>{totalTokens ? (totalTokens / 1e9).toFixed(2) + 'B tokens' : '—'}</b></div>
          <div class="about-line"><span>缓存命中率</span><b>{totalTokens ? rate.toFixed(2) + '%' : '—'}</b></div>
          <div class="row-actions">
            <button class="outline-btn" onClick={() => setUsageOpen(true)}>查看详细用量与计费</button>
            <a class="outline-btn" href="https://platform.deepseek.com/top_up" target="_blank" rel="noopener">去充值</a>
            {(window as any).PhoneConsole && (window as any).PhoneConsole.toSettings && (
              <button class="outline-btn" onClick={() => { try { (window as any).PhoneConsole.toSettings(); } catch (e) {} }}>
                更换地址 / 重新登录
              </button>
            )}
          </div>
        </div>

        <div class="field">
          <label>关于</label>
          <div class="about-line"><span>界面</span><b>v2 · TypeScript + Preact</b></div>
          <div class="about-line"><span>内核</span><b>DSH agent · 控制台 HTTP API</b></div>
        </div>

        <div class="field">
          <button class="outline-btn" onClick={() => {
              const app = (window as any).PhoneConsole;
              if (app && typeof app.toSettings === 'function') {
                // APK：回原生连接/登录页（可以重新扫码或改地址）
                try { app.toSettings(); return; } catch (e) { /* 落回浏览器逻辑 */ }
              }
              localStorage.removeItem('console_pin');
              location.reload();   // 浏览器：回到网页登录页
            }}>
            返回登录界面
          </button>
          <button class="outline-btn" onClick={() => {
              const app = (window as any).PhoneConsole;
              if (app && typeof app.logout === 'function') { try { app.logout(); return; } catch (e) {} }
              localStorage.removeItem('console_pin');
              location.reload();
            }}>
            清除 PIN 并退出
          </button>
          <a class="outline-btn" href="/legacy">打开旧版界面</a>
        </div>
      </div>
    </div>
  );
}

/* ────────────────────────── 新会话 ────────────────────────── */
function NewThread({ open, onClose, onCreate }: {
  open: boolean; onClose: () => void; onCreate: (name: string, workdir: string) => void;
}) {
  const [name, setName] = useState('');
  const [path, setPath] = useState('');
  const [dirs, setDirs] = useState<string[]>([]);
  const [canUp, setCanUp] = useState(false);
  const [loading, setLoading] = useState(false);
  const [mkdirName, setMkdirName] = useState('');
  const [roots, setRoots] = useState<{ phone: string; dsh: string }>({ phone: '', dsh: '' });
  const [busy, setBusy] = useState(false);

  const join = (base: string, name: string) =>
    (base.endsWith('\\') || base.endsWith('/') ? base + name : base + '\\' + name);

  const browse = async (p: string) => {
    setLoading(true);
    try {
      const d = await listFiles(p || '');
      setPath(d.path || p);
      setDirs((d.entries || []).filter((e) => e.dir).map((e) => e.name));
      setCanUp(!!d.can_up);
    } catch (e) {
      toast('读目录失败：' + (e as Error).message, 'err');
    } finally { setLoading(false); }
  };

  useEffect(() => {
    if (!open) return;
    (async () => {
      let phone = '', dsh = '';
      try {
        const info = await getInfo();
        phone = info.phone_workspace || '';
        dsh = info.workdir_root || '';
        setRoots({ phone, dsh });
      } catch { /* 忽略：仍可用默认目录 */ }
      const saved = localStorage.getItem('console_workdir') || '';
      browse(saved || phone || dsh || '');
    })();
  }, [open]);

  const parentOf = (p: string) => {
    const i = Math.max(p.lastIndexOf('\\'), p.lastIndexOf('/'));
    return i > 2 ? p.slice(0, i) : p;
  };

  const mkdir = async () => {
    const n = mkdirName.trim();
    if (!n || !path) return;
    const full = join(path, n);
    setBusy(true);
    try {
      await makeDir(full);
      setMkdirName('');
      toast('已创建文件夹', 'ok');
      await browse(full);
    } catch (e) { toast('新建失败：' + (e as Error).message, 'err'); }
    finally { setBusy(false); }
  };

  if (!open) return null;
  return (
    <div class="sheet-wrap">
      <div class="sheet-mask" onClick={onClose} />
      <div class="sheet">
        <div class="sheet-grab" />
        <div class="sheet-head"><b>新会话</b><button class="ghost-btn" onClick={onClose}><Icon name="close" /></button></div>

        <div class="field">
          <label>名称</label>
          <input class="text-input" value={name} placeholder="例如：修一下登录页"
            onInput={(e) => setName((e.currentTarget as HTMLInputElement).value)} />
        </div>

        <div class="field">
          <label>工作目录</label>
          <div class="dir-path mono">{path || '—'}{loading ? ' …' : ''}</div>
          <div class="dir-actions">
            {roots.phone ? <button class="outline-btn sm" onClick={() => browse(roots.phone)}>手机任务目录</button> : null}
            {roots.dsh ? <button class="outline-btn sm" onClick={() => browse(roots.dsh)}>DSH 工作区</button> : null}
            {canUp ? <button class="outline-btn sm" onClick={() => browse(parentOf(path))}>↑ 上一级</button> : null}
          </div>
          <div class="dir-list">
            {dirs.map((d) => (
              <button class="dir-row" key={d} onClick={() => browse(join(path, d))}>
                <Icon name="chevron" size={13} /><span>{d}</span>
              </button>
            ))}
            {!dirs.length && !loading ? <div class="muted small">没有子目录（可以直接在此目录创建）</div> : null}
          </div>
          <div class="dir-mkdir">
            <input class="text-input" value={mkdirName} placeholder="新建文件夹名"
              onInput={(e) => setMkdirName((e.currentTarget as HTMLInputElement).value)} />
            <button class="outline-btn sm" disabled={!mkdirName.trim() || busy} onClick={mkdir}>新建</button>
          </div>
        </div>

        <button class="primary-btn" disabled={!name.trim() || !path.trim() || busy}
          onClick={() => {
            localStorage.setItem('console_workdir', path);
            setBusy(true);
            onCreate(name.trim(), path);
            setBusy(false);
          }}>
          创建并开始
        </button>
      </div>
    </div>
  );
}


/* ────────────────────────── 模型 / 强度选择（输入栏弹出，ChatGPT 式） ────────────────────────── */
function ModelSheet(props: {
  open: boolean; onClose: () => void;
  models: ModelsPayload | null;
  modelId: string; effort: string;
  onApply: (provider: string, modelId: string, effort: string) => Promise<void>;
  busy: boolean;
}) {
  const groups = props.models?.catalog?.groups || [];
  const all = groups.reduce<ModelInfo[]>((acc, g) => acc.concat(g.models || []), []);
  const cur = all.find((m) => m.id === props.modelId);
  const efforts = cur?.reasoning?.efforts || [];
  const [localEffort, setLocalEffort] = useState(props.effort);
  useEffect(() => { setLocalEffort(props.effort); }, [props.effort, props.modelId]);
  const providerOf = (mid: string) => {
    for (const g of groups) { if ((g.models || []).some((x) => x.id === mid)) return g.id; }
    return '';
  };
  if (!props.open) return null;
  return (
    <div class="sheet-wrap">
      <div class="sheet-mask" onClick={props.onClose} />
      <div class="sheet">
        <div class="sheet-grab" />
        <div class="sheet-head"><b>模型与思考强度</b>
          <button class="ghost-btn" onClick={props.onClose}><Icon name="close" /></button>
        </div>
        {!all.length ? <div class="hint">先打开一段会话，才能切换模型</div> : null}
        <div class="model-list">
          {groups.map((g) => (
            <div class="model-group" key={g.id}>
              <div class="model-group-title">{g.name || g.id}</div>
              {(g.models || []).map((m) => (
                <button key={m.id}
                  class={'model-row' + (m.id === props.modelId ? ' on' : '')}
                  disabled={props.busy}
                  onClick={() => props.onApply(providerOf(m.id), m.id, '')}>
                  <span class="model-row-name">{m.name || m.id}</span>
                  {m.id === props.modelId ? <span class="model-row-tag">当前</span> : null}
                </button>
              ))}
            </div>
          ))}
        </div>
        {efforts.length ? (
          <div class="field">
            <label>思考强度</label>
            <div class="seg">
              {efforts.map((x) => (
                <button key={x.id} class={localEffort === x.id ? 'on' : ''}
                  onClick={() => {
                    setLocalEffort(x.id);
                    props.onApply(providerOf(props.modelId), props.modelId, x.id);
                  }}>{x.name || x.id}</button>
              ))}
            </div>
          </div>
        ) : null}
        <div class="hint">点击模型立即对当前会话生效；「思考强度」跟随所选模型。</div>
      </div>
    </div>
  );
}

/* ────────────────────────── 主应用 ────────────────────────── */
export function App() {
  const s = useStore();
  const [drawer, setDrawer] = useState(false);
  const [settings, setSettings] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [pinReady, setPinReady] = useState(false);
  const stopStream = useRef<null | (() => void)>(null);
  const pollTimer = useRef(0);
  const [viewer, setViewer] = useState<{ path: string; name: string } | null>(null);
  const [queue, setQueue] = useState<{ text: string; images: string[]; files: string[] }[]>([]);
  const queueRef = useRef<{ text: string; images: string[]; files: string[] }[]>([]);
  queueRef.current = queue;
  /* 模型 / 强度（输入栏） */
  const [models, setModels] = useState<ModelsPayload | null>(null);
  const [modelOpen, setModelOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [pickToken, setPickToken] = useState(0);
  const [modelBusy, setModelBusy] = useState(false);
  const stateRef = useRef(s);
  stateRef.current = s;
  const prevRunning = useRef(false);

  /* 主题 */
  useEffect(() => {
    applyTheme(s.theme);
    applyBg();                       // 壁纸/底色跟着明暗主题重算
    const mq = matchMedia('(prefers-color-scheme: dark)');
    const fn = () => { if (state.theme === 'auto') applyTheme('auto'); applyBg(); };
    mq.addEventListener('change', fn);
    return () => mq.removeEventListener('change', fn);
  }, [s.theme]);

  /* 登录态：URL 里的 pin 优先 */
  const login = useCallback(async (pin: string) => {
    setPin(pin);
    await api.login(pin);
    const info = await api.info().catch(() => null);
    if (info && info.workdir) localStorage.setItem('console_workdir', info.workdir);
    // 壁纸以服务端为准（手机设的壁纸电脑端也能看到，反过来也一样）
    getBg().then((b) => {
      if (b && b.url) { writeBg({ url: b.url }); applyBg(); }
    }).catch(() => null);
    await refreshLists();
    set({ ready: true, view: 'list' });
    setPinReady(true);
  }, []);

  const refreshLists = useCallback(async () => {
    const [t, ses] = await Promise.all([
      api.threads().catch(() => ({ threads: [] })),
      api.sessions().catch(() => ({ sessions: [] })),
    ]);
    set({
      threads: t.threads || [],
      sessions: (ses.sessions || []).filter((x: any) => x.source === 'desktop'),
    });
  }, []);

  useEffect(() => {
    const q = new URLSearchParams(location.search).get('pin');
    // APK 壳里还带着「扫码/上次保存的 PIN」，即使 URL 没带也能自动登录
    let nativePin = '';
    try {
      const app = (window as any).PhoneConsole;
      if (app && typeof app.pin === 'function') nativePin = String(app.pin() || '');
    } catch (e) { nativePin = ''; }
    const pin = q || getPin() || nativePin;
    if (pin) { login(pin).catch(() => setPinReady(true)); }
    else setPinReady(true);
  }, []);

  /* 滚动：贴底时自动跟新消息；翻旧消息时不打断，底部弹「回到底部 / 新消息」 */
  const listRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const [jumpVisible, setJumpVisible] = useState(false);
  const [unread, setUnread] = useState(0);

  const scrollToBottom = useCallback((smooth = false) => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    atBottomRef.current = true;
    setJumpVisible(false);
    setUnread(0);
  }, []);

  const onChatScroll = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    const at = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    atBottomRef.current = at;
    setJumpVisible(!at);
    if (at) setUnread(0);
  }, []);

  /* 打开会话 */
  const open = useCallback(async (kind: 'thread' | 'session', id: string, title: string) => {
    stopStream.current?.();
    clearInterval(pollTimer.current);
    set({ active: { kind, id, title }, items: [], running: false, status: '', busy: false, view: 'chat' });
    atBottomRef.current = true;
    setJumpVisible(false);
    setUnread(0);
    setDrawer(false);
    requestAnimationFrame(() => scrollToBottom(false));
    const snap = await api.snapshot(kind, id).catch(() => null);
    if (snap) set({ items: withEcho(snap.items || []), running: !!snap.running, status: snap.status || '', plan: (snap as any).plan || null });
    stopStream.current = stream(kind, id, (ev) => {
      if (ev.type === 'session.snapshot') {
        set({ items: withEcho(ev.items || []), running: !!ev.session?.running, status: ev.session?.status || '' });
      } else if (ev.type === 'session.item' || ev.type === 'session.item_update') {
        const it = ev.item;
        if (!it) return;
        const items = state.items.slice();
        const i = items.findIndex((x) => x.id === it.id);
        if (i >= 0) items[i] = { ...items[i], ...it }; else items.push(it);
        set({ items });
      }
    });
    // 3 秒兜底轮询（与旧界面一致）
    pollTimer.current = window.setInterval(async () => {
      const d = await api.snapshot(kind, id).catch(() => null);
      if (!d) return;
      set({ running: !!d.running, status: d.status || '', items: withEcho(d.items || []), plan: (d as any).plan || null });
    }, 3000);
  }, []);

  /* 发送 / 停止 / 新建 */
  /* 真正发出去（不做繁忙判断） */
  const sendNow = useCallback(async (text: string, images: string[], files: string[]) => {
    const st0 = stateRef.current;
    if (!st0.active) return;
    const atts = images.map((p) => ({ name: baseName(p), path: p, image: true }))
      .concat(files.map((p) => ({ name: baseName(p), path: p, image: false })));
    const echo: Item = {
      id: 'local-' + Date.now(), kind: 'user', text, local: true,
      images, files, attachments: atts,
    };
    echoes.current = echoes.current.concat([echo]);
    set({ items: (st0.items || []).concat([echo]), busy: true });
    try {
      await api.send(st0.active.kind, st0.active.id, text, images, files);
      const d = await api.snapshot(st0.active.kind, st0.active.id).catch(() => null);
      if (d) set({ items: withEcho(d.items || []), running: !!d.running });
    } catch (e) {
      echoes.current = echoes.current.filter((x) => x.id !== echo.id);
      set({ items: (stateRef.current.items || []).filter((x) => x.id !== echo.id) });
      if ((e as any)?.status === 409) {
        setQueue((q) => q.concat([{ text, images, files }]));
        toast('当前回答还没结束，已排队', 'ok');
        return;
      }
      throw e;
    } finally { set({ busy: false }); }
  }, []);

  /* 对外 send：空闲直接发，繁忙进队列 */
  const send = useCallback(async (text: string, images: string[], files: string[]) => {
    const st0 = stateRef.current;
    if (!st0.active) return;
    if (st0.running) {
      setQueue((q) => q.concat([{ text, images, files }]));
      toast('已排队（' + (queueRef.current.length + 1) + ' 条），回答结束后自动发送', 'ok');
      return;
    }
    await sendNow(text, images, files);
  }, []);

  /* 插入：先中止当前回答，再立刻发出 */
  const sendInsert = useCallback(async (text: string, images: string[], files: string[]) => {
    const st0 = stateRef.current;
    if (!st0.active) return;
    try { await api.stop(st0.active.kind, st0.active.id); } catch (e) { /* 忽略 */ }
    await new Promise((r) => setTimeout(r, 250));
    await sendNow(text, images, files).catch((e) => toast('发送失败：' + (e as Error).message, 'err'));
  }, []);

  /* 插队：把队列里这条拎出来，立刻中止当前回答并发送 */
  const promoteQueue = useCallback(async (i: number) => {
    const item = queueRef.current[i];
    if (!item) return;
    setQueue((q) => q.filter((_, idx) => idx !== i));
    toast('插队发送中…', 'ok');
    await sendInsert(item.text, item.images, item.files);
  }, []);

  const dropQueue = useCallback((i: number) => {
    setQueue((q) => q.filter((_, idx) => idx !== i));
    toast('已取消排队', 'ok');
  }, []);

  /* 打开会话 → 拉模型目录（输入栏显示当前模型/强度） */
  useEffect(() => {
    const a = s.active;
    if (!a) { setModels(null); return; }
    getModels(a.kind, a.id).then(setModels).catch(() => null);
  }, [s.active?.kind, s.active?.id]);

  const modelGroups = models?.catalog?.groups || [];
  const allModelInfos = modelGroups.reduce<ModelInfo[]>((acc, g) => acc.concat(g.models || []), []);
  const curModelInfo = allModelInfos.find((m) => m.id === (models?.current?.model || ''));
  const curEfforts = curModelInfo?.reasoning?.efforts || [];
  const curEffortInfo = curEfforts.find((x) => x.id === (models?.current?.reasoningEffort || ''));

  const applyModelChoice = useCallback(async (provider: string, mid: string, eff: string) => {
    const a = stateRef.current.active;
    if (!a) { toast('先打开一段会话', 'err'); return; }
    setModelBusy(true);
    try {
      await setModel(a.kind, a.id, provider, mid, eff || undefined);
      toast('已切换：' + mid + (eff ? ' · ' + eff : ''), 'ok');
      const m = await getModels(a.kind, a.id).catch(() => null);
      if (m) setModels(m);
    } catch (e) {
      toast('切换失败：' + (e as Error).message, 'err');
    } finally { setModelBusy(false); }
  }, []);

  /* running 由 true → false：把队首消息发出去（队列空了就停） */
  useEffect(() => {
    const was = prevRunning.current;
    prevRunning.current = !!s.running;
    if (was && !s.running && queueRef.current.length) {
      const first = queueRef.current[0];
      setQueue((q) => q.slice(1));
      setTimeout(() => {
        sendNow(first.text, first.images, first.files)
          .catch((e) => toast('排队消息发送失败：' + (e as Error).message, 'err'));
      }, 150);
    }
  }, [s.running, s.active?.kind, s.active?.id]);

  const stop = useCallback(async () => {
    const st0 = stateRef.current;
    if (!st0.active) return;
    await api.stop(st0.active.kind, st0.active.id).catch(() => null);
    toast('已发送停止', 'ok');
    // 停止后排队的消息也照发（running 的 false 事件可能被 stop 吞掉）
    setTimeout(() => {
      if (!queueRef.current.length) return;
      const first = queueRef.current[0];
      setQueue((q) => q.slice(1));
      sendNow(first.text, first.images, first.files)
        .catch((e) => toast('排队消息发送失败：' + (e as Error).message, 'err'));
    }, 900);
  }, []);

  const createThread = useCallback(async (name: string, workdir: string) => {
    try {
      const r = await api.newThread(name, workdir);
      if (!r.thread) { toast(r.error || '创建失败', 'err'); return; }
      setNewOpen(false);
      await refreshLists();
      open('thread', r.thread.id, r.thread.name || name);
      toast('已创建：' + (r.thread.name || name), 'ok');
    } catch (e) { toast('创建失败：' + (e as Error).message, 'err'); }
  }, []);

  const upload = useCallback(async (f: File, onPct: (p: number) => void) => {
    if (!state.active) return null;
    const r = await uploadWithProgress(state.active.kind, state.active.id, f, onPct);
    return r ? { name: r.name || f.name, path: r.path, size: r.size || f.size } : null;
  }, []);

  // 本地回声：自己发的消息立刻显示，等服务端回传同一条后自动去掉
  const echoes = useRef<Item[]>([]);
  const withEcho = useCallback((items: Item[]) => {
    const serverUser = (items || []).filter((i) => (i.kind || '').toLowerCase() === 'user');
    // 服务端那条文本可能被追加了「图片已识别」等说明：displayText 或前缀匹配都算同一条
    echoes.current = echoes.current.filter((e) => !serverUser.some((s) =>
      (s.displayText || '') === (e.text || '') ||
      (!!e.text && (s.text || '') === (e.text || '')) ||
      (!!e.text && (s.text || '').indexOf(e.text) === 0)));
    return (items || []).concat(echoes.current);
  }, []);
  useEffect(() => {
    if (state.view !== 'chat') return;
    const el = listRef.current;
    if (!el) return;
    if (atBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    } else {
      setUnread((n) => n + 1);
    }
  }, [s.items.length, s.view]);

  if (!pinReady) return <div class="boot">正在连接…</div>;
  if (!s.ready) return <Login onSubmit={login} />;

  const title = s.active?.title || '会话';
  return (
    <div class="app">
      <TopBar title={title} running={s.running} status={s.status}
        onMenu={() => setDrawer(true)} onNew={() => setNewOpen(true)} onSettings={() => setSettings(true)} />
      <main class="chat" ref={listRef} onScroll={onChatScroll}>
        {s.view === 'list' || !s.active ? (
          <div class="empty">
            <div class="empty-mark">⌘</div>
            <p>选择一个会话，或新建一个开始</p>
            <button class="outline-btn" onClick={() => setDrawer(true)}>打开会话列表</button>
          </div>
        ) : (
          <div class="chat-inner">
            {s.items.length === 0 ? <div class="empty small"><p>还没有消息，发一条试试</p></div> : null}
            {s.items.map((it) => (
              <MessageBlock key={it.id} item={it} onOpenImage={(p, n) => setViewer({ path: p, name: n })} />
            ))}
          </div>
        )}
      </main>
      {jumpVisible ? (
        <button class="jump" onClick={() => scrollToBottom(true)}>
          {unread > 0 ? '新消息 ' + unread : '回到底部'}
        </button>
      ) : null}
      <PlanBar plan={s.plan} />
      <Composer disabled={!s.active} running={s.running} onSend={send} onStop={stop} upload={upload}
        modelName={allModelInfos.find((m) => m.id === (models?.current?.model || ''))?.name
          || models?.current?.model || ''}
        effortName={curEffortInfo?.name || models?.current?.reasoningEffort || ''}
        onOpenModel={() => setModelOpen(true)}
        queue={queue} onDropQueue={dropQueue} onInsert={sendInsert} onPromoteQueue={promoteQueue}
        onCommands={() => setCmdOpen(true)} pickToken={pickToken} />
      <CommandSheet open={cmdOpen} onClose={() => setCmdOpen(false)} plan={s.plan} active={s.active}
        onFile={() => setPickToken(Date.now())}
        onModel={() => setModelOpen(true)}
        onExport={() => {
          const data = { at: new Date().toISOString(), active: s.active, plan: s.plan, items: s.items };
          const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = 'phone-console-' + (s.active ? s.active.id.slice(0, 8) : 'export') + '.json';
          a.click();
          setTimeout(() => URL.revokeObjectURL(a.href), 3000);
        }} />
      <Drawer open={drawer} onClose={() => setDrawer(false)} onPick={open}
        onNew={() => { setDrawer(false); setNewOpen(true); }}
        active={s.active ? s.active.kind + ':' + s.active.id : null} />
      <Settings open={settings} onClose={() => setSettings(false)} active={s.active} />
      <ModelSheet open={modelOpen} onClose={() => setModelOpen(false)} models={models}
        modelId={models?.current?.model || ''} effort={models?.current?.reasoningEffort || ''}
        onApply={applyModelChoice} busy={modelBusy} />
      <NewThread open={newOpen} onClose={() => setNewOpen(false)} onCreate={createThread} />
      {viewer ? <ImageViewer path={viewer.path} name={viewer.name} onClose={() => setViewer(null)} /> : null}
      {s.toast ? <div class={'toast ' + s.toast.kind}>{s.toast.text}</div> : null}
    </div>
  );
}
