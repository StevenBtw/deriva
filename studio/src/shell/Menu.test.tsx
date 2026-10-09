import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Menu } from "./Menu";

function renderMenu(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Menu />
    </MemoryRouter>,
  );
}

describe("Menu", () => {
  it("lists the workspace and the six definition pages in three groups", () => {
    renderMenu();

    for (const label of ["Workspace", "Repositories", "General & file types", "Intermediate ontology", "Extraction config", "Output ontology", "Derivation config"]) {
      expect(screen.getByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
    }
    for (const group of ["Sources", "Intermediate", "Output"]) {
      expect(screen.getByText(group, { selector: ".menu-group" })).toBeInTheDocument();
    }
  });

  it("marks the current page", () => {
    renderMenu("/config/extraction");

    expect(screen.getByRole("link", { name: /Extraction config/ })).toHaveAttribute("aria-current", "page");
  });

  it("collapses to icons", async () => {
    renderMenu();
    const toggle = screen.getByRole("button", { name: /collapse menu/i });

    await userEvent.click(toggle);

    expect(screen.getByRole("navigation")).toHaveClass("collapsed");
    expect(screen.getByRole("button", { name: /expand menu/i })).toHaveAttribute("aria-expanded", "false");
  });
});
