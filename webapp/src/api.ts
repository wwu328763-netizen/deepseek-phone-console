/* 手机远程控制台 · API 客户端（TypeScript）
   契约与旧页面一致：头 X-Console-Pin、SSE /api/(threads|sessions)/{id}/stream */
export interface Thread { id: string; name: string; workdir?: string; created_at?: string; running?: boolean }
export interface Session { id: string; name?: string; cwd?: string; updated?: string; running?: boolean; source?: string }
export interface Att { name: string; path: string; image?: boolean }
export interface Item {
  id: string; kind: string; text?: string; output?: string; args?: string;
  command?: string; name?: string; error?: string;
  status?: string; stream?: boolean; ts?: number; at?: number;
  questions?: { id: string; question?: string; options?: { label: string }[] }[];
  sessionId?: string; rpc_id?: string;
  images?: string[]; files?: string[]; attachments?: Att[]; displayText?: string;
  local?: boolean;
}
export interface Snap { running: boolean; status?: string; items: Item[] }

const PIN_KEY = 'console_pin';

export function getPin(): string { return localStorage.getItem(PIN_KEY) || ''; }
export function setPin(p: string): void { localStorage.setItem(PIN_KEY, p); }

export class ApiError extends Error {
  status: number;
  constructor(msg: string, status = 0) { super(msg); this.status = status; }
}

async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const pin = getPin();
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> || {}) };
  if (pin) headers['X-Console-Pin'] = pin;
  if (init.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) throw new ApiError('PIN 不对或已过期', 401);
  if (!res.ok) throw new ApiError('HTTP ' + res.status, res.status);
  return res;
}

export async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await raw(path, init);
  return await res.json() as T;
}

export const api = {
  login: (pin: string) => json<{ ok: boolean }>('/api/login', { method: 'POST', body: JSON.stringify({ pin }) }),
  info: () => json<any>('/api/info'),
  threads: () => json<{ threads: Thread[] }>('/api/threads'),
  sessions: () => json<{ sessions: Session[] }>('/api/sessions'),
  snapshot: (kind: 'thread' | 'session', id: string) =>
    json<Snap>(kind === 'thread' ? `/api/threads/${id}` : `/api/sessions/${id}`),
  send: (kind: 'thread' | 'session', id: string, prompt: string, images: string[] = [], files: string[] = []) =>
    json<{ ok: boolean; msg?: string }>(`/api/${kind === 'thread' ? 'threads' : 'sessions'}/${id}/send`,
      { method: 'POST', body: JSON.stringify({ prompt, images, files }) }),
  stop: (kind: 'thread' | 'session', id: string) =>
    json<{ ok: boolean }>(`/api/${kind === 'thread' ? 'threads' : 'sessions'}/${id}/stop`, { method: 'POST' }),
  // 服务端返回 201 {thread} 或 5xx {error}，没有 ok 字段
  newThread: (name: string, workdir: string, prompt = '') =>
    json<{ thread?: Thread; error?: string }>('/api/threads',
      { method: 'POST', body: JSON.stringify({ name, workdir, prompt }) }),
  usage: () => json<any>('/api/usage'),
  upload: async (kind: 'thread' | 'session', id: string, file: File): Promise<{ path: string } | null> => {
    const res = await raw(`/api/${kind === 'thread' ? 'threads' : 'sessions'}/${id}/upload`, {
      method: 'POST',
      headers: { 'X-Filename': encodeURIComponent(file.name) },
      body: file,
    });
    return await res.json() as { path: string };
  },
};

/** SSE 订阅：返回取消函数 */
export function stream(kind: 'thread' | 'session', id: string,
  onEvent: (ev: { type: string; session?: any; items?: Item[]; item?: Item }) => void,
  onDown?: (err: unknown) => void): () => void {
  const ctrl = new AbortController();
  (async () => {
    try {
      const res = await raw(`/api/${kind === 'thread' ? 'threads' : 'sessions'}/${id}/stream`,
        { signal: ctrl.signal });
      if (!res.body) return;
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i: number;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const block = buf.slice(0, i).trim();
          buf = buf.slice(i + 2);
          if (!block.startsWith('data: ')) continue;
          try { onEvent(JSON.parse(block.slice(6))); } catch { /* 忽略坏帧 */ }
        }
      }
    } catch (e) {
      if ((e as any)?.name !== 'AbortError') onDown?.(e);
    }
  })();
  return () => ctrl.abort();
}

/* ---- 原始文件（图片缩略图 / 下载） ----
   /api/raw 要 X-Console-Pin 头，不能直接塞进 <img src>，所以统一 fetch 成 blob URL；
   同一个 path 只拉一次（上传的图通常 1~3MB，翻聊天记录时不该反复下载）。 */
const blobCache = new Map<string, string>();

export function cachedBlobUrl(path: string): string | null {
  return blobCache.get(String(path || '')) || null;
}

export async function blobUrl(path: string): Promise<string> {
  const key = String(path || '');
  const hit = blobCache.get(key);
  if (hit) return hit;
  const res = await raw('/api/raw?path=' + encodeURIComponent(key));
  const url = URL.createObjectURL(await res.blob());
  blobCache.set(key, url);
  return url;
}

