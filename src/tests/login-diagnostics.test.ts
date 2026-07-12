import test from "node:test";
import assert from "node:assert/strict";
import { classifyLoginState } from "../services/x.js";
import type { LoginSignals } from "../types.js";

const BASE: LoginSignals = {
  current_url: "https://x.com/home",
  title: "",
  http_status: 200,
  has_auth_cookie: false,
  has_csrf_cookie: false,
  auth_ui_detected: false,
  login_ui_detected: false,
  timeline_posts_visible: 0,
  blank_dialog_detected: false,
  security_challenge_detected: false,
  account_restricted_detected: false,
  rate_limit_detected: false,
  generic_error_detected: false
};

test("classifies an authenticated session", () => {
  const result = classifyLoginState({
    ...BASE,
    has_auth_cookie: true,
    has_csrf_cookie: true,
    auth_ui_detected: true
  });
  assert.equal(result.reason_code, "authenticated");
  assert.equal(result.authenticated, true);
});

test("classifies a stuck X SSO onboarding flow", () => {
  const result = classifyLoginState({
    ...BASE,
    current_url: "https://x.com/i/jf/onboarding/web/sso?mode=sso",
    blank_dialog_detected: true
  });
  assert.equal(result.reason_code, "x_sso_onboarding_stuck");
});

test("classifies a missing auth cookie", () => {
  const result = classifyLoginState({ ...BASE, title: "Log in / X", login_ui_detected: true });
  assert.equal(result.reason_code, "auth_cookie_missing");
});

test("classifies a rejected existing auth cookie", () => {
  const result = classifyLoginState({
    ...BASE,
    title: "Log in / X",
    has_auth_cookie: true,
    login_ui_detected: true
  });
  assert.equal(result.reason_code, "session_cookie_rejected");
});

test("classifies rate limiting before cookie state", () => {
  const result = classifyLoginState({ ...BASE, http_status: 429, rate_limit_detected: true });
  assert.equal(result.reason_code, "x_rate_limited");
});

test("classifies an interactive security challenge", () => {
  const result = classifyLoginState({ ...BASE, security_challenge_detected: true });
  assert.equal(result.reason_code, "x_security_challenge");
});
