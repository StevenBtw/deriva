import { afterEach, describe, expect, it, vi } from "vitest";

import { effectiveTheme, getTheme, nextTheme, setTheme } from "./theme";

describe("theme", () => {
  afterEach(() => vi.restoreAllMocks());

  it("defaults to the system preference", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({ matches: true } as MediaQueryList);

    expect(getTheme()).toBe("system");
    expect(effectiveTheme()).toBe("dark");
  });

  it("applies and remembers an explicit choice", () => {
    setTheme("dark");

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(getTheme()).toBe("dark");
    expect(effectiveTheme()).toBe("dark");
  });

  it("removes the attribute for system", () => {
    setTheme("light");
    setTheme("system");

    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(getTheme()).toBe("system");
  });

  it("cycles system, light, dark", () => {
    expect(nextTheme("system")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("system");
  });

  it("survives storage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(getTheme()).toBe("system");
  });
});
