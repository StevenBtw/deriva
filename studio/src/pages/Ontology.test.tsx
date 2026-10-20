import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GraphView, IntermediateOntology, OutputOntology } from "../api/types";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ontology: { intermediate: vi.fn(), output: vi.fn() }, configs: { setEnabled: vi.fn() } };
});

// The graph widget as the page drives it: the view and settings it gets, the selection, a click on a node
const widget = vi.hoisted(() => ({ props: null as null | { view: GraphView; settings?: Record<string, unknown>; selected?: string | null } }));
vi.mock("../widgets/GraphWidget", () => ({
  GraphWidget: (props: { view: GraphView; settings?: Record<string, unknown>; selected?: string | null; onSelect?: (id: string | null) => void }) => {
    widget.props = props;
    return (
      <div data-testid="schema-graph" data-selected={props.selected ?? ""}>
        {props.view.nodes.map((n) => (
          <button key={n.id} type="button" onClick={() => props.onSelect?.(n.id)}>
            node {n.id}
          </button>
        ))}
        <button type="button" onClick={() => props.onSelect?.(null)}>
          stage
        </button>
      </div>
    );
  },
}));

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

const shownNodes = () => widget.props?.view.nodes.map((n) => n.id) ?? [];
const details = () => screen.getByRole("complementary");

async function openView(name: "Graph" | "Matrix" | "Cards") {
  await userEvent.click(await within(await screen.findByRole("group", { name: "Ontology view" })).findByRole("button", { name }));
}

