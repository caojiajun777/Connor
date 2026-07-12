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

export async function withAuthenticatedPage<T>(
  operation: (page: Page) => Promise<T>
): Promise<T> {
  let context: BrowserContext | undefined;
  try {
    context = await launchPersistentBrowser(true);
    const existing = context.pages()[0];
    const page = existing ?? (await context.newPage());
    return await operation(page);
  } catch (error) {
    if (error instanceof Error && /SingletonLock|profile.*in use|ProcessSingleton/i.test(error.message)) {
      throw new Error(
        "The X Agent browser profile is already open. Close the dedicated login window and retry."
      );
    }
    throw error;
  } finally {
    await context?.close().catch(() => undefined);
  }
}
