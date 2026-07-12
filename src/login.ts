#!/usr/bin/env node
import { spawn } from "node:child_process";
import fs from "node:fs";
import { findChromeExecutable } from "./services/browser.js";
import { profileDir, X_BASE_URL } from "./constants.js";

async function main(): Promise<void> {
  const userDataDir = profileDir();
  fs.mkdirSync(userDataDir, { recursive: true });

  // OAuth providers such as Google may reject browsers launched through an
  // automation protocol. Start the installed browser as an ordinary native
  // process for the one-time sign-in, then let the MCP server reuse the
  // resulting profile only after the user closes this window.
  const child = spawn(
    findChromeExecutable(),
    [
      `--user-data-dir=${userDataDir}`,
      "--no-first-run",
      "--no-default-browser-check",
      `${X_BASE_URL}/home`
    ],
    {
      detached: true,
      stdio: "ignore",
      windowsHide: false
    }
  );
  child.unref();

  console.error(`Native Chrome login window opened. Profile: ${userDataDir}`);
  console.error("Complete the X/Google login, confirm the X Home timeline is visible, then CLOSE that dedicated Chrome window.");
  console.error("After it is closed, run x_session_status or start the MCP search tool.");
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
