const CACHE_NAME = 'comet-static-cache-v1';
const STATIC_ASSETS = [
    '/', // Cache the root page (index.html)
    '/static/style.css',
    '/static/script.js',
    'https://cdn.jsdelivr.net/npm/marked/marked.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css'
    // Add paths to your actual icons here if you want them cached, e.g.:
    // '/static/icons/icon-192x192.png',
    // '/static/icons/icon-512x512.png',
    // Add your favicon if it's a static file and not a data URI
];

self.addEventListener('install', event => {
    console.log('[Service Worker] Installing...');
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('[Service Worker] Pre-caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .catch(error => {
                console.error('[Service Worker] Failed to cache static assets:', error);
            })
    );
    self.skipWaiting(); // Activate new service worker immediately
});

self.addEventListener('activate', event => {
    console.log('[Service Worker] Activating...');
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('[Service Worker] Clearing old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
    return self.clients.claim(); // Take control of all open clients
});

self.addEventListener('fetch', event => {
    // For GET requests, try to serve from cache, then network, then cache errors.
    if (event.request.method === 'GET') {
        // For navigation requests (HTML pages), try network first to get fresh content,
        // then fall back to cache. For other assets, cache-first is often preferred.
        if (event.request.mode === 'navigate') {
            event.respondWith(
                fetch(event.request)
                    .then(response => {
                        // If network fetch is successful, cache the new response (optional for navigate)
                        // Be careful caching all navigation responses as they might be dynamic
                        return response;
                    })
                    .catch(() => {
                        // Fallback to cache if network fails
                        return caches.match(event.request)
                            .then(cachedResponse => {
                                return cachedResponse || caches.match('/'); // Fallback to root if specific page not cached
                            });
                    })
            );
        } else if (STATIC_ASSETS.includes(new URL(event.request.url).pathname) || event.request.url.startsWith('https')) {
             // Cache-first for known static assets and CDN resources
            event.respondWith(
                caches.match(event.request)
                    .then(cachedResponse => {
                        if (cachedResponse) {
                            // console.log('[Service Worker] Serving from cache:', event.request.url);
                            return cachedResponse;
                        }
                        // console.log('[Service Worker] Fetching from network:', event.request.url);
                        return fetch(event.request).then(networkResponse => {
                            // Optionally, cache new static assets dynamically if not in initial list
                            // Be careful with caching opaque responses (from CDNs without CORS)
                            if (networkResponse && networkResponse.status === 200 && networkResponse.type !== 'opaque') {
                                const responseToCache = networkResponse.clone();
                                caches.open(CACHE_NAME)
                                    .then(cache => {
                                        cache.put(event.request, responseToCache);
                                    });
                            }
                            return networkResponse;
                        });
                    })
            );
        } else {
            // For other GET requests (e.g., API calls like /search), just fetch from network.
            // Do not cache API calls by default as they are dynamic.
            event.respondWith(fetch(event.request));
        }
    }
}); 