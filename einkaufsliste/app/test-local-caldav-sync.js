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

test("does not read local CalDAV storage while disabled", async () => {
  let imported = 0;
  const sync = createLocalCaldavSync({ getOptions: () => ({ caldav_enabled: false }), onItems: async () => { imported += 1; }, root: os.tmpdir() });
  const status = await sync.run();
  assert.equal(status.state, "disabled");
  assert.equal(imported, 0);
});
