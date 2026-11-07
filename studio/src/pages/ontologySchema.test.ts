import { describe, expect, it } from "vitest";

import type { IntermediateOntology, NodeType } from "../api/types";
import { labelBoxes, layoutSchema, schemaGraph, type SchemaColors, typeEdges } from "./ontologySchema";

const type = (name: string, group: string, count: number): NodeType => ({ name, group, count, description: "", properties: [], sample: {}, producers: [], consumers: [] });

const DATA: IntermediateOntology = {
  groups: ["structure", "code", "business", "deployment"],
  node_types: [type("Directory", "structure", 77), type("File", "structure", 574), type("Method", "code", 2135), type("TypeDefinition", "code", 1556), type("Lifecycle", "business", 0), type("Technology", "deployment", 19)],
  edge_types: [
    { name: "CONTAINS", count: 4306, pairs: [["Directory", "File"], ["File", "Method"], ["TypeDefinition", "Method"], ["Directory", "Directory"]] },
    { name: "REFERENCES", count: 918, pairs: [["TypeDefinition", "Method"]] },
    { name: "CONFIGURES", count: 14, pairs: [["File", "Technology"]] },
    { name: "CALLS", count: 1984, pairs: [["Method", "Method"]] },
  ],
  other_steps: [],
};

const COLORS: SchemaColors = { groups: { structure: "#b3a6ff", code: "#7fc4f5", business: "#f2d264", deployment: "#9bd88a" }, empty: "#8e96a3", edge: "#59606c" };
const ALL = { hiddenGroups: new Set<string>(), showEmpty: true, edgeType: null };

const byId = <T extends { id: string }>(items: T[]) => Object.fromEntries(items.map((item) => [item.id, item]));

describe("schemaGraph", () => {
  it("draws every type as a node coloured by its group and sized by its count; a type without nodes is small and faint", () => {
    const nodes = byId(schemaGraph(DATA, ALL, COLORS).nodes);

    expect(Object.keys(nodes).sort()).toEqual(["Directory", "File", "Lifecycle", "Method", "Technology", "TypeDefinition"]);
    expect(nodes.File).toMatchObject({ label: "File", color: "#b3a6ff", group: "structure", count: 574 });
    expect(nodes.Method.color).toBe("#7fc4f5");
    expect(nodes.Method.size as number).toBeGreaterThan(nodes.File.size as number);
    expect(nodes.File.size as number).toBeGreaterThan(nodes.Technology.size as number);
    expect(nodes.Lifecycle.color).toBe("#8e96a3");
    expect(nodes.Lifecycle.size as number).toBeLessThan(nodes.Technology.size as number);
  });

  it("joins the edge types between one pair of types into one labelled edge and keeps a type's edges to itself", () => {
    const edges = schemaGraph(DATA, ALL, COLORS).edges;
    const between = (source: string, target: string) => edges.filter((e) => e.source === source && e.target === target);

    expect(between("TypeDefinition", "Method")).toHaveLength(1);
    expect(between("TypeDefinition", "Method")[0].label).toBe("CONTAINS · REFERENCES");
    expect(between("Method", "Method")[0].label).toBe("CALLS");
    expect(between("Directory", "Directory")[0].label).toBe("CONTAINS");
    expect(new Set(edges.map((e) => e.id)).size).toBe(edges.length);
    // Thicker for the more common edge type
    expect(between("Directory", "File")[0].size as number).toBeGreaterThan(between("File", "Technology")[0].size as number);
  });

  it("leaves out hidden groups with their edges, types without nodes, and other edge types when asked", () => {
    const withoutCode = schemaGraph(DATA, { ...ALL, hiddenGroups: new Set(["code"]) }, COLORS);
    expect(withoutCode.nodes.map((n) => n.id)).not.toContain("Method");
    expect(withoutCode.edges.some((e) => e.source === "Method" || e.target === "Method")).toBe(false);

    expect(schemaGraph(DATA, { ...ALL, showEmpty: false }, COLORS).nodes.map((n) => n.id)).not.toContain("Lifecycle");

    const configures = schemaGraph(DATA, { ...ALL, edgeType: "CONFIGURES" }, COLORS);
    expect(configures.edges.map((e) => `${e.source}>${e.target}:${e.label}`)).toEqual(["File>Technology:CONFIGURES"]);
    expect(configures.nodes).toHaveLength(6);
  });

  it("places every type where it was when a filter hides others", () => {
    const all = byId(schemaGraph(DATA, ALL, COLORS).nodes);
    const some = byId(schemaGraph(DATA, { ...ALL, hiddenGroups: new Set(["code"]), showEmpty: false }, COLORS).nodes);

    expect([some.File.x, some.File.y]).toEqual([all.File.x, all.File.y]);
  });
});

