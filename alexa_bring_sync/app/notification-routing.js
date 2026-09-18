function normalizeServiceDomains(services) {
  if (Array.isArray(services)) return services;
  if (!services || typeof services !== "object") return [];
  return Object.entries(services).map(([domain, value]) => {
    if (value && typeof value === "object" && (value.domain || value.services)) {
      return { domain: value.domain || domain, services: value.services || value };
    }
    return { domain, services: value };
  });
}

function notifyServiceNames(entry) {
  if (!entry || entry.domain !== "notify") return [];
  if (Array.isArray(entry.services)) return entry.services.map(String);
  if (entry.services && typeof entry.services === "object") return Object.keys(entry.services);
  return [];
}

function mobileAppNotifyTargets(services) {
  return normalizeServiceDomains(services)
    .flatMap(notifyServiceNames)
    .filter((service) => /^mobile_app_[a-z0-9_]+$/i.test(String(service)))
    .map((service) => `notify.${service}`);
}

function notificationPayload(message, kind, imageUrl, targetUrl) {
  const data = {
    notification_icon: "mdi:cart-arrow-down",
    tag: "alexa-bring-sync",
    group: "alexa-bring-sync",
    push: { sound: "default" },
  };
  if (imageUrl) data.image = imageUrl;
  if (targetUrl) { data.url = targetUrl; data.clickAction = targetUrl; }
  return {
    title: "Einkaufsliste",
    message,
    data,
  };
}

module.exports = { normalizeServiceDomains, mobileAppNotifyTargets, notificationPayload };
