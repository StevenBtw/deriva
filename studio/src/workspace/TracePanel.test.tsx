import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, trace: { element: vi.fn() } };
});

import { trace } from "../api/client";
import type { Trace } from "../api/types";
import { TracePanel } from "./TracePanel";

const README = ["![Logo](../docs/logo.png) Service: Order Service", "Order Service keeps the orders and their state, from the first draft to the last change.", "To build it, install the toolchain the manifest names."];

const TRACE: Trace = {
  element: { identifier: "ac_order_service", name: "Order Service", element_type: "ApplicationComponent", properties: {} },
  sources: [
    {
      id: "unit::app::order-service",
      type: "DeployableUnit",
      name: "order-service",
      properties: {
        id: "unit::app::order-service",
        extractStep: "DeployableUnit",
        in_degree: 6,
        pagerank: 0.0049435540588992685,
        readmeLines: README,
        evidence: ["container: app/order-service/Dockerfile", "manifest: app/order-service/pom.xml", "build: app/order-service/pom.xml"],
      },
    },
  ],
  relationships: [],
  calls: [],
};

describe("TracePanel", () => {
  beforeEach(() => {
    vi.mocked(trace.element).mockResolvedValue(TRACE);
  });

  it("lists a source's short properties on one line, rounded, and folds the long ones away", async () => {
    render(<TracePanel elementId="ac_order_service" runId={null} />);

    // Short values in one line, a float to four significant digits; the id is the source line's own
    const line = await screen.findByText(/extractStep: DeployableUnit/);
    expect(line).toHaveTextContent("extractStep: DeployableUnit · in_degree: 6 · pagerank: 0.004944");
    expect(line).not.toHaveTextContent("readmeLines");
    // A long value is a folded line named by its key and size, its items one per line when unfolded
    const readme = screen.getByText("readmeLines (3 items)");
    expect(screen.getByText("evidence (3 items)")).toBeInTheDocument();
    expect(readme.closest("details")).not.toHaveAttribute("open");
    await userEvent.click(readme);
    expect(readme.closest("details")).toHaveTextContent("Order Service keeps the orders and their state, from the first draft to the last change.");
  });
});
