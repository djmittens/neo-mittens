// Extracts the real readSseStream/dispatchSseFrame source out of the shipped
// userscript and exercises it, so we test the actual text that runs in the
// browser rather than a copy.
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

// Resolve relative to this file so the test runs from any cwd / checkout.
const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(HERE, "bnetswitch-lfg.user.js"), "utf8");

function extractFn(name) {
  let start = SRC.indexOf(`function ${name}(`);
  if (start === -1) throw new Error(`missing ${name}`);
  // Keep the `async` keyword if the declaration has one.
  if (SRC.slice(start - 6, start) === "async ") start -= 6;
  let i = SRC.indexOf("{", start);
  let depth = 0;
  for (; i < SRC.length; i++) {
    if (SRC[i] === "{") depth++;
    else if (SRC[i] === "}" && --depth === 0) return SRC.slice(start, i + 1);
  }
  throw new Error(`unbalanced ${name}`);
}

const seen = [];
const harness = `
  ${extractFn("readSseStream")}
  ${extractFn("dispatchSseFrame")}
  return { readSseStream, dispatchSseFrame };
`;
const { readSseStream } = new Function(
  "noteSseActivity",
  "handleServerEvent",
  "TextDecoder",
  harness
)(() => {}, (t, d) => seen.push([t, d]), TextDecoder);

function streamOf(chunks) {
  const enc = new TextEncoder();
  let i = 0;
  return {
    getReader: () => ({
      read: async () =>
        i < chunks.length
          ? { value: enc.encode(chunks[i++]), done: false }
          : { value: undefined, done: true },
    }),
  };
}

let failures = 0;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
  if (!ok) console.log(`      got  ${JSON.stringify(got)}\n      want ${JSON.stringify(want)}`);
}

// 1. Whole frames in one chunk.
seen.length = 0;
await readSseStream(
  streamOf(['event: boot\ndata: {"boot_id":"abc"}\n\nevent: ping\ndata: {}\n\n'])
);
check("whole frames", seen, [["boot", '{"boot_id":"abc"}'], ["ping", "{}"]]);

// 2. A frame split across chunk boundaries mid-field and mid-separator.
seen.length = 0;
await readSseStream(streamOf(["event: act", "ion\ndata: {\"id\":1", '}\n', "\n"]));
check("split across chunks", seen, [["action", '{"id":1}'] ]);

// 3. Multi-line data must be joined with \n, per the SSE spec.
seen.length = 0;
await readSseStream(streamOf(["event: action\ndata: a\ndata: b\n\n"]));
check("multi-line data", seen, [["action", "a\nb"]]);

// 4. Comments (keepalive `:` lines) and CRLF must not produce events.
seen.length = 0;
await readSseStream(streamOf([": keepalive\n\nevent: ping\r\ndata: {}\r\n\r\n"]));
check("comments + CRLF", seen, [["ping", "{}"]]);

// 5. A frame with no data lines is not dispatched.
seen.length = 0;
await readSseStream(streamOf(["event: nodata\n\n"]));
check("event without data ignored", seen, []);

// 6. Trailing partial frame is held, not emitted.
seen.length = 0;
await readSseStream(streamOf(["event: action\ndata: {}\n\nevent: half\ndata: x"]));
check("partial tail withheld", seen, [["action", "{}"]]);

// 7. Multi-byte UTF-8 split across a chunk boundary must not corrupt.
seen.length = 0;
const enc = new TextEncoder().encode('event: action\ndata: "é"\n\n');
const cut = enc.indexOf(0xc3); // first byte of 'é'
const raw = {
  getReader: () => {
    let n = 0;
    const parts = [enc.slice(0, cut + 1), enc.slice(cut + 1)];
    return { read: async () => (n < 2 ? { value: parts[n++], done: false } : { done: true }) };
  },
};
await readSseStream(raw);
check("utf-8 split mid-codepoint", seen, [["action", '"é"']]);

// 8. CRLF torn exactly across a chunk boundary must stay ONE line break.
seen.length = 0;
await readSseStream(streamOf(["event: action\r\ndata: {}\r", "\n\r\n"]));
check("CRLF torn across chunks", seen, [["action", "{}"]]);

// 9. Bare-CR terminators (legal in SSE) still frame correctly.
seen.length = 0;
await readSseStream(streamOf(["event: action\rdata: {}\r\r"]));
check("bare CR terminators", seen, [["action", "{}"]]);

console.log(failures === 0 ? "\nALL PASS" : `\n${failures} FAILURE(S)`);
process.exit(failures ? 1 : 0);
