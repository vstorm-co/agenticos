// The console's service worker (#2097): Web Push, and nothing else - no cache,
// no offline copy of anything. A push carries a title, a body, a console path
// and a tag; a click opens that path in a console tab, or focuses one.

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
