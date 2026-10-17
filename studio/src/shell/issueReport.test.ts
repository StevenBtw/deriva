import { afterEach, describe, expect, it, vi } from "vitest";

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
    expect(body).toContain("**Screenshots**");
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

/** Replace the navigator's user agent (and its hints) for one test; restored after each test. */
function stubNavigator(userAgent: string, userAgentData?: { platform?: string; brands?: { brand: string; version: string }[] }) {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(userAgent);
  Object.defineProperty(navigator, "userAgentData", { value: userAgentData, configurable: true });
}

describe("browser detection", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(navigator, "userAgentData", { value: undefined, configurable: true });
  });

  it("falls back without user agent hints (jsdom reports no browser)", () => {
    expect(detectBrowser()).toBe("unknown");
  });

  it.each([
    ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.2849.68", "Edge 130.0.2849.68"],
    ["Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0", "Firefox 131.0"],
    ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36", "Chrome 130.0.0.0"],
    ["Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0.6723.90 Mobile/15E148 Safari/604.1", "Chrome 130.0.6723.90"],
    ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15", "Safari 18.0"],
  ])("names the browser from the user agent %#", (userAgent, browser) => {
    stubNavigator(userAgent);
    expect(detectBrowser()).toBe(browser);
  });

  it("names the browser from the hints, without the placeholder and Chromium brands", () => {
    stubNavigator("", { brands: [{ brand: "Not=A?Brand", version: "8" }, { brand: "Chromium", version: "130" }, { brand: "Google Chrome", version: "130" }] });
    expect(detectBrowser()).toBe("Google Chrome 130");
  });

  it.each([
    ["Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Windows"],
    ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "macOS"],
    ["Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36", "Android"],
    ["Mozilla/5.0 (X11; Linux x86_64; rv:131.0)", "Linux"],
    ["Mozilla/5.0", "unknown"],
  ])("names the OS from the user agent %#", (userAgent, os) => {
    stubNavigator(userAgent);
    expect(detectOs()).toBe(os);
  });

  it("names the OS from the platform hint first", () => {
    stubNavigator("Mozilla/5.0 (X11; Linux x86_64)", { platform: "ChromeOS" });
    expect(detectOs()).toBe("ChromeOS");
  });
});
