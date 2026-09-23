"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { readOpenTodos, createLocalCaldavSync } = require("./local-caldav-sync");

test("reads only open VTODOs from the local CalDAV storage", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "caldav-todos-"));
  try {
    fs.mkdirSync(path.join(root, "user", "einkauf"), { recursive: true });
    fs.writeFileSync(path.join(root, "user", "einkauf", "milk.ics"), "BEGIN:VCALENDAR\nBEGIN:VTODO\nUID:milk-1\nSUMMARY:Milch\nSTATUS:NEEDS-ACTION\nEND:VTODO\nEND:VCALENDAR\n");
    fs.writeFileSync(path.join(root, "user", "einkauf", "done.ics"), "BEGIN:VCALENDAR\nBEGIN:VTODO\nUID:done-1\nSUMMARY:Alte Milch\nSTATUS:COMPLETED\nEND:VTODO\nEND:VCALENDAR\n");
    assert.deepEqual(readOpenTodos(root).map((item) => ({ id: item.id, name: item.name })), [{ id: "milk-1", name: "Milch" }]);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test("removes only successfully handled CalDAV reminders", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "caldav-todos-"));
  try {
    const folder = path.join(root, "user", "einkauf");
    fs.mkdirSync(folder, { recursive: true });
    const milk = path.join(folder, "milk.ics");
    const bread = path.join(folder, "bread.ics");
    fs.writeFileSync(milk, "BEGIN:VCALENDAR\nBEGIN:VTODO\nUID:milk-1\nSUMMARY:Milch\nSTATUS:NEEDS-ACTION\nEND:VTODO\nEND:VCALENDAR\n");
    fs.writeFileSync(bread, "BEGIN:VCALENDAR\nBEGIN:VTODO\nUID:bread-1\nSUMMARY:Brot\nSTATUS:NEEDS-ACTION\nEND:VTODO\nEND:VCALENDAR\n");
    const sync = createLocalCaldavSync({
      getOptions: () => ({ caldav_enabled: true, caldav_username: "einkauf", caldav_password: "secret" }),
      onItems: async () => ({ added: 1, duplicates: 0, handledSourceIds: ["milk-1"] }), root, log: () => {},
    });
    const status = await sync.run();
    assert.equal(status.state, "ready");
    assert.equal(fs.existsSync(milk), false);
    assert.equal(fs.existsSync(bread), true);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test("does not read local CalDAV storage while disabled", async () => {
  let imported = 0;
  const sync = createLocalCaldavSync({ getOptions: () => ({ caldav_enabled: false }), onItems: async () => { imported += 1; }, root: os.tmpdir() });
  const status = await sync.run();
  assert.equal(status.state, "disabled");
  assert.equal(imported, 0);
});
