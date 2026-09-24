"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { mobileAppNotifyTargets, reminderNotificationPayload } = require("./notification-routing");

test("uses every Home-Assistant mobile-app notification service", () => {
  assert.deepEqual(mobileAppNotifyTargets({ notify: { mobile_app_patricks_iphone: {}, mobile_app_tablet: {}, notify: {} } }), ["notify.mobile_app_patricks_iphone", "notify.mobile_app_tablet"]);
});

test("creates a visible, grouped iPhone notification", () => {
  assert.deepEqual(reminderNotificationPayload("Milch wurde zur Einkaufsliste hinzugefügt."), {
    title: "Einkaufsliste", message: "Milch wurde zur Einkaufsliste hinzugefügt.",
    data: { notification_icon: "mdi:cart-arrow-down", tag: "einkaufsliste-erinnerungen", group: "einkaufsliste-erinnerungen", push: { sound: "default" } },
  });
});


test("uses the existing exclamation-mark notification group for local CalDAV imports", () => {
  assert.deepEqual(reminderNotificationPayload("Es wurde Milch zur Einkaufsliste hinzugefügt!", { source: "local-caldav" }), {
    title: "Einkaufsliste", message: "Es wurde Milch zur Einkaufsliste hinzugefügt!",
    data: { notification_icon: "mdi:cart-arrow-down", tag: "alexa-bring-sync", group: "alexa-bring-sync", push: { sound: "default" } },
  });
});
