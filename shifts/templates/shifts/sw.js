const CACHE_NAME = 'shiftflow-cache-v1';
const ASSETS_TO_CACHE = [
  '/static/css/style.css',
  '/static/images/icon-192.png',
  '/static/images/icon-512.png',
];

// インストール時に静的ファイルをキャッシュ
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
  self.skipWaiting();
});

// 古いキャッシュのクリーンアップ
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cache => {
          if (cache !== CACHE_NAME) {
            return caches.delete(cache);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// リクエストの処理
self.addEventListener('fetch', event => {
  // ブラウザの拡張機能や非HTTP/HTTPSリクエストを除外
  if (!event.request.url.startsWith(self.location.origin)) return;

  event.respondWith(
    caches.match(event.request).then(cachedResponse => {
      if (cachedResponse) {
        return cachedResponse;
      }
      
      return fetch(event.request).then(response => {
        // レスポンスが正常かつ静的ファイルである場合はキャッシュに追加
        if (response && response.status === 200 && event.request.url.includes('/static/')) {
          const responseToCache = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, responseToCache);
          });
        }
        return response;
      }).catch(() => {
        // オフライン時の代替表示などを行う場合はここに追加
      });
    })
  );
});
