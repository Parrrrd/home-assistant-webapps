"use strict";

function normalizeServiceDomains(services) {
  if (Array.isArray(services)) return services;
  if (!services || typeof services !== "object") return [];
  return Object.entries(services).map(([domain, value]) => ({ domain: value?.domain || domain, services: value?.services || value }));
}

function mobileAppNotifyTargets(services) {
  return normalizeServiceDomains(services)
    .filter((entry) => entry?.domain === "notify")
    .flatMap((entry) => Array.isArray(entry.services) ? entry.services : Object.keys(entry.services || {}))
    .filter((service) => /^mobile_app_[a-z0-9_]+$/i.test(String(service)))
    .map((service) => `notify.${service}`);
}

function reminderNotificationPayload(message) {
  return { title: "Einkaufsliste", message, data: { notification_icon: "mdi:cart-arrow-down", tag: "einkaufsliste-erinnerungen", group: "einkaufsliste-erinnerungen", push: { sound: "default" } } };
}

function shouldSendReminderNotification(context = {}) {
  return String(context?.source || "") !== "local-caldav";
}

module.exports = { normalizeServiceDomains, mobileAppNotifyTargets, reminderNotificationPayload, shouldSendReminderNotification };
