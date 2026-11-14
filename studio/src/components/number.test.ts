import { describe, expect, it } from "vitest";

import { decimal } from "./number";

describe("decimal", () => {
  it("shows a float32 value as the number that was set", () => {
    expect(decimal(0.30000001192092896)).toBe("0.3");
    expect(decimal(0.699999988079071)).toBe("0.7");
  });

  it("keeps exact values as they are", () => {
    expect(decimal(0)).toBe("0");
    expect(decimal(1)).toBe("1");
    expect(decimal(0.25)).toBe("0.25");
  });

  it("keeps a seventh significant digit", () => {
    expect(decimal(Math.fround(1.234567))).toBe("1.234567");
  });
});
