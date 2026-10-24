/* Phone console service worker: caches the app shell, never API responses. */
const CACHE = "phone-console-v64";
const SHELL = [
  "/",
  "/legacy",
  "/app/app.js",
  "/app/app.css",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // never cache API traffic

  const isShell = ["/", "/index.html", "/app", "/app/", "/legacy"].includes(url.pathname);
  // /app/* 是每次构建都会变的资源：必须 network-first，否则装了 PWA 后永远用旧 app.js
  const isAppAsset = url.pathname.startsWith("/app/");
  if (isShell || isAppAsset) {
    // network-first so UI updates show immediately; fall back to cache offline
    event.respondWith(
      fetch(event.request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
          return resp;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((hit) => {
      const fetched = fetch(event.request).then((resp) => {
        if (resp.ok && (url.pathname.startsWith("/icons/") || url.pathname.startsWith("/app/") || ["/", "/index.html", "/app", "/app/", "/legacy", "/manifest.webmanifest"].includes(url.pathname))) {
          const copy = resp.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return resp;
      }).catch(() => hit);
      return hit || fetched;
    })
  );
});
