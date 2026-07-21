import assert from "node:assert/strict";
import test from "node:test";
import { firstTweetWaitMs, nextScrollDecision } from "../services/collect-budget.js";

test("empty first screen stops without further scrolls", () => {
  const d = nextScrollDecision({ pass: 0, seenCount: 0, needed: 21 });
  assert.equal(d.continueScrolling, false);
  assert.equal(d.reason, "empty_first_screen");
});

test("keeps scrolling when first screen has posts but needs more", () => {
  const d = nextScrollDecision({ pass: 0, seenCount: 5, needed: 21 });
  assert.equal(d.continueScrolling, true);
  assert.equal(d.reason, "scroll");
});

test("stops when enough posts collected", () => {
  const d = nextScrollDecision({ pass: 2, seenCount: 21, needed: 21 });
  assert.equal(d.continueScrolling, false);
  assert.equal(d.reason, "enough");
});

test("first tweet wait is capped", () => {
  assert.equal(firstTweetWaitMs(30_000), 8_000);
  assert.equal(firstTweetWaitMs(5_000), 5_000);
});
