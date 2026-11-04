// The console's service worker (#2097): Web Push, and the console's own code.
//
// A push carries a title, a body, a console path and a tag; a click opens that
// path in a console tab, or focuses one.
//
// The code is kept so an app opened without a network still opens the console,
// which then reads its sealed copy on the device (`lib/offline`). Only code:
// the hashed scripts and styles Next.js builds, kept on first use, and the HTML
// of each page, kept on every load that succeeds and served only when the
// network fails. No page renders anything per person on the server, so nobody's
// conversations are in this cache - they are sealed in IndexedDB. A page served
// from here repeats the script nonce it was first served with; offline there is
// nothing but that page and the device's own copy for it to run beside.

const CODE = "agenticos-code-v1";
/** Old builds' chunks are never asked for again; the oldest go past this. */
const MAX_ENTRIES = 400;

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(names.filter((name) => name !== CODE).map((name) => caches.delete(name))),
      )
      .then(() => self.clients.claim()),
  );
});

async function trim(cache) {
  const keys = await cache.keys();
  await Promise.all(
    keys.slice(0, Math.max(0, keys.length - MAX_ENTRIES)).map((key) => cache.delete(key)),
  );
}

async function keep(request, response) {
  const cache = await caches.open(CODE);
  await cache.put(request, response);
  await trim(cache);
}

/** A built chunk never changes under its name: the network only the first time. */
async function chunk(event) {
  const kept = await caches.match(event.request);
  if (kept) return kept;
  const response = await fetch(event.request);
  // A production build marks its chunks immutable; `next dev` serves the same
  // names with new code on every edit, and keeping those would freeze them.
  if (response.ok && /immutable/.test(response.headers.get("Cache-Control") || "")) {
    event.waitUntil(keep(event.request, response.clone()));
  }
  return response;
}

/** A page from the network whenever there is one; the copy only when there is not. */
async function page(event) {
  const url = new URL(event.request.url);
  const key = url.origin + url.pathname;
  try {
    const response = await fetch(event.request);
    if (response.ok && !response.redirected && response.type === "basic") {
      event.waitUntil(keep(key, response.clone()));
    }
    return response;
  } catch (error) {
    const kept = await caches.match(key);
    if (kept) return kept;
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(chunk(event));
  } else if (request.mode === "navigate" && !url.pathname.startsWith("/api/")) {
    event.respondWith(page(event));
  }
});

self.addEventListener("push", (event) => {
  let message = {};
  try {
    message = event.data ? event.data.json() : {};
  } catch {
    // A push this console did not write: show nothing rather than garbage.
    return;
  }
  event.waitUntil(
    self.registration.showNotification(message.title || "AgenticOS", {
      body: message.body || "",
      tag: message.tag,
      icon: "/icon",
      badge: "/icon",
      data: { url: message.url || "/dashboard" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/dashboard", self.location.origin);
  // Only a page of this console: the path came from the server, and a click is
  // not the moment to follow it anywhere else.
  if (target.origin !== self.location.origin) return;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((tabs) => {
      for (const tab of tabs) {
        if (new URL(tab.url).origin === target.origin && "focus" in tab) {
          return tab.navigate(target.href).then((opened) => (opened || tab).focus());
        }
      }
      return self.clients.openWindow(target.href);
    }),
  );
});
