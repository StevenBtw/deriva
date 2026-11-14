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
  it("draws the pipeline entries with the ring mark, one ring per stage as on deriva.dev", () => {
    renderMenu();
    const stage = (label: string) => screen.getByRole("link", { name: new RegExp(label) }).querySelector("svg.ring-icon")?.getAttribute("data-stage");

    expect(stage("Repositories")).toBe("outer");
    expect(stage("Intermediate ontology")).toBe("second");
    expect(stage("Output ontology")).toBe("inner");
    // The model (the ArchiMate export) is the pipeline's last stage: the core, in a group of its own
    expect(stage("Export config")).toBe("core");
    expect(screen.getByRole("link", { name: /Export config/ })).toHaveAttribute("href", "/config/export");
    // The workspace is the start page: a home icon, not a ring
    const workspace = screen.getByRole("link", { name: /Workspace/ });
    expect(workspace.querySelector("svg.ring-icon")).toBeNull();
    expect(workspace.querySelector("svg.home-icon")).not.toBeNull();
  });

  it("gives both config pages the same pen icon", () => {
    renderMenu();
    const icon = (label: string) => screen.getByRole("link", { name: new RegExp(label) }).querySelector(".menu-icon")?.textContent;

    expect(icon("Extraction config")).toBe("✎");
    expect(icon("Derivation config")).toBe("✎");
  });

  it("lists the workspace and the seven definition pages in four groups", () => {
    renderMenu();

    for (const label of ["Workspace", "Repositories", "General & file types", "Intermediate ontology", "Extraction config", "Output ontology", "Derivation config", "Export config"]) {
      expect(screen.getByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
    }
    for (const group of ["Sources", "Intermediate", "Output", "Model"]) {
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
