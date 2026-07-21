import { describe, expect, it } from "vitest";

import { safeHttpUrl } from "@/lib/safe-url";

describe("safeHttpUrl", () => {
  it("allows http, https, and same-origin paths", () => {
    expect(safeHttpUrl("https://x.com/a")).toBe("https://x.com/a");
    expect(safeHttpUrl("http://example.com")).toBe("http://example.com/");
    expect(safeHttpUrl("/media/posts/a.jpg")).toBe("/media/posts/a.jpg");
  });

  it("rejects javascript, data, and protocol-relative", () => {
    expect(safeHttpUrl("javascript:alert(1)")).toBeNull();
    expect(safeHttpUrl("data:text/html,hi")).toBeNull();
    expect(safeHttpUrl("//evil.example/x")).toBeNull();
    expect(safeHttpUrl("")).toBeNull();
  });
});
