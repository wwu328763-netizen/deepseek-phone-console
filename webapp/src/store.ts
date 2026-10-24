/* 轻量响应式 store：不用外部状态库，组件通过 useStore 订阅 */
import { useEffect, useState } from 'preact/hooks';
import type { Item, Session, Thread } from './api';

export type Theme = 'dark' | 'light' | 'auto';
export type View = 'chat' | 'list';

export interface State {
  ready: boolean;            // 已登录且 info 拉取完成
  theme: Theme;
  view: View;
  threads: Thread[];
  sessions: Session[];
  active: { kind: 'thread' | 'session'; id: string; title: string } | null;
  items: Item[];
  plan: any;          // DSH 的计划/目标（输入框上方镜像）
  running: boolean;
  status: string;
  busy: boolean;             // 发送中/等待首帧
  error: string;
  toast: { text: string; kind: 'ok' | 'err' } | null;
}

const THEME_KEY = 'console_theme_v2';

function initialTheme(): Theme {
  const v = localStorage.getItem(THEME_KEY) as Theme | null;
  return v === 'light' || v === 'dark' || v === 'auto' ? v : 'auto';
}

export const state: State = {
  ready: false,
  theme: initialTheme(),
  view: 'list',
  threads: [],
  sessions: [],
  active: null,
  items: [],
  plan: null,
  running: false,
  status: '',
  busy: false,
  error: '',
  toast: null,
};

type Listener = () => void;
const listeners = new Set<Listener>();
let raf = 0;

export function set(patch: Partial<State>): void {
  Object.assign(state, patch);
  if (!raf) {
    raf = requestAnimationFrame(() => {
      raf = 0;
      listeners.forEach((l) => l());
    });
  }
}
export function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

export function useStore(): State {
  const [, force] = useState(0);
  useEffect(() => subscribe(() => force((n) => n + 1)), []);
  return state;
}

export function applyTheme(theme: Theme = state.theme): void {
  localStorage.setItem(THEME_KEY, theme);
  const dark = theme === 'dark' || (theme === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', dark ? '#0B0B0C' : '#FFFFFF');
  if (theme !== state.theme) set({ theme });
}

let toastTimer = 0;
export function toast(text: string, kind: 'ok' | 'err' = 'ok'): void {
  set({ toast: { text, kind } });
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => set({ toast: null }), 2600);
}

export function relativeTime(iso?: string): string {
  if (!iso) return '';
  const t = new Date(String(iso).replace(' ', 'T')).getTime();
  if (!isFinite(t)) return '';
  const d = Math.max(0, Date.now() - t) / 1000;
  if (d < 60) return '刚刚';
  if (d < 3600) return Math.floor(d / 60) + '分钟';
  if (d < 86400) return Math.floor(d / 3600) + '小时';
  if (d < 86400 * 30) return Math.floor(d / 86400) + '天';
  const dt = new Date(t);
  return (dt.getMonth() + 1) + '-' + dt.getDate();
}

/* ───────────── 聊天背景：壁纸 + 底色深浅 ─────────────
   壁纸沿用旧版的 `console_bg`（压缩后的 dataURL），所以两个界面设的壁纸互通；
   「遮罩」「底色深浅」是 v2 自己的语义（旧版的 console_bg_alpha 调的是气泡透明度），
   单独用 v2 的 key，避免两个界面的滑块互相打架。 */
export interface BgState { url: string; veil: number; shade: number }

const BG_URL_KEY = 'console_bg';
const BG_VEIL_KEY = 'console_bg_v2_veil';
const BG_SHADE_KEY = 'console_bg_v2_shade';

function clampNum(raw: string | null, lo: number, hi: number, dflt: number): number {
  const n = parseInt(raw || '', 10);
  if (!isFinite(n)) return dflt;
  return Math.max(lo, Math.min(hi, n));
}

export function readBg(): BgState {
  return {
    url: localStorage.getItem(BG_URL_KEY) || '',
    veil: clampNum(localStorage.getItem(BG_VEIL_KEY), 0, 100, 72),
    shade: clampNum(localStorage.getItem(BG_SHADE_KEY), 0, 30, 0),
  };
}

export function writeBg(patch: Partial<BgState>): void {
  if (patch.url !== undefined) {
    if (patch.url) localStorage.setItem(BG_URL_KEY, patch.url);
    else localStorage.removeItem(BG_URL_KEY);
  }
  if (patch.veil !== undefined) localStorage.setItem(BG_VEIL_KEY, String(patch.veil));
  if (patch.shade !== undefined) localStorage.setItem(BG_SHADE_KEY, String(patch.shade));
}

/** 把壁纸/底色写进 CSS 变量；主题切换后要重跑（灰度跟着深浅和深浅主题走）。 */
export function applyBg(bg: BgState = readBg()): void {
  const dark = document.documentElement.dataset.theme === 'dark';
  const g = dark ? Math.round(20 + bg.shade * 1.2) : Math.round(255 * (1 - bg.shade / 100));
  const root = document.documentElement.style;
  root.setProperty('--base-rgb', g + ',' + g + ',' + g);
  if (bg.url) {
    root.setProperty('--bg-image', 'url("' + bg.url + '")');
    root.setProperty('--chat-veil', (bg.veil / 100).toFixed(3));
  } else {
    root.setProperty('--bg-image', 'none');
    // 没壁纸时「底色深浅」就是一层很淡的同色蒙层（和旧版一样用 8%）
    root.setProperty('--chat-veil', bg.shade > 0 ? '0.08' : '0');
  }
}

/* ───────────── 复制到剪贴板（http 局域网下没有 clipboard API，退回 execCommand） ───────────── */
export async function copyText(text: string): Promise<boolean> {
  const t = String(text || '');
  if (!t) return false;
  try {
    await navigator.clipboard.writeText(t);
    return true;
  } catch { /* 非 https / 无权限，走下面的兜底 */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = t;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, t.length);
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}
