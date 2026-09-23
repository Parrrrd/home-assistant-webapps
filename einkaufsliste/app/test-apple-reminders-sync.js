const test = require("node:test");
const assert = require("node:assert/strict");
const { createAppleRemindersSync, openTodos } = require("./apple-reminders-sync");

test("parses open VTODOs and ignores completed reminders", () => {
  const todos = openTodos("BEGIN:VTODO\r\nUID:milk-1\r\nSUMMARY:Milch\\, frisch\r\nSTATUS:NEEDS-ACTION\r\nEND:VTODO\r\nBEGIN:VTODO\r\nUID:done-1\r\nSUMMARY:Brot\r\nSTATUS:COMPLETED\r\nEND:VTODO", "/todo.ics");
  assert.deepEqual(todos, [{ id: "milk-1", name: "Milch, frisch", status: "NEEDS-ACTION" }]);
});

test("discovers one named VTODO list and imports it without changing the remote list", async () => {
  const originalFetch = global.fetch;
  const calls = [];
  const xml = [
    `<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop><d:current-user-principal><d:href>/principal/</d:href></d:current-user-principal></d:prop></d:propstat></d:response></d:multistatus>`,
    `<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:propstat><d:prop><c:calendar-home-set><d:href>/calendars/user/</d:href></c:calendar-home-set></d:prop></d:propstat></d:response></d:multistatus>`,
    `<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:href>/calendars/user/einkauf/</d:href><d:propstat><d:prop><d:displayname>Einkaufsliste</d:displayname><c:supported-calendar-component-set><c:comp name="VTODO"/></c:supported-calendar-component-set></d:prop></d:propstat></d:response></d:multistatus>`,
    `<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:href>/calendars/user/einkauf/milch.ics</d:href><d:propstat><d:prop><c:calendar-data>BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:milk-1\r\nSUMMARY:Milch\r\nSTATUS:NEEDS-ACTION\r\nEND:VTODO\r\nEND:VCALENDAR</c:calendar-data></d:prop></d:propstat></d:response></d:multistatus>`,
  ];
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), method: options.method });
    return new Response(xml.shift(), { status: 207, headers: { "content-type": "application/xml" } });
  };
  const received = [];
  try {
    const sync = createAppleRemindersSync({
      getOptions: () => ({ reminders_sync_enabled: true, reminders_sync_username: "patrick@example.test", reminders_sync_password: "app-password", reminders_sync_list_name: "Einkaufsliste", reminders_sync_target_list_id: "supermarkt" }),
      onItems: async (items, target) => { received.push({ items, target }); return { added: items.length, duplicates: 0 }; },
      log: () => {},
    });
    const state = await sync.run();
    assert.equal(state.state, "ready", state.detail);
    assert.equal(state.imported, 1);
    assert.deepEqual(received, [{ items: [{ id: "milk-1", name: "Milch", status: "NEEDS-ACTION" }], target: "supermarkt" }]);
    assert.deepEqual(calls.map((call) => call.method), ["PROPFIND", "PROPFIND", "PROPFIND", "REPORT"]);
  } finally { global.fetch = originalFetch; }
});

test("does not contact Apple while the separate sync is disabled", async () => {
  const sync = createAppleRemindersSync({ getOptions: () => ({ reminders_sync_enabled: false }), onItems: async () => { throw new Error("must not import"); }, log: () => {} });
  const state = await sync.run();
  assert.equal(state.state, "disabled");
});
