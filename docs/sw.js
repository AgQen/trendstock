// 최소 Service Worker — 오프라인 캐시 + "홈 화면에 추가" 가능하게.
const CACHE = "trendstock-v1";
const ASSETS = ["./", "./index.html", "./manifest.json", "./icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
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
  // data/analysis.json 은 항상 네트워크 우선 (새 데이터 표시 보장)
  if (e.request.url.includes("/data/analysis.json")) {
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
  // 정적 자원은 캐시 우선
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
