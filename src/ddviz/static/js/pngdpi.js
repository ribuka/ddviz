// The resolution of a PNG: its pHYs chunk, which tells the pixels per metre
// (`docs/spec.md`, "グラフ画像のコピー"). A canvas's PNG has none; a copied
// graph image gets one after its IHDR, so that an application that reads it
// knows the image's size in inches.

const SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];
// Bytes of a chunk around its data: length, type and CRC.
const FRAME = 12;

let table = null;

// Returns the CRC-32 of the PNG specification (that of zlib) of `bytes`.
export function crc32(bytes) {
  table ??= Uint32Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  let crc = 0xffffffff;
  for (const byte of bytes) crc = table[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

// Returns the pixels per metre of `dpi` dots per inch, as pHYs holds them.
export function pixelsPerMetre(dpi) {
  return Math.round(dpi / 0.0254);
}

// Returns the PNG `bytes` (a Uint8Array) with a pHYs chunk of `dpi` (the
// same both ways, the unit the metre) after its IHDR, in place of the pHYs
// it had. Throws on bytes that are not a PNG.
export function withDpi(bytes, dpi) {
  if (bytes.length < SIGNATURE.length + FRAME || SIGNATURE.some((b, i) => bytes[i] !== b)) {
    throw new Error("PNG の形式ではありません");
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const type = (at) => String.fromCharCode(...bytes.subarray(at + 4, at + 8));
  const parts = [bytes.subarray(0, SIGNATURE.length)];
  let at = SIGNATURE.length;
  while (at < bytes.length) {
    if (at + FRAME > bytes.length) throw new Error("PNG のチャンクが途中で切れています");
    const end = at + FRAME + view.getUint32(at);
    if (end > bytes.length) throw new Error("PNG のチャンクが途中で切れています");
    const name = type(at);
    if (name !== "pHYs") parts.push(bytes.subarray(at, end));
    if (name === "IHDR") parts.push(physChunk(dpi));
    at = end;
  }
  if (type(SIGNATURE.length) !== "IHDR") throw new Error("PNG の IHDR がありません");
  const out = new Uint8Array(parts.reduce((n, part) => n + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

// Returns the pHYs chunk of `dpi`: its length, type, data and CRC.
function physChunk(dpi) {
  const chunk = new Uint8Array(FRAME + 9);
  const view = new DataView(chunk.buffer);
  view.setUint32(0, 9);
  chunk.set([..."pHYs"].map((c) => c.charCodeAt(0)), 4);
  const ppm = pixelsPerMetre(dpi);
  view.setUint32(8, ppm);
  view.setUint32(12, ppm);
  chunk[16] = 1;
  view.setUint32(17, crc32(chunk.subarray(4, 17)));
  return chunk;
}
