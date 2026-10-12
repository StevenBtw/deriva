import { describe, expect, it } from "vitest";

import { GITHUB_URL, detectBrowser, detectOs, newIssueUrl } from "./issueReport";

describe("newIssueUrl", () => {
  it("opens a new bug report pre-filled with the environment", () => {
    const url = new URL(newIssueUrl({ version: "0.8.2", install: "deriva-dev", os: "Windows", python: "3.14.6", browser: "Chrome 130" }));

    expect(`${url.origin}${url.pathname}`).toBe(`${GITHUB_URL}/issues/new`);
    expect(url.searchParams.get("labels")).toBe("bug");
    expect(url.searchParams.get("title")?.trim()).toBe("[BUG]");
    const body = url.searchParams.get("body") ?? "";
    expect(body).toContain("**Describe the bug**");
    expect(body).toContain("**To Reproduce**");
    expect(body).toContain("**Expected behavior**");
    expect(body).toContain("**Environment**");
    expect(body).toContain("- Deriva version: 0.8.2");
    expect(body).toContain("- Install: deriva-dev");
    expect(body).toContain("- OS: Windows");
    expect(body).toContain("- Python: 3.14.6");
    expect(body).toContain("- Browser: Chrome 130");
  });

  it("leaves out what it does not know", () => {
    const url = new URL(newIssueUrl({ install: "deriva-studio" }));
    const body = url.searchParams.get("body") ?? "";

    expect(body).toContain("- Install: deriva-studio");
    expect(body).not.toContain("Deriva version:");
    expect(body).not.toContain("OS:");
    expect(body).not.toContain("Browser:");
  });
});

describe("browser detection", () => {
  it("falls back without user agent hints (jsdom reports no browser)", () => {
    // The OS depends on the machine running the tests; the browser stays unknown in jsdom
    expect(["Windows", "macOS", "Linux", "unknown"]).toContain(detectOs());
    expect(detectBrowser()).toBe("unknown");
  });
});
