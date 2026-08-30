const CACHE_NAME = "webpatch-cache-v7";
const FILES_TO_CACHE = [
    "index.html",
    "index.pd",
    "pd4web.js",
    "vexflow.js",
    "pd4web.threads.js",
    "pd4web.wasm",
    "pd4web.data",
    "icon-192.png",
    "icon-512.png",
];

// ─────────────────────────────────────
self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return Promise.all(
                FILES_TO_CACHE.map((file) =>
                    cache.add(file).catch((err) => {
                        console.error("Failed to cache:", file, err);
                    }),
                ),
            );
        }),
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
            .then(() => self.clients.claim()),
    );
});

// ─────────────────────────────────────
self.addEventListener("fetch", (event) => {
    event.respondWith(caches.match(event.request).then((response) => response || fetch(event.request)));
});
