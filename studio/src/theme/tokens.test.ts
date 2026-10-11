import { describe, expect, it } from "vitest";

import css from "./tokens.css?raw";

/** The custom properties a rule block sets, in order. */
function tokens(block: string | undefined): string[] {
  return (block ?? "")
    .split(";")
    .map((part) => part.trim())
    .filter((part) => part.startsWith("--") || part.startsWith("color-scheme"));
}

const dark = /:root,\s*:root\[data-theme="dark"\] \{([^}]*)\}/.exec(css)?.[1];
const systemLight = /@media \(prefers-color-scheme: light\) \{\s*:root:not\(\[data-theme="dark"\]\) \{([^}]*)\}/.exec(css)?.[1];
const chosenLight = /\n:root\[data-theme="light"\] \{([^}]*)\}/.exec(css)?.[1];

describe("theme tokens", () => {
  // The light palette is written twice (system preference and explicit choice); they must not drift apart
  it("gives the system's light mode and the chosen light theme the same palette", () => {
    expect(tokens(systemLight).length).toBeGreaterThan(10);
    expect(tokens(systemLight)).toEqual(tokens(chosenLight));
  });

  it("sets every dark token in the light palette too", () => {
    const names = (block: string | undefined) => tokens(block).map((t) => t.split(":")[0]);

    expect(names(chosenLight)).toEqual(names(dark));
  });
});
