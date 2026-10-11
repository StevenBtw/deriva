import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CodeEditor } from "./CodeEditor";

describe("CodeEditor", () => {
  it("shows the value in a CodeMirror editor", () => {
    const { container } = render(<CodeEditor label="Instruction" value="Classify each directory." onChange={() => {}} />);

    expect(container.querySelector(".cm-editor")).not.toBeNull();
    expect(container.textContent).toContain("Classify each directory.");
  });

  it("takes no typing while read only, and the same editor is unlocked again", () => {
    const { container, rerender } = render(<CodeEditor label="Instruction" value="one" readOnly onChange={() => {}} />);
    const editor = container.querySelector(".cm-editor");

    expect(container.querySelector(".cm-content")?.getAttribute("contenteditable")).toBe("false");
    rerender(<CodeEditor label="Instruction" value="one" onChange={() => {}} />);

    expect(container.querySelector(".cm-content")?.getAttribute("contenteditable")).toBe("true");
    expect(container.querySelector(".cm-editor")).toBe(editor);
  });

  it("follows a new value from the parent", () => {
    const { container, rerender } = render(<CodeEditor label="Instruction" value="one" onChange={() => {}} />);

    rerender(<CodeEditor label="Instruction" value="two" onChange={() => {}} />);

    expect(container.textContent).toContain("two");
  });
});
