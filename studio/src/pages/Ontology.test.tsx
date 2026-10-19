import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IntermediateOntology, OutputOntology } from "../api/types";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ontology: { intermediate: vi.fn(), output: vi.fn() }, configs: { setEnabled: vi.fn() } };
});

import { configs, ontology } from "../api/client";
import { IntermediateOntologyPage, OutputOntologyPage } from "./Ontology";

const INTERMEDIATE: IntermediateOntology = {
  groups: ["structure", "code", "business", "deployment"],
  node_types: [
    {
      name: "Directory",
      group: "structure",
      description: "Represents a directory in the graph.",
      count: 2,
      properties: ["id", "name", "path"],
      sample: { id: "dir::r::src", name: "src", path: "src" },
      producers: [{ name: "Directory", enabled: true, version: 2, method: "structural" }],
      consumers: ["ApplicationComponent"],
    },
    {
      name: "Lifecycle",
      group: "business",
      description: "A business process from structure.",
      count: 0,
      properties: ["name", "states"],
      sample: {},
      producers: [],
      consumers: [],
    },
    {
      name: "Technology",
      group: "deployment",
      description: "Represents a technology infrastructure component in the graph.",
      count: 1,
      properties: ["id", "techName"],
      sample: { id: "tech::r::queue", techName: "Queue" },
      producers: [{ name: "Technology", enabled: true, version: 7, method: "llm" }],
      consumers: ["Node"],
    },
  ],
  edge_types: [
    { name: "CONTAINS", count: 4, pairs: [["Directory", "Technology"]] },
    { name: "CONFIGURES", count: 2, pairs: [["Directory", "Technology"]] },
  ],
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

  it("groups every node type, also one the graph has none of, with its count and producing step", async () => {
    render(<IntermediateOntologyPage />);

    const structure = (await screen.findByRole("heading", { name: "Structure" })).closest(".card") as HTMLElement;
    const directory = within(structure).getByRole("button", { name: "Directory" }).closest("tr")!;
    expect(directory).toHaveTextContent("2");
    expect(within(directory).getByRole("switch", { name: "Enable Directory" })).toBeInTheDocument();
    const business = screen.getByRole("heading", { name: "Business" }).closest(".card") as HTMLElement;
    const lifecycle = within(business).getByRole("button", { name: "Lifecycle" }).closest("tr")!;
    expect(lifecycle).toHaveTextContent("0");
    expect(lifecycle).toHaveTextContent("no step");
    expect(screen.getByRole("heading", { name: "Code" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Deployment" })).toBeInTheDocument();
    expect(screen.getByText(/DirectoryClassification/)).toBeInTheDocument();
  });

  it("shows the edge types with their codes and the edges between types as a matrix", async () => {
    render(<IntermediateOntologyPage />);

    const edges = (await screen.findByRole("heading", { name: "Edge types" })).closest(".card") as HTMLElement;
    expect(within(edges).getByRole("row", { name: /CONT CONTAINS 4/ })).toBeInTheDocument();
    expect(within(edges).getByRole("row", { name: /CONF CONFIGURES 2/ })).toBeInTheDocument();
    const matrix = screen.getByRole("heading", { name: /Edges in this graph/ }).closest(".card") as HTMLElement;
    expect(within(matrix).getByRole("rowheader", { name: "Directory" })).toBeInTheDocument();
    expect(within(matrix).getByRole("columnheader", { name: "Technology" })).toBeInTheDocument();
    const cell = within(matrix).getByTitle("Directory → Technology: CONTAINS, CONFIGURES");
    expect(cell).toHaveTextContent("CONT CONF");
  });

  it("shows a type without nodes with its description and the properties it can have", async () => {
    render(<IntermediateOntologyPage />);

    await userEvent.click(await screen.findByRole("button", { name: "Lifecycle" }));

    const details = screen.getByRole("heading", { name: "Lifecycle" }).closest(".card") as HTMLElement;
    expect(details).toHaveTextContent("A business process from structure.");
    expect(details).toHaveTextContent("name, states");
    expect(details).toHaveTextContent("no nodes in this graph");
  });

  it("switches the producing extraction step and shows a type's sample", async () => {
    render(<IntermediateOntologyPage />);
    const row = (await screen.findByRole("button", { name: "Technology" })).closest("tr")!;

    await userEvent.click(within(row).getByRole("switch", { name: "Enable Technology" }));
    expect(configs.setEnabled).toHaveBeenCalledWith("extraction", "Technology", false);
    await waitFor(() => expect(ontology.intermediate).toHaveBeenCalledTimes(2));

    await userEvent.click(within(row).getByRole("button", { name: "Technology" }));
    expect(await screen.findByText(/tech::r::queue/)).toBeInTheDocument();
  });

  it("opens a node type from the keyboard", async () => {
    render(<IntermediateOntologyPage />);
    const technology = await screen.findByRole("button", { name: "Technology" });

    technology.focus();
    await userEvent.keyboard("{Enter}");

    expect(await screen.findByText(/tech::r::queue/)).toBeInTheDocument();
  });

  it("offers a retry when the ontology could not be loaded", async () => {
    vi.mocked(ontology.intermediate).mockRejectedValueOnce(new Error("graph busy"));
    render(<IntermediateOntologyPage />);

    expect(await screen.findByText(/graph busy/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("button", { name: "Technology" })).toBeInTheDocument();
    expect(screen.queryByText(/graph busy/)).not.toBeInTheDocument();
  });

  it("keeps the page when a switch fails and lets the message be dismissed", async () => {
    vi.mocked(configs.setEnabled).mockRejectedValueOnce(new Error("config is read only"));
    render(<IntermediateOntologyPage />);
    const row = (await screen.findByRole("button", { name: "Technology" })).closest("tr")!;

    await userEvent.click(within(row).getByRole("switch", { name: "Enable Technology" }));

    expect(await screen.findByText(/config is read only/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Technology" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText(/config is read only/)).not.toBeInTheDocument();
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

  it("keeps the layer in the matrix headers, so same-named types of two layers stay apart", async () => {
    vi.mocked(ontology.output).mockResolvedValue({
      ...OUTPUT,
      rules: [
        { source: "Node", target: "ApplicationService", direct: ["Serving"], derived: [] },
        { source: "Node", target: "TechnologyService", direct: ["Realization"], derived: [] },
      ],
    });
    render(<OutputOntologyPage />);

    const headers = (await screen.findAllByRole("columnheader")).map((h) => h.textContent);
    expect(headers).toContain("A·Service");
    expect(headers).toContain("T·Service");
  });

  it("abbreviates the matrix rows like its columns, with the full type on hover, so the matrix fits", async () => {
    render(<OutputOntologyPage />);

    const row = await screen.findByRole("rowheader", { name: "A·Service" });
    expect(row).toHaveAttribute("title", "ApplicationService");
  });
});
