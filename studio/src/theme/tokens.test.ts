import { describe, expect, it } from "vitest";

import css from "./tokens.css?raw";

/** The custom properties a rule block sets, in order. */
function names(block: string | undefined): string[] {
  return (block ?? "")
    .split(";")
    .map((part) => part.trim())
    .filter((part) => part.startsWith("--"))
    .map((part) => part.split(":")[0]);
}

const generated = /\/\* design-tokens:start[^*]*\*\/([\s\S]*?)\/\* design-tokens:end \*\//.exec(css)?.[1] ?? "";
const dark = /:root,\s*:root\[data-theme="dark"\] \{([^}]*)\}/.exec(generated)?.[1];
const light = /:root\[data-theme="light"\] \{([^}]*)\}/.exec(generated)?.[1];

describe("theme tokens", () => {
  it("takes the palette from the generated design-token block, dark first", () => {
    expect(names(dark).length).toBeGreaterThan(15);
    expect(names(light)).toEqual(names(dark));
  });

  it("carries eight cluster colours (the anywidget data palette) in both themes", () => {
    const clusters = (block: string | undefined) => names(block).filter((n) => n.startsWith("--cluster-"));
    expect(clusters(dark)).toEqual(["--cluster-1", "--cluster-2", "--cluster-3", "--cluster-4", "--cluster-5", "--cluster-6", "--cluster-7", "--cluster-8"]);
    expect(clusters(light)).toEqual(clusters(dark));
    for (const block of [dark, light]) {
      const colours = (block ?? "")
        .split(";")
        .map((part) => part.trim())
        .filter((part) => part.startsWith("--cluster-"))
        .map((part) => part.slice(part.indexOf(":") + 1).trim());
      for (const colour of colours) expect(colour).toMatch(/^#[0-9a-f]{6}$/i);
      expect(new Set(colours).size).toBe(8);
    }
  });

  it("declares the colour scheme of each theme", () => {
    expect(dark).toMatch(/color-scheme:\s*dark;/);
    expect(light).toMatch(/color-scheme:\s*light;/);
  });

  it("lets the pointer cross from the DB indicator to its details without closing them", () => {
    expect(css).toMatch(/\.db-details::before \{[^}]*height: 7px;/);
  });

  it("does not follow the system preference: Studio opens in dark", () => {
    expect(css).not.toContain("prefers-color-scheme");
  });

  it("sets the Studio type: IBM Plex Mono at 13px with line height 1.6", () => {
    expect(css).toMatch(/font:\s*13px\/1\.6 "IBM Plex Mono"/);
    expect(css).toContain('font-family: "IBM Plex Mono"');
  });

  it("fills the Run button with the brand colour, not a status colour", () => {
    const go = /button\.go \{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(go).toContain("background: var(--primary)");
    expect(go).not.toContain("var(--ok)");
  });
});

describe("type weights", () => {
  // A weight without its own font file is faked by the browser (a smeared, blurry bold)
  const shipped = new Set([...css.matchAll(/@font-face\s*\{[^}]*font-weight:\s*(\d+)/g)].map((m) => m[1]));
  const used = new Set([...css.replace(/@font-face\s*\{[^}]*\}/g, "").matchAll(/font-weight:\s*(\d+|bold)/g)].map((m) => (m[1] === "bold" ? "700" : m[1])));

  it("uses only weights it ships, up to SemiBold (600)", () => {
    expect([...shipped].sort()).toEqual(["400", "500", "600"]);
    for (const weight of used) expect(shipped.has(weight), `font-weight ${weight} has a font file`).toBe(true);
  });

  it("never lets the browser fake a weight or a style", () => {
    expect(css).toMatch(/font-synthesis:\s*none/);
  });
});
