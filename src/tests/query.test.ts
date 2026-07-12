import test from "node:test";
import assert from "node:assert/strict";
import { buildSearchQuery, normalizePostUrl } from "../services/x.js";

test("buildSearchQuery appends optional filters", () => {
  assert.equal(
    buildSearchQuery({ query: '"new model"', since: "2026-07-01", until: "2026-07-12", lang: "en" }),
    '"new model" since:2026-07-01 until:2026-07-12 lang:en'
  );
});

test("buildSearchQuery does not duplicate native operators", () => {
  assert.equal(
    buildSearchQuery({ query: "Gemini since:2026-07-05 lang:en", since: "2026-07-01", lang: "zh" }),
    "Gemini since:2026-07-05 lang:en"
  );
});

test("normalizePostUrl accepts X and Twitter status links", () => {
  assert.equal(
    normalizePostUrl("https://twitter.com/OpenAI/status/12345?ref=test"),
    "https://x.com/OpenAI/status/12345"
  );
});

test("normalizePostUrl rejects non-X hosts", () => {
  assert.throws(() => normalizePostUrl("https://example.com/user/status/123"), /x\.com or twitter\.com/);
});
