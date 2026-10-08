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

  it("treats empty text as no lines", () => {
    expect(lineDiff("", "one")).toEqual([{ op: "+", text: "one" }]);
    expect(lineDiff("same", "same")).toEqual([{ op: " ", text: "same" }]);
  });
});
