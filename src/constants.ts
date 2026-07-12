import os from "node:os";
import path from "node:path";

export const CHARACTER_LIMIT = 25_000;
export const DEFAULT_TIMEOUT_MS = 30_000;
export const DEFAULT_PROFILE_DIR = path.join(os.homedir(), ".codex-x-news-agent");
export const X_BASE_URL = "https://x.com";

export function profileDir(): string {
  return path.resolve(process.env.X_AGENT_PROFILE_DIR || DEFAULT_PROFILE_DIR);
}

export function timeoutMs(): number {
  const parsed = Number.parseInt(process.env.X_AGENT_TIMEOUT_MS || "", 10);
  return Number.isFinite(parsed) && parsed >= 5_000 && parsed <= 120_000
    ? parsed
    : DEFAULT_TIMEOUT_MS;
}