describe("Intermediate ontology", () => {
  beforeEach(() => {
    widget.props = null;
    vi.mocked(ontology.intermediate).mockResolvedValue(INTERMEDIATE);
    vi.mocked(configs.setEnabled).mockResolvedValue({ name: "Technology", enabled: false });
  });

  it("opens on the schema graph: every type a node, edges with their types, placed by the page and drawn as arrows", async () => {
    render(<IntermediateOntologyPage />);

    await screen.findByTestId("schema-graph");
    expect(shownNodes()).toEqual(["Directory", "Lifecycle", "Technology"]);
    expect(widget.props?.view.edges).toEqual([expect.objectContaining({ source: "Directory", target: "Technology", label: "CONTAINS · CONFIGURES" })]);
    expect(widget.props?.settings).toMatchObject({ layout: "preset", edge_arrows: true, show_edge_labels: false, highlight_neighbors: true, show_query_input: false });
    expect(screen.getByText(/3 node types, 2 edge types/)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Enable DirectoryClassification" })).toBeInTheDocument();
  });

  it("shows the graph's overview until a type is selected, and the type when its node is clicked", async () => {
    render(<IntermediateOntologyPage />);
    expect(await screen.findByRole("heading", { name: "This graph" })).toBeInTheDocument();
    expect(details()).toHaveTextContent("3 nodes of 2 types, 6 edges of 2 types. 1 type has no nodes here.");

    await userEvent.click(screen.getByRole("button", { name: "node Technology" }));

    expect(within(details()).getByRole("heading", { name: "Technology" })).toBeInTheDocument();
    expect(details()).toHaveTextContent("Represents a technology infrastructure component in the graph.");
    expect(details()).toHaveTextContent("1 node");
    expect(within(details()).getByRole("switch", { name: "Enable Technology" })).toBeInTheDocument();
    expect(within(details()).getByText("Node")).toBeInTheDocument();
    expect(screen.getByTestId("schema-graph")).toHaveAttribute("data-selected", "Technology");
    // The selected type's edges carry their edge types' names
    expect(widget.props?.settings).toMatchObject({ show_edge_labels: true });

    await userEvent.click(screen.getByRole("button", { name: "stage" }));
    expect(screen.getByRole("heading", { name: "This graph" })).toBeInTheDocument();
    expect(widget.props?.settings).toMatchObject({ show_edge_labels: false });
  });

  it("lists a type's edges with the type at the other end, which opens on a click", async () => {
    render(<IntermediateOntologyPage />);
    await userEvent.click(await screen.findByRole("button", { name: "node Technology" }));

    const edges = within(details()).getByRole("table");
    expect(within(edges).getByRole("row", { name: /CONFIGURES Directory/ })).toHaveTextContent("←");
    expect(within(edges).getByRole("row", { name: /CONTAINS Directory/ })).toBeInTheDocument();

    await userEvent.click(within(edges).getAllByRole("button", { name: "Directory" })[0]);

    expect(within(details()).getByRole("heading", { name: "Directory" })).toBeInTheDocument();
    expect(screen.getByTestId("schema-graph")).toHaveAttribute("data-selected", "Directory");
  });

  it("shows a type without nodes with its description and the properties it can have, and closes", async () => {
    render(<IntermediateOntologyPage />);
    await userEvent.click(await screen.findByRole("button", { name: "node Lifecycle" }));

    expect(details()).toHaveTextContent("A business process from structure.");
    expect(details()).toHaveTextContent("name, states");
    expect(details()).toHaveTextContent("no nodes in this graph");
    expect(details()).toHaveTextContent("no extraction step of its own");
    expect(within(details()).queryByRole("button", { name: "Show a sample node" })).not.toBeInTheDocument();

    await userEvent.click(within(details()).getByRole("button", { name: "Close the details" }));
    expect(screen.getByRole("heading", { name: "This graph" })).toBeInTheDocument();
  });

  it("shows and hides a type's sample node", async () => {
    render(<IntermediateOntologyPage />);
    await userEvent.click(await screen.findByRole("button", { name: "node Technology" }));

    await userEvent.click(within(details()).getByRole("button", { name: "Show a sample node" }));
    expect(await screen.findByText(/tech::r::queue/)).toBeInTheDocument();

    await userEvent.click(within(details()).getByRole("button", { name: "Hide the sample node" }));
    expect(screen.queryByText(/tech::r::queue/)).not.toBeInTheDocument();
  });

  it("hides a group's types, types without nodes, and other edge types", async () => {
    render(<IntermediateOntologyPage />);
    const groups = await screen.findByRole("group", { name: "Groups" });

    await userEvent.click(within(groups).getByRole("button", { name: /Deployment 1/ }));
    expect(within(groups).getByRole("button", { name: /Deployment 1/ })).toHaveAttribute("aria-pressed", "false");
    expect(shownNodes()).toEqual(["Directory", "Lifecycle"]);
    expect(widget.props?.view.edges).toEqual([]);
    await userEvent.click(within(groups).getByRole("button", { name: /Deployment 1/ }));

    await userEvent.click(screen.getByRole("checkbox", { name: "Types without nodes" }));
    expect(shownNodes()).toEqual(["Directory", "Technology"]);

    await userEvent.selectOptions(screen.getByRole("combobox", { name: /Edges/ }), "CONFIGURES");
    expect(widget.props?.view.edges.map((e) => e.label)).toEqual(["CONFIGURES"]);
  });

  it("says so when no type matches the filters", async () => {
    render(<IntermediateOntologyPage />);
    const groups = await screen.findByRole("group", { name: "Groups" });

    for (const name of [/Structure/, /Code/, /Business/, /Deployment/]) await userEvent.click(within(groups).getByRole("button", { name }));

    expect(screen.getByText("No type matches these filters.")).toBeInTheDocument();
    expect(screen.queryByTestId("schema-graph")).not.toBeInTheDocument();
  });

  it("groups every node type in cards, also one the graph has none of, with its count and producing step", async () => {
    render(<IntermediateOntologyPage />);
    await openView("Cards");

    const structure = screen.getByRole("heading", { name: "Structure" }).closest(".card") as HTMLElement;
    const directory = within(structure).getByRole("button", { name: "Directory" }).closest("tr")!;
    expect(directory).toHaveTextContent("2");
    expect(within(directory).getByRole("switch", { name: "Enable Directory" })).toBeInTheDocument();
    const business = screen.getByRole("heading", { name: "Business" }).closest(".card") as HTMLElement;
    const lifecycle = within(business).getByRole("button", { name: "Lifecycle" }).closest("tr")!;
    expect(lifecycle).toHaveTextContent("0");
    expect(lifecycle).toHaveTextContent("no step");
    expect(screen.getByRole("heading", { name: "Code" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Deployment" })).toBeInTheDocument();
  });

  it("opens a type from its card, also from the keyboard, and keeps it selected in the graph", async () => {
    render(<IntermediateOntologyPage />);
    await openView("Cards");
    const deployment = screen.getByRole("heading", { name: "Deployment" }).closest(".card") as HTMLElement;
    const technology = within(deployment).getByRole("button", { name: "Technology" });

    technology.focus();
    await userEvent.keyboard("{Enter}");

    expect(within(details()).getByRole("heading", { name: "Technology" })).toBeInTheDocument();
    await openView("Graph");
    expect(screen.getByTestId("schema-graph")).toHaveAttribute("data-selected", "Technology");
  });

  it("shows the edge types with their codes and the edges between types as a matrix", async () => {
    render(<IntermediateOntologyPage />);
    await openView("Matrix");

    const edges = screen.getByRole("heading", { name: "Edge types" }).closest(".card") as HTMLElement;
    expect(within(edges).getByRole("row", { name: /CONT CONTAINS 4/ })).toBeInTheDocument();
    expect(within(edges).getByRole("row", { name: /CONF CONFIGURES 2/ })).toBeInTheDocument();
    const matrix = screen.getByRole("heading", { name: /Edges in this graph/ }).closest(".card") as HTMLElement;
    expect(within(matrix).getByRole("rowheader", { name: "Directory" })).toBeInTheDocument();
    expect(within(matrix).getByRole("columnheader", { name: "Technology" })).toBeInTheDocument();
    expect(within(matrix).getByTitle("Directory → Technology: CONTAINS, CONFIGURES")).toHaveTextContent("CONT CONF");

    await userEvent.selectOptions(screen.getByRole("combobox", { name: /Edges/ }), "CONFIGURES");
    expect(within(matrix).getByTitle("Directory → Technology: CONFIGURES")).toHaveTextContent("CONF");
  });

  it("switches the producing extraction step from the details and reloads the ontology", async () => {
    render(<IntermediateOntologyPage />);
    await userEvent.click(await screen.findByRole("button", { name: "node Technology" }));

    await userEvent.click(within(details()).getByRole("switch", { name: "Enable Technology" }));

    expect(configs.setEnabled).toHaveBeenCalledWith("extraction", "Technology", false);
    await waitFor(() => expect(ontology.intermediate).toHaveBeenCalledTimes(2));
    expect(within(details()).getByRole("heading", { name: "Technology" })).toBeInTheDocument();
  });

  it("offers a retry when the ontology could not be loaded", async () => {
    vi.mocked(ontology.intermediate).mockRejectedValueOnce(new Error("graph busy"));
    render(<IntermediateOntologyPage />);

    expect(await screen.findByText(/graph busy/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByTestId("schema-graph")).toBeInTheDocument();
    expect(screen.queryByText(/graph busy/)).not.toBeInTheDocument();
  });

  it("keeps the page when a switch fails and lets the message be dismissed", async () => {
    vi.mocked(configs.setEnabled).mockRejectedValueOnce(new Error("config is read only"));
    render(<IntermediateOntologyPage />);

    await userEvent.click(await screen.findByRole("switch", { name: "Enable DirectoryClassification" }));

    expect(await screen.findByText(/config is read only/)).toBeInTheDocument();
    expect(screen.getByTestId("schema-graph")).toBeInTheDocument();
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
