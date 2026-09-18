const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");
const { writeNotificationImages } = require("./notification-assets");

test("creates valid added and duplicate PNG assets without contacting Home Assistant", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "alexa-bring-sync-assets-"));
  try {
    const files = writeNotificationImages(directory);
    for (const file of Object.values(files)) {
      const bytes = fs.readFileSync(file);
      assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
      assert.equal(bytes.readUInt32BE(16), 256);
      assert.equal(bytes.readUInt32BE(20), 256);
      assert.equal(bytes[24], 8);
      assert.equal(bytes[25], 6);
    }
    assert.notDeepEqual(fs.readFileSync(files.added), fs.readFileSync(files.duplicate));
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
