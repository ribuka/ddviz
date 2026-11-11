// The memory in the footer: the working sets of the backend and the frontend
// (`GET /api/memory`), fetched about once a second while the page is shown.
// Only these two numbers change: nothing else on the page is redrawn.

const MIB = 1024 ** 2;
const GIB = 1024 ** 3;
export const MEMORY_PERIOD_MS = 1000;

// Bytes as the footer shows them: whole MiB under 1 GiB (never "1024 MiB"),
// GiB with two decimals from 1 GiB; "—" when unknown.
export function memoryText(bytes) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < GIB) return `${Math.min(Math.round(bytes / MIB), 1023)} MiB`;
  return `${(bytes / GIB).toFixed(2)} GiB`;
}

// Fetches the memory and writes it into the two elements. At most one request
// is out at a time; the next starts about `period` after the previous one
// started, or as soon as it ends when it took longer, so a slow request never
// leaves a backlog. A hidden page sends none and fetches again when shown.
export class MemoryMeter {
  constructor(backend, frontend, period = MEMORY_PERIOD_MS) {
    this.backend = backend;
    this.frontend = frontend;
    this.period = period;
    this.pending = false;
    this.timer = null;
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) this.fetch();
    });
  }

  show(memory) {
    this.backend.textContent = memoryText(memory?.backend_bytes);
    this.frontend.textContent = memoryText(memory?.frontend_bytes);
  }

  async fetch() {
    if (this.pending || this.timer !== null || document.hidden) return;
    this.pending = true;
    const started = performance.now();
    let memory = null;
    try {
      const response = await fetch("/api/memory", { cache: "no-store" });
      if (response.ok) memory = await response.json();
    } catch {
      // Unreachable: both unknown until the next fetch succeeds.
    }
    this.pending = false;
    this.show(memory);
    if (document.hidden) return;
    const wait = Math.max(0, started + this.period - performance.now());
    this.timer = setTimeout(() => {
      this.timer = null;
      this.fetch();
    }, wait);
  }
}
