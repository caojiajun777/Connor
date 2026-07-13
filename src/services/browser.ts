import fs from "node:fs";
import { chromium, type BrowserContext, type Page } from "playwright-core";
import { profileDir, timeoutMs } from "../constants.js";

const WINDOWS_CANDIDATES = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"
];

const UNIX_CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser"
];

/**
 * Cap concurrent pages on the single shared profile.
 * Default 1 (serial). Max 2 — higher values raise X rate-limit risk.
 */
function maxConcurrentPages(): number {
  const raw = Number(process.env.X_AGENT_MAX_CONCURRENT_PAGES ?? "1");
  if (!Number.isFinite(raw)) return 1;
  return Math.max(1, Math.min(2, Math.floor(raw)));
}

class Semaphore {
  private active = 0;
  private readonly waiters: Array<() => void> = [];

  constructor(private readonly limit: number) {}

  async acquire(): Promise<void> {
    if (this.active < this.limit) {
      this.active += 1;
      return;
    }
    await new Promise<void>((resolve) => this.waiters.push(resolve));
    this.active += 1;
  }

  release(): void {
    this.active = Math.max(0, this.active - 1);
    const next = this.waiters.shift();
    if (next) next();
  }
}

const pageGate = new Semaphore(maxConcurrentPages());

let sharedContext: BrowserContext | null = null;
let launching: Promise<BrowserContext> | null = null;

export function findChromeExecutable(): string {
  const configured = process.env.X_AGENT_CHROME_PATH;
  if (configured) {
    const resolved = configured.trim();
    if (!fs.existsSync(resolved)) {
      throw new Error(`X_AGENT_CHROME_PATH does not exist: ${resolved}`);
    }
    return resolved;
  }

  const found = [...WINDOWS_CANDIDATES, ...UNIX_CANDIDATES].find((candidate) =>
    fs.existsSync(candidate)
  );
  if (!found) {
    throw new Error(
      "Chrome or Edge was not found. Set X_AGENT_CHROME_PATH to the browser executable."
    );
  }
  return found;
}

export async function launchPersistentBrowser(headless: boolean): Promise<BrowserContext> {
  fs.mkdirSync(profileDir(), { recursive: true });
  const context = await chromium.launchPersistentContext(profileDir(), {
    executablePath: findChromeExecutable(),
    headless,
    locale: "zh-CN",
    viewport: headless ? { width: 1440, height: 1000 } : null,
    timeout: timeoutMs()
  });
  context.setDefaultTimeout(timeoutMs());
  context.setDefaultNavigationTimeout(timeoutMs());
  return context;
}

async function getSharedContext(): Promise<BrowserContext> {
  if (sharedContext) return sharedContext;
  if (launching) return launching;
  launching = launchPersistentBrowser(true)
    .then((context) => {
      sharedContext = context;
      context.on("close", () => {
        if (sharedContext === context) sharedContext = null;
      });
      return context;
    })
    .finally(() => {
      launching = null;
    });
  return launching;
}

export async function closeSharedBrowser(): Promise<void> {
  const context = sharedContext;
  sharedContext = null;
  launching = null;
  if (context) await context.close().catch(() => undefined);
}

/**
 * Run work on a page from the shared persistent profile.
 * One Chrome process is reused for the whole MCP lifetime (collect speedup).
 * Page ops stay gated (default serial) so we do not multiply X sessions.
 */
export async function withAuthenticatedPage<T>(
  operation: (page: Page) => Promise<T>
): Promise<T> {
  await pageGate.acquire();
  let page: Page | undefined;
  try {
    const context = await getSharedContext();
    page = await context.newPage();
    return await operation(page);
  } catch (error) {
    if (
      error instanceof Error &&
      /SingletonLock|profile.*in use|ProcessSingleton/i.test(error.message)
    ) {
      // Stale shared handle after an external lock — drop and surface a clear error.
      sharedContext = null;
      throw new Error(
        "The X Agent browser profile is already open. Close the dedicated login window and retry."
      );
    }
    throw error;
  } finally {
    await page?.close().catch(() => undefined);
    pageGate.release();
  }
}

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    void closeSharedBrowser().finally(() => process.exit(0));
  });
}
