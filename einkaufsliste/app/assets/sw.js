const SHELL_CACHE = "eigene-einkaufsliste-shell-0.3.69";
const IMAGE_CACHE = "eigene-einkaufsliste-images-v1";
const BASE = new URL("./", self.location.href);
const INDEX_URL = new URL("index.html", BASE).href;
const SHELL_PATHS = [
  "index.html",
  "manifest.webmanifest",
  "apple-touch-icon.png",
  "apple-touch-icon-precomposed.png",
  "favicon-64.png",
  "icon-192.png",
  "icon-512.png",
  "icon-1024.png"
];
const SHELL = SHELL_PATHS.map((item) => new URL(item, BASE).href);

function isImagePath(relativePath) {
  return relativePath.startsWith("product-images/") ||
    relativePath.startsWith("category-images/") ||
    relativePath.startsWith("generated-product-images/") ||
    relativePath.startsWith("generated-category-images/");
}

function imageCacheKey(input) {
  const url = input instanceof URL ? input : new URL(typeof input === "string" ? input : input.url);
  // Bildrevisionen dürfen den persistenten Cache nicht mit alten ?v=-Varianten füllen.
  // Pro Bildpfad bleibt immer nur die zuletzt erfolgreich geladene Variante erhalten.
  return new Request(url.origin + url.pathname, { method: "GET" });
}

async function cacheImage(request, response) {
  if (!response || !response.ok) return false;
  const cache = await caches.open(IMAGE_CACHE);
  await cache.put(imageCacheKey(request), response.clone());
  return true;
}

async function warmImageUrls(urls) {
  const cache = await caches.open(IMAGE_CACHE);
  let cached = 0;
  for (const raw of urls) {
    try {
      const url = new URL(raw, BASE);
      if (url.origin !== self.location.origin) continue;
      const basePath = BASE.pathname.endsWith("/") ? BASE.pathname : BASE.pathname + "/";
      if (!url.pathname.startsWith(basePath)) continue;
      const relativePath = url.pathname.slice(basePath.length);
      if (!isImagePath(relativePath)) continue;
      const response = await fetch(url.href);
      if (response && response.ok) {
        await cache.put(imageCacheKey(url), response.clone());
        cached += 1;
      }
    } catch (_) {
      // Einzelne Bilder dürfen die übrige Offline-Vorbereitung nicht blockieren.
    }
  }
  return cached;
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    // Die Startseite ist für den Offline-Start zwingend. Zusätzliche Shell-Dateien
    // werden best-effort gespeichert, damit ein einzelnes Icon den Worker nicht blockiert.
    await cache.add(new Request(INDEX_URL, { cache: "reload" }));
    await Promise.allSettled(
      SHELL.filter((url) => url !== INDEX_URL)
        .map((url) => cache.add(new Request(url, { cache: "reload" })))
    );
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    const oldShells = names.filter((name) => name.startsWith("eigene-einkaufsliste-shell-") && name !== SHELL_CACHE);
    const imageCache = await caches.open(IMAGE_CACHE);
    // Beim ersten Update auf den getrennten Bildcache werden bereits vorhandene
    // Produkt-/Kategorie-Bilder aus alten Shell-Caches übernommen, bevor diese
    // gelöscht werden. Dadurch geht der bestehende Offline-Bildbestand nicht verloren.
    for (const name of oldShells) {
      try {
        const oldCache = await caches.open(name);
        const keys = await oldCache.keys();
        for (const request of keys) {
          const url = new URL(request.url);
          const basePath = BASE.pathname.endsWith("/") ? BASE.pathname : BASE.pathname + "/";
          if (!url.pathname.startsWith(basePath)) continue;
          const relativePath = url.pathname.slice(basePath.length);
          if (!isImagePath(relativePath)) continue;
          const response = await oldCache.match(request);
          if (response && response.ok) await imageCache.put(imageCacheKey(url), response.clone());
        }
      } catch (_) {}
      await caches.delete(name);
    }
    // IMAGE_CACHE wird absichtlich NICHT gelöscht: Produkt- und Kategorie-Bilder
    // bleiben damit auch über weitere App-Updates hinweg offline verfügbar.
    await self.clients.claim();
  })());
});

self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type !== "cache-images") return;
  const urls = Array.isArray(data.urls) ? data.urls.slice(0, 500) : [];
  event.waitUntil((async () => {
    const count = await warmImageUrls(urls);
    try { event.source?.postMessage({ type: "offline-images-ready", count }); } catch (_) {}
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  const basePath = BASE.pathname.endsWith("/") ? BASE.pathname : BASE.pathname + "/";
  if (!url.pathname.startsWith(basePath)) return;

  const relativePath = url.pathname.slice(basePath.length);
  if (relativePath.startsWith("api/")) return;

  if (request.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const response = await fetch(request);
        if (response && response.ok) {
          const cache = await caches.open(SHELL_CACHE);
          await cache.put(INDEX_URL, response.clone());
        }
        return response;
      } catch (_) {
        const cache = await caches.open(SHELL_CACHE);
        const cached = await cache.match(INDEX_URL, { ignoreSearch: true });
        if (cached) return cached;
        return new Response(
          "Offline-App wurde noch nicht vollständig vorbereitet. Bitte einmal mit Verbindung öffnen.",
          { status: 503, headers: { "content-type": "text/plain; charset=utf-8" } }
        );
      }
    })());
    return;
  }

  if (isImagePath(relativePath)) {
    event.respondWith((async () => {
      const key = imageCacheKey(url);
      try {
        const response = await fetch(request, { cache: "no-cache" });
        if (response && response.ok) {
          await cacheImage(request, response);
          return response;
        }
        const cache = await caches.open(IMAGE_CACHE);
        const cached = await cache.match(key);
        return cached || response;
      } catch (_) {
        const cache = await caches.open(IMAGE_CACHE);
        const cached = await cache.match(key);
        if (cached) return cached;
        return new Response("", { status: 504 });
      }
    })());
    return;
  }

  if (SHELL.includes(url.href)) {
    event.respondWith((async () => {
      const cache = await caches.open(SHELL_CACHE);
      const cached = await cache.match(request, { ignoreSearch: true });
      if (cached) return cached;
      try {
        const response = await fetch(request);
        if (response && response.ok) await cache.put(request, response.clone());
        return response;
      } catch (_) {
        return new Response("", { status: 504 });
      }
    })());
  }
});
