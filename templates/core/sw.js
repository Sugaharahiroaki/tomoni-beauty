/* TOMONI Beauty service worker: 静的ファイルはキャッシュ、ページはネットワーク優先 */
const CACHE = "tomoni-v1";
const PRECACHE = ["/static/css/app.css", "/static/js/app.js", "/static/js/recorder.js", "/offline/", "/static/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
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
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return res;
      }))
    );
    return;
  }
  if (url.pathname.startsWith("/media/") || url.pathname.startsWith("/admin/")) return;

  event.respondWith(
    fetch(req).catch(() => caches.match(req).then((hit) => hit || caches.match("/offline/")))
  );
});
