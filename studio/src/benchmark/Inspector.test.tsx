import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { InspectorView } from "../api/types";

const received: unknown[][] = [];

vi.mock("../widgets/ArchimateWidget", () => ({
  ArchimateWidget: ({ elements }: { elements: unknown[] }) => {
    received.push(elements);
    return <div data-testid="archimate">{elements.length} elements</div>;
  },
}));

import { Inspector } from "./Inspector";

const element = (run: string, identifier: string, name: string) => ({
  run,
  identifier,
  name,
  type: "ApplicationComponent",
  layer: "Application",
  source: `dir::r::${identifier}`,
  by_source: `dir::r::${identifier}`,
  by_name: name.toLowerCase(),
});

const VIEW: InspectorView = {
  repository: "r",
  runs: ["s1/1", "s2/1"],
  elements: [element("s1/1", "ac_core", "Core"), element("s2/1", "ac_core", "Core"), element("s1/1", "ac_cli", "CLI")],
  relationships: [],
  causes: {},
};

describe("Inspector", () => {
  it("lets an element be picked from the keyboard", async () => {
    const onSelect = vi.fn();
    render(<Inspector view={VIEW} onSelect={onSelect} />);

    const core = screen.getByRole("button", { name: /Core/ });
    core.focus();
    await userEvent.keyboard("{Enter}");

    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ name: "Core" }));
  });

  it("groups differences by what differs when the flip analysis names no cause", async () => {
    const view: InspectorView = {
      ...VIEW,
      elements: [
        element("s1/1", "ac_core", "Core"),
        element("s2/1", "ac_core", "Core"),
        element("s1/1", "ac_cli", "CLI"),
        { ...element("s1/1", "ac_api", "Policy API"), by_source: "dir::r::api", source: "dir::r::api" },
        { ...element("s2/1", "ac_api", "Policy Service"), by_source: "dir::r::api", source: "dir::r::api", by_name: "policy service" },
      ],
    };
    render(<Inspector view={view} />);

    await userEvent.click(screen.getByRole("button", { name: "by cause" }));

    expect(screen.getByText("name differs · 1")).toBeInTheDocument();
    expect(screen.getByText("not in every run · 1")).toBeInTheDocument();
    expect(screen.getByText("Stable · 1")).toBeInTheDocument();
    expect(screen.queryByText(/^other/)).not.toBeInTheDocument();
    expect(screen.getByText(/2 of 3 elements differ, matched by source/)).toBeInTheDocument();
  });

  it("keeps a cause the flip analysis found", async () => {
    render(<Inspector view={{ ...VIEW, causes: { "dir::r::ac_cli": "candidate dropped" } }} />);

    await userEvent.click(screen.getByRole("button", { name: "by cause" }));

    expect(screen.getByText("candidate dropped · 1")).toBeInTheDocument();
  });

  it("falls back to all runs when a new view has not the run that was shown", async () => {
    const { rerender } = render(<Inspector view={VIEW} />);
    await userEvent.click(screen.getByRole("button", { name: "s2/1" }));

    rerender(<Inspector view={{ ...VIEW, runs: ["s3/1", "s4/1"], elements: VIEW.elements.map((e) => ({ ...e, run: e.run.replace("s1", "s3").replace("s2", "s4") })) }} />);

    expect(screen.getByRole("button", { name: "All runs" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/All 2 runs/)).toBeInTheDocument();
  });
});

describe("Inspector diagram", () => {
  it("keeps the diagram data when the page re-renders with the same view, so a zoomed or panned diagram stays put", async () => {
    const { rerender } = render(<Inspector view={VIEW} />);
    await userEvent.click(screen.getByRole("button", { name: "Diagram" }));
    const before = received.length;

    // A parent re-render (the shell polls the server status every 10 s) with the same data
    rerender(<Inspector view={VIEW} />);
    rerender(<Inspector view={VIEW} />);

    expect(received.length).toBeGreaterThan(before);
    expect(new Set(received.slice(before - 1))).toHaveProperty("size", 1);
  });
});
