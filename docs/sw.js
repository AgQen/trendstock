// Service Worker — network-first for HTML/JSON (즉시 갱신 보장),
// 정적 리소스(icon, manifest)만 캐시 우선.
const CACHE = "trendstock-v3";   // UI 큰 변경 시 bump
const STATIC_ASSETS = ["./manifest.json", "./icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = e.request.url;
  // index.html / data JSON 은 network-first (새 배포 즉시 반영)
  const networkFirst =
    e.request.mode === "navigate" ||
    url.endsWith("/") || url.endsWith("index.html") ||
    url.includes("/data/analysis.json");

  if (networkFirst) {
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          const clone = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, clone));
          return r;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }
  // 그 외 정적 자원은 캐시 우선
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
