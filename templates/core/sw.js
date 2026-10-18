/* TOMONI Beauty service worker: 静的ファイルはキャッシュを返しつつ裏で更新、ページはネットワーク優先 */
const CACHE = "tomoni-{{ version }}";
const PRECACHE = ["/static/css/app.css", "/static/js/app.js", "/static/js/recorder.js", "/offline/", "/static/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE).catch(() => null)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/static/")) {
    // stale-while-revalidate: 手元のキャッシュをすぐ返し、裏で新しいものを取りに行く（次の表示から新しくなる）
    event.respondWith(
      caches.open(CACHE).then(async (c) => {
        const hit = await c.match(req);
        const refresh = fetch(req).then((res) => { if (res && res.ok) c.put(req, res.clone()); return res; }).catch(() => hit);
        return hit || refresh;
      })
    );
    return;
  }
  if (url.pathname.startsWith("/media/") || url.pathname.startsWith("/admin/")) return;

  event.respondWith(
    fetch(req).catch(() => caches.match(req).then((hit) => hit || caches.match("/offline/")))
  );
});
