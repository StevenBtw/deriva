import { describe, expect, it } from "vitest";

import { lineDiff } from "./diff";

describe("lineDiff", () => {
  it("keeps common lines and marks removed and added ones in order", () => {
    expect(lineDiff("a\nb\nc", "a\nx\nc\nd")).toEqual([
      { op: " ", text: "a" },
      { op: "-", text: "b" },
      { op: "+", text: "x" },
      { op: " ", text: "c" },
      { op: "+", text: "d" },
    ]);
  });

  it("diffs long texts without a table of their full size", () => {
    const before = Array.from({ length: 4000 }, (_, i) => `old ${i}`);
    const after = Array.from({ length: 4000 }, (_, i) => `new ${i}`);

    const lines = lineDiff(["head", ...before, "tail"].join("\n"), ["head", ...after, "tail"].join("\n"));

    expect(lines).toHaveLength(8002);
    expect([lines[0], lines[lines.length - 1]]).toEqual([
      { op: " ", text: "head" },
      { op: " ", text: "tail" },
    ]);
    expect(lines.filter((l) => l.op === "-")).toHaveLength(4000);
  });

  it("treats empty text as no lines", () => {
    expect(lineDiff("", "one")).toEqual([{ op: "+", text: "one" }]);
    expect(lineDiff("same", "same")).toEqual([{ op: " ", text: "same" }]);
  });
});
