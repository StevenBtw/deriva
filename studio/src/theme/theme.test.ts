import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { effectiveTheme, getTheme, nextTheme, setTheme, useTheme } from "./theme";

describe("theme", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("opens in dark whatever the system prefers", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({ matches: false } as MediaQueryList);

    expect(getTheme()).toBe("dark");
    expect(effectiveTheme()).toBe("dark");
  });

  it("applies and remembers an explicit choice", () => {
    setTheme("light");

    expect(document.documentElement.dataset.theme).toBe("light");
    expect(getTheme()).toBe("light");
    expect(effectiveTheme()).toBe("light");
  });

  it("toggles between dark and light", () => {
    expect(nextTheme("dark")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
  });

  it("survives storage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(getTheme()).toBe("dark");
  });

  it("still applies a choice when storage refuses to write", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    setTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    setTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

describe("useTheme", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    setTheme("dark");
    localStorage.clear();
  });

  it("tells every component when the theme changes, not only the one that changed it", () => {
    const toggle = renderHook(() => useTheme());
    const graphs = renderHook(() => useTheme());

    act(() => toggle.result.current[1]("light"));

    expect(graphs.result.current[0]).toBe("light");
    expect(graphs.result.current[2]).toBe("light");
  });
});