describe("layoutSchema", () => {
  it("gives the same positions for the same ontology, spread apart", () => {
    const first = layoutSchema(DATA), second = layoutSchema(DATA);
    expect([...first]).toEqual([...second]);

    const points = [...first.values()];
    for (const [i, a] of points.entries()) {
      expect(Number.isFinite(a.x) && Number.isFinite(a.y)).toBe(true);
      for (const b of points.slice(i + 1)) expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThan(0.1);
    }
  });

  it("keeps a group's types closer to each other than to the other groups", () => {
    const at = layoutSchema(DATA);
    const distance = (a: string, b: string) => Math.hypot(at.get(a)!.x - at.get(b)!.x, at.get(a)!.y - at.get(b)!.y);

    expect(distance("Method", "TypeDefinition")).toBeLessThan(distance("Method", "Technology"));
  });

  it("keeps every type's label clear of the others around a hub, the same way every time", () => {
    // The intermediate ontology's own types with File as the hub: linked types of one group (Directory and
    // Repository, DataDomain and DataEntity) end up close together, and their labels met before the collision pass
    const types: [string, string, number][] = [
      ["BuildModule", "structure", 4], ["Directory", "structure", 80], ["File", "structure", 650], ["Module", "structure", 0], ["Repository", "structure", 1],
      ["ExternalDependency", "code", 60], ["Method", "code", 2700], ["Service", "code", 0], ["Test", "code", 0], ["TypeDefinition", "code", 2200],
      ["BusinessConcept", "business", 20], ["DataDomain", "business", 7], ["DataEntity", "business", 7], ["Lifecycle", "business", 0], ["LifecycleEvent", "business", 0], ["Role", "business", 0],
      ["DeployableUnit", "deployment", 2], ["Deployment", "deployment", 0], ["Environment", "deployment", 0], ["Software", "deployment", 4], ["Technology", "deployment", 15],
    ];
    const edge = (name: string, pairs: [string, string][]) => ({ name, count: 10, pairs });
    const hub: IntermediateOntology = {
      groups: ["structure", "code", "business", "deployment"],
      node_types: types.map(([name, group, count]) => type(name, group, count)),
      edge_types: [
        edge("BUILDS", [["DeployableUnit", "BuildModule"]]),
        edge("CALLS", [["Method", "Method"]]),
        edge("CONFIGURES", [["File", "Technology"]]),
        edge("CONTAINS", [["Directory", "Directory"], ["Directory", "File"], ["File", "Method"], ["File", "TypeDefinition"], ["Repository", "Directory"], ["Repository", "File"], ["TypeDefinition", "Method"]]),
        edge("IMPORTS", [["File", "File"]]),
        edge("INCLUDES", [["BuildModule", "File"], ["DataDomain", "DataEntity"], ["DataEntity", "TypeDefinition"], ["DeployableUnit", "File"]]),
        edge("INHERITS", [["TypeDefinition", "TypeDefinition"]]),
        edge("NAMED_IN", [["DataEntity", "File"]]),
        edge("NESTS", [["BuildModule", "BuildModule"]]),
        edge("REFERENCES", [["File", "BusinessConcept"], ["Method", "TypeDefinition"]]),
        edge("REPRESENTS", [["Directory", "Technology"]]),
        edge("SERVES", [["Software", "DeployableUnit"]]),
        edge("USES", [["File", "ExternalDependency"]]),
      ],
      other_steps: [],
    };

    const first = layoutSchema(hub);
    expect([...first]).toEqual([...layoutSchema(hub)]);
    const boxes = labelBoxes(first, hub);
    for (const [i, a] of boxes.entries()) {
      for (const b of boxes.slice(i + 1)) {
        const apart = a.x2 <= b.x1 || b.x2 <= a.x1 || a.y2 <= b.y1 || b.y2 <= a.y1;
        expect(apart, `${a.name} and ${b.name}`).toBe(true);
      }
    }
  });
});

describe("typeEdges", () => {
  it("lists a type's edges out, in and to itself, with the types at the other end", () => {
    expect(typeEdges(DATA, "File")).toEqual([
      { direction: "out", edge: "CONFIGURES", others: ["Technology"] },
      { direction: "in", edge: "CONTAINS", others: ["Directory"] },
      { direction: "out", edge: "CONTAINS", others: ["Method"] },
    ]);
    expect(typeEdges(DATA, "Method")).toEqual([
      { direction: "self", edge: "CALLS", others: ["Method"] },
      { direction: "in", edge: "CONTAINS", others: ["File", "TypeDefinition"] },
      { direction: "in", edge: "REFERENCES", others: ["TypeDefinition"] },
    ]);
    expect(typeEdges(DATA, "Lifecycle")).toEqual([]);
  });
});