export async function downloadRaw(path: string, name: string): Promise<void> {
  const res = await raw('/api/raw?path=' + encodeURIComponent(path));
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = name || 'file';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/* ---- 聊天背景：与旧版共用服务端的 /api/bg（url 是压缩后的 dataURL） ---- */
export interface BgPayload { url?: string; alpha?: number }
export async function getBg(): Promise<BgPayload> { return json<BgPayload>('/api/bg'); }
export async function saveBg(patch: BgPayload) {
  return json<{ ok?: boolean }>('/api/bg', { method: 'POST', body: JSON.stringify(patch) });
}

/* ---- 设置 / 问答 / 文件浏览 ---- */
export interface ModelInfo { id: string; name: string; reasoning?: { efforts: { id: string; name: string; description?: string }[] } }
export interface ModelGroup { id: string; name: string; models: ModelInfo[] }
export interface ModelsPayload {
  catalog: { groups: ModelGroup[]; routableProviders?: string[]; default?: any };
  current: { provider?: string; model?: string; reasoningEffort?: string };
  canSwitch?: boolean;
}
export interface DirEntry { name: string; dir: boolean; size?: number | null; mtime?: number }
export interface FilesPayload { path: string; root: string; can_up: boolean; entries: DirEntry[] }

export async function getModels(kind: string, id: string): Promise<ModelsPayload | null> {
  return json<ModelsPayload>('/api/models?kind=' + encodeURIComponent(kind) + '&id=' + encodeURIComponent(id));
}
export async function setModel(kind: string, id: string, provider: string, model: string, effort?: string) {
  return json<any>('/api/model', {
    method: 'POST',
    body: JSON.stringify({ kind, id, provider, model, reasoningEffort: effort || undefined }),
  });
}
export async function answerQuestion(sessionId: string, rpcId: string,
  answers: { id: string; selected: string[]; custom?: string }[]) {
  return json<any>('/api/answer', { method: 'POST', body: JSON.stringify({ sessionId, rpcId, answers }) });
}
export async function getUsage() { return json<any>('/api/usage'); }
export async function getBalance() { return json<any>('/api/balance'); }
export async function listFiles(path: string) {
  return json<FilesPayload>('/api/files?path=' + encodeURIComponent(path || ''));
}
export async function makeDir(path: string) {
  return json<any>('/api/fs/mkdir', { method: 'POST', body: JSON.stringify({ path }) });
}
export interface InfoPayload {
  workdir_root?: string;
  phone_workspace?: string | null;
  dsh_connected?: boolean;
  port?: number;
}
export async function getInfo() { return json<InfoPayload>('/api/info'); }

/** 带进度的上传（XHR；fetch 拿不到上传进度） */
/* 上传兜底：60 秒没结果就失败，避免界面"卡死"（大文件走隧道时服务器/网络可能不回应） */
export const UPLOAD_TIMEOUT_MS = 60000;

export function uploadWithProgress(
  kind: 'thread' | 'session', id: string, file: File,
  onPct: (p: number) => void,
): Promise<{ name: string; path: string; size?: number } | null> {
  return new Promise((resolve, reject) => {
    let xhr: XMLHttpRequest;
    try { xhr = new XMLHttpRequest(); } catch { reject(new Error('当前环境不支持上传')); return; }
    xhr.open('POST', `/api/${kind === 'thread' ? 'threads' : 'sessions'}/${id}/upload`, true);
    xhr.timeout = 120000;
    xhr.setRequestHeader('X-Console-Pin', getPin());
    xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name));
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');

    /* 进度兜底：WebView 里 upload 进度事件有时不触发，这时自己跑一个"假进度"
       （爬到 90% 停住，真实进度来了就被覆盖），至少让用户看到在上传而不是卡死。 */
    let real = 0;
    let fake = 0;
    const fakeTimer = setInterval(() => {
      if (real > 0) return;
      fake = Math.min(0.9, fake + (fake < 0.6 ? 0.08 : 0.02));
      onPct(fake);
    }, 320);

    const cleanup = () => clearInterval(fakeTimer);

    if (xhr.upload) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && e.total > 0) {
          real = Math.min(1, e.loaded / e.total);
          onPct(real);
        }
      };
    }
    xhr.onload = () => {
      cleanup();
      try {
        const j = JSON.parse(xhr.responseText || '{}');
        if (xhr.status >= 200 && xhr.status < 300) { onPct(1); resolve(j); }
        else reject(new Error(j.error || ('HTTP ' + xhr.status)));
      } catch (e) { reject(e as Error); }
    };
    xhr.onerror = () => { cleanup(); reject(new Error('网络错误（上传中断）')); };
    xhr.onabort = () => { cleanup(); reject(new Error('已取消上传')); };
    xhr.ontimeout = () => { cleanup(); reject(new Error('上传超时（120s），建议换小文件或换网络')); };
    try {
      xhr.send(file);
    } catch (e) {
      cleanup(); reject(e as Error); return;
    }
    // 暴露给调用方可取消
    (file as any).__abortUpload = () => xhr.abort();
  });
}



/* ---- 手机端归档 ---- */
export async function getArchived(): Promise<{ thread: string[]; session: string[] }> {
  return json<{ thread: string[]; session: string[] }>('/api/archived');
}

export async function setArchived(kind: 'thread' | 'session', id: string, archived: boolean) {
  return json<{ ok: boolean; archived: string[] }>('/api/archive', {
    method: 'POST',
    body: JSON.stringify({ kind, id, archived }),
  });
}
