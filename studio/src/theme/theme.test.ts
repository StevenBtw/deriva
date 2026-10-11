import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { effectiveTheme, getTheme, nextTheme, setTheme, useTheme } from "./theme";

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

  it("still applies a choice when storage refuses to write", () => {
    const blocked = () => {
      throw new Error("blocked");
    };
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(blocked);
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(blocked);

    setTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    setTheme("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });
});

describe("useTheme", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    setTheme("system");
  });

  it("tells every component when the theme changes, not only the one that changed it", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({ matches: false, addEventListener: () => {}, removeEventListener: () => {} } as unknown as MediaQueryList);
    const toggle = renderHook(() => useTheme());
    const graphs = renderHook(() => useTheme());

    act(() => toggle.result.current[1]("dark"));

    expect(graphs.result.current[0]).toBe("dark");
    expect(graphs.result.current[2]).toBe("dark");
  });
});
