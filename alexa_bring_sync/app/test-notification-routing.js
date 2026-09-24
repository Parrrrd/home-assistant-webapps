const test = require("node:test");
const assert = require("node:assert/strict");
const { mobileAppNotifyTargets, notificationPayload, targetItemAlreadyKnown, targetItemAlreadyNotified } = require("./notification-routing");

test("sendet direkt an alle mobile_app-Dienste und ignoriert andere notify-Dienste", () => {
  const services = [
    { domain: "notify", services: ["mobile_app_phone_one", "mobile_app_secondary_iphone", "notify"] },
    { domain: "light", services: ["mobile_app_not_a_notify"] },
  ];
  assert.deepEqual(mobileAppNotifyTargets(services), [
    "notify.mobile_app_phone_one",
    "notify.mobile_app_secondary_iphone",
  ]);
});

test("erkennt die reale Home-Assistant-Service-Struktur mit services als Objekt", () => {
  const services = [
    { domain: "notify", services: {
      mobile_app_phone_one: { fields: {} },
      mobile_app_secondary_iphone: { fields: {} },
      notify: { fields: {} },
    } },
    { domain: "light", services: { turn_on: { fields: {} } } },
  ];
  assert.deepEqual(mobileAppNotifyTargets(services), [
    "notify.mobile_app_phone_one",
    "notify.mobile_app_secondary_iphone",
  ]);
});

test("lässt das Zusatzbild bei neuen Artikeln weg", () => {
  assert.deepEqual(notificationPayload("Es wurde Milch zur Einkaufsliste hinzugefügt!", "added", null), {
    title: "Einkaufsliste",
    message: "Es wurde Milch zur Einkaufsliste hinzugefügt!",
    data: {
      notification_icon: "mdi:cart-arrow-down",
      tag: "alexa-bring-sync",
      group: "alexa-bring-sync",
      push: { sound: "default" },
    },
  });
});

test("behält das Warnbild bei Duplikaten", () => {
  const payload = notificationPayload("Milch befindet sich schon auf der Einkaufsliste!", "duplicate", "/local/alexa_bring_sync/duplicate.png");
  assert.equal(payload.data.image, "/local/alexa_bring_sync/duplicate.png");
});


test("Push öffnet die direkte Einkaufsliste auf iOS und Android", () => {
  const payload = notificationPayload(
    "Milch befindet sich schon auf der Einkaufsliste!",
    "duplicate",
    "/local/alexa_bring_sync/duplicate.png",
    "http://example.invalid:8156/"
  );
  assert.equal(payload.data.url, "http://example.invalid:8156/");
  assert.equal(payload.data.clickAction, "http://example.invalid:8156/");
});

test("erkennt mobile_app Dienste auch wenn Home Assistant die Domains als Objekt liefert", () => {
  const services = {
    notify: {
      mobile_app_phone_one: { fields: {} },
      mobile_app_secondary_iphone: { fields: {} },
      notify: { fields: {} },
    },
    light: { turn_on: { fields: {} } },
  };
  assert.deepEqual(mobileAppNotifyTargets(services), [
    "notify.mobile_app_phone_one",
    "notify.mobile_app_secondary_iphone",
  ]);
});

test("eine neue stabile Eintrags-ID wird nicht durch alte Namenshistorie unterdrückt", () => {
  const known = {
    "name:milch": "Milch",
    milch: "Milch",
    "id:entry-old": "Milch",
  };
  assert.equal(targetItemAlreadyKnown(known, "id:entry-new", "milch", true), false);
  assert.equal(targetItemAlreadyKnown(known, "id:entry-old", "milch", true), true);
  assert.equal(targetItemAlreadyKnown(known, "name:milch", "milch", false), true);
});

test("unterdrückt beim Poll nur bereits direkt benachrichtigte Siri-CalDAV-Einträge", () => {
  assert.equal(targetItemAlreadyNotified({ notificationSource: "local-caldav" }), true);
  assert.equal(targetItemAlreadyNotified({ notificationSource: "apple-reminders" }), false);
  assert.equal(targetItemAlreadyNotified({}), false);
});

test("server sends added and duplicate pushes before Alexa completion and independent of image processing", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const source = fs.readFileSync(path.join(__dirname, "server.js"), "utf8");
  const start = source.indexOf('if (result.status === "added")');
  const end = source.indexOf('alexaCandidateMemory.delete(candidate.key);', start);
  const block = source.slice(start, end);
  assert.ok(block.indexOf('notifyAllDevices(`Es wurde ${processedName}') >= 0);
  assert.ok(block.indexOf('notifyAllDevices(`${processedName} befindet sich schon') >= 0);
  const completeIndex = source.indexOf('await completeAlexaItem(list.listId, sourceItem);', start);
  const addedPushIndex = source.indexOf('await notifyAllDevices(`Es wurde ${processedName}', start);
  const duplicatePushIndex = source.indexOf('await notifyAllDevices(`${processedName} befindet sich schon', start);
  assert.ok(addedPushIndex < completeIndex);
  assert.ok(duplicatePushIndex < completeIndex);
  assert.doesNotMatch(block, /imageStatus|generateProductImage|Gemini|gemini/i);
});
