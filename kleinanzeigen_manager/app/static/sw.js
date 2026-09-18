self.addEventListener('install', event => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {body: event.data ? event.data.text() : ''}; }
  const title = data.title || 'Kleinanzeigen Manager';
  const options = {
    body: data.body || 'Neue Nachricht',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/favicon-32.png',
    tag: data.tag || 'kleinanzeigen-message',
    renotify: true,
    data: {url: data.url || '/messages'}
  };
  event.waitUntil(self.registration.showNotification(title, options));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/messages';
  event.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(clients => {
    for (const client of clients) {
      if ('focus' in client) {
        try { client.navigate(target); } catch (e) {}
        return client.focus();
      }
    }
    return self.clients.openWindow ? self.clients.openWindow(target) : undefined;
  }));
});
