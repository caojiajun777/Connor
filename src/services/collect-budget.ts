/** Pure helpers for profile/search scroll budgets (unit-tested). */

export type ScrollDecision = {
  continueScrolling: boolean;
  reason: "enough" | "empty_first_screen" | "max_passes" | "scroll";
};

/**
 * After extracting posts on `pass` (0-based), decide whether to wheel+wait again.
 * Empty first screens return immediately — do not burn 12×700ms on dead profiles.
 */
export function nextScrollDecision(input: {
  pass: number;
  seenCount: number;
  needed: number;
  maxPasses?: number;
}): ScrollDecision {
  const maxPasses = input.maxPasses ?? 12;
  if (input.seenCount >= input.needed) {
    return { continueScrolling: false, reason: "enough" };
  }
  if (input.pass === 0 && input.seenCount === 0) {
    return { continueScrolling: false, reason: "empty_first_screen" };
  }
  if (input.pass + 1 >= maxPasses) {
    return { continueScrolling: false, reason: "max_passes" };
  }
  return { continueScrolling: true, reason: "scroll" };
}

/** Cap how long we wait for the first tweet card on a profile (empty accounts). */
export function firstTweetWaitMs(fullTimeoutMs: number): number {
  return Math.min(fullTimeoutMs, 8_000);
}
