const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "einkaufsliste-siri-tests-"));
process.env.DATA_DIR = dataDir;
process.env.DATA_FILE = path.join(dataDir, "shopping-list.json");
process.env.BACKUP_DIR = path.join(dataDir, "backups");
fs.writeFileSync(path.join(dataDir, "options.json"), JSON.stringify({ shortcut_token: "test-only-shortcut-token" }));

const { server, shortcutItemInput } = require("./server");

function request(base, pathname, body, token = "test-only-shortcut-token") {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const req = require("node:http").request(base + pathname, {
      method: "POST",
      headers: { "content-type": "application/json", "content-length": Buffer.byteLength(payload), "x-sync-token": token },
    }, (res) => {
      let raw = "";
      res.on("data", (chunk) => { raw += chunk; });
      res.on("end", () => resolve({ status: res.statusCode, body: JSON.parse(raw) }));
    });
    req.on("error", reject);
    req.end(payload);
  });
}

test.after(async () => {
  if (server.listening) await new Promise((resolve) => server.close(resolve));
  fs.rmSync(dataDir, { recursive: true, force: true });
});

test("Siri shortcut accepts dictated text, cleans a full sentence and returns a spoken confirmation", async () => {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;

  assert.equal(shortcutItemInput("Setze Milch auf die Einkaufsliste"), "Milch");
  const rejected = await request(base, "/api/shortcut/add", { input: "Milch" }, "wrong-token");
  assert.equal(rejected.status, 401);

  const added = await request(base, "/api/shortcut/add", { input: "Setze Milch auf die Einkaufsliste" });
  assert.equal(added.status, 201);
  assert.equal(added.body.status, "added");
  assert.equal(added.body.entry.productName, "Milch");
  assert.match(added.body.message, /Milch.*steht jetzt auf Einkaufsliste/i);

  const duplicate = await request(base, "/api/shortcut/add", { text: "Milch" });
  assert.equal(duplicate.status, 200);
  assert.equal(duplicate.body.status, "duplicate");
  assert.match(duplicate.body.message, /bereits auf Einkaufsliste/i);
});
