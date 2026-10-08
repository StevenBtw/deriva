import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IntermediateOntology, OutputOntology } from "../api/types";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ontology: { intermediate: vi.fn(), output: vi.fn() }, configs: { setEnabled: vi.fn() } };
});

vi.mock("../widgets/GraphWidget", () => ({
  GraphWidget: ({ view }: { view: { nodes: unknown[]; edges: unknown[] } }) => (
    <div data-testid="schema-graph">
      {view.nodes.length} types · {view.edges.length} edge kinds
    </div>
  ),
}));

import { configs, ontology } from "../api/client";
import { IntermediateOntologyPage, OutputOntologyPage } from "./Ontology";

const INTERMEDIATE: IntermediateOntology = {
  node_types: [
    {
      name: "Directory",
      count: 2,
      properties: ["id", "name", "path"],
      sample: { id: "dir::r::src", name: "src", path: "src" },
      producers: [{ name: "Directory", enabled: true, version: 2, method: "structural" }],
      consumers: ["ApplicationComponent"],
    },
    { name: "Technology", count: 1, properties: ["id", "techName"], sample: { id: "tech::r::queue", techName: "Queue" }, producers: [{ name: "Technology", enabled: true, version: 7, method: "llm" }], consumers: ["Node"] },
  ],
  edge_types: [{ name: "CONTAINS", count: 4, pairs: [["Directory", "Technology"]] }],
  other_steps: [{ name: "DirectoryClassification", enabled: true, version: 9, method: "llm" }],
};

const OUTPUT: OutputOntology = {
  element_types: [
    { name: "Node", layer: "Technology", count: 2, step: { enabled: true, version: 4 } },
    { name: "BusinessActor", layer: "Business", count: 0, step: null },
    { name: "ApplicationService", layer: "Application", count: 1, step: { enabled: false, version: 3 } },
  ],
  relationship_types: [{ name: "Serving", count: 2 }],
  rules: [{ source: "ApplicationService", target: "Node", direct: ["Serving"], derived: ["Flow"] }],
};

describe("Intermediate ontology", () => {
  beforeEach(() => {
    vi.mocked(ontology.intermediate).mockResolvedValue(INTERMEDIATE);
    vi.mocked(configs.setEnabled).mockResolvedValue({ name: "Technology", enabled: false });
  });

  it("lists node types with their producing and consuming steps and draws the schema", async () => {
    render(<IntermediateOntologyPage />);

    const row = (await screen.findByRole("cell", { name: "Technology" })).closest("tr")!;
    expect(row).toHaveTextContent("1");
    expect(row).toHaveTextContent("Node");
    expect(screen.getByTestId("schema-graph")).toHaveTextContent("2 types · 1 edge kinds");
    expect(screen.getByText(/DirectoryClassification/)).toBeInTheDocument();
  });

  it("switches the producing extraction step and shows a type's sample", async () => {
    render(<IntermediateOntologyPage />);
    const row = (await screen.findByRole("cell", { name: "Technology" })).closest("tr")!;

    await userEvent.click(within(row).getByRole("switch", { name: "Enable Technology" }));
    expect(configs.setEnabled).toHaveBeenCalledWith("extraction", "Technology", false);
    await waitFor(() => expect(ontology.intermediate).toHaveBeenCalledTimes(2));

    await userEvent.click(within(row).getByRole("cell", { name: "Technology" }));
    expect(await screen.findByText(/tech::r::queue/)).toBeInTheDocument();
  });
});

describe("Output ontology", () => {
  beforeEach(() => {
    vi.mocked(ontology.output).mockResolvedValue(OUTPUT);
    vi.mocked(configs.setEnabled).mockResolvedValue({ name: "ApplicationService", enabled: true });
  });

  it("groups element types by layer with their counts and derivation step", async () => {
    render(<OutputOntologyPage />);

    const technology = (await screen.findByText("Technology layer")).closest<HTMLElement>(".card")!;
    expect(within(technology).getByText("Node").closest("tr")).toHaveTextContent("v4");
    expect(screen.getByText("BusinessActor").closest("tr")).toHaveTextContent("no step");

    await userEvent.click(screen.getByRole("switch", { name: "Enable ApplicationService" }));
    expect(configs.setEnabled).toHaveBeenCalledWith("derivation", "ApplicationService", true);
  });

  it("shows relationship counts and the allowed relationships per pair", async () => {
    render(<OutputOntologyPage />);

    expect(await screen.findByText("Serving")).toBeInTheDocument();
    const cell = screen.getByTitle("ApplicationService → Node: direct Serving; derived Flow");
    expect(cell).toHaveTextContent("V");
  });
});
