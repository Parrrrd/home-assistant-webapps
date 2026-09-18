const fs = require("node:fs");
const path = require("node:path");
const zlib = require("node:zlib");

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data) {
  const name = Buffer.from(type, "ascii");
  const crcInput = Buffer.concat([name, data]);
  const chunk = Buffer.alloc(12 + data.length);
  chunk.writeUInt32BE(data.length, 0);
  name.copy(chunk, 4);
  data.copy(chunk, 8);
  chunk.writeUInt32BE(crc32(crcInput), 8 + data.length);
  return chunk;
}

function makeNotificationPng(kind) {
  const width = 256;
  const height = 256;
  const pixels = Buffer.alloc(width * height * 4);
  const setPixel = (x, y, color) => {
    if (x < 0 || x >= width || y < 0 || y >= height) return;
    const offset = (y * width + x) * 4;
    pixels[offset] = color[0];
    pixels[offset + 1] = color[1];
    pixels[offset + 2] = color[2];
    pixels[offset + 3] = color[3];
  };
  const fillCircle = (cx, cy, radius, color) => {
    const radiusSquared = radius * radius;
    for (let y = cy - radius; y <= cy + radius; y += 1) {
      for (let x = cx - radius; x <= cx + radius; x += 1) {
        if ((x - cx) ** 2 + (y - cy) ** 2 <= radiusSquared) setPixel(x, y, color);
      }
    }
  };
  const fillRect = (x1, y1, x2, y2, color) => {
    for (let y = y1; y <= y2; y += 1) for (let x = x1; x <= x2; x += 1) setPixel(x, y, color);
  };
  const fillTriangle = (a, b, c, color) => {
    const edge = (p1, p2, p) => (p.x - p2.x) * (p1.y - p2.y) - (p1.x - p2.x) * (p.y - p2.y);
    const minX = Math.max(0, Math.floor(Math.min(a.x, b.x, c.x)));
    const maxX = Math.min(width - 1, Math.ceil(Math.max(a.x, b.x, c.x)));
    const minY = Math.max(0, Math.floor(Math.min(a.y, b.y, c.y)));
    const maxY = Math.min(height - 1, Math.ceil(Math.max(a.y, b.y, c.y)));
    for (let y = minY; y <= maxY; y += 1) {
      for (let x = minX; x <= maxX; x += 1) {
        const p = { x, y };
        const w1 = edge(b, c, p);
        const w2 = edge(c, a, p);
        const w3 = edge(a, b, p);
        if ((w1 >= 0 && w2 >= 0 && w3 >= 0) || (w1 <= 0 && w2 <= 0 && w3 <= 0)) setPixel(x, y, color);
      }
    }
  };
  const green = [39, 201, 67, 255];
  const red = [242, 45, 45, 255];
  const white = [255, 255, 255, 255];
  if (kind === "duplicate") {
    fillTriangle({ x: 128, y: 18 }, { x: 244, y: 226 }, { x: 12, y: 226 }, red);
    fillRect(115, 78, 141, 158, white);
    fillCircle(128, 190, 13, white);
  } else {
    fillCircle(128, 128, 112, green);
    fillRect(114, 66, 142, 190, white);
    fillRect(66, 114, 190, 142, white);
    fillCircle(128, 66, 14, white);
    fillCircle(128, 190, 14, white);
    fillCircle(66, 128, 14, white);
    fillCircle(190, 128, 14, white);
  }
  const rows = [];
  for (let y = 0; y < height; y += 1) rows.push(Buffer.concat([Buffer.from([0]), pixels.subarray(y * width * 4, (y + 1) * width * 4)]));
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 6;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk("IHDR", header),
    pngChunk("IDAT", zlib.deflateSync(Buffer.concat(rows))),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

function writeNotificationImages(directory) {
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, "added.png"), makeNotificationPng("added"));
  fs.writeFileSync(path.join(directory, "duplicate.png"), makeNotificationPng("duplicate"));
  return {
    added: path.join(directory, "added.png"),
    duplicate: path.join(directory, "duplicate.png"),
  };
}

module.exports = { makeNotificationPng, writeNotificationImages };
