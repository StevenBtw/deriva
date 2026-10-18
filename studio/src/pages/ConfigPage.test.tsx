import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, configs: { list: vi.fn(), save: vi.fn(), setEnabled: vi.fn(), versions: vi.fn(), scan: vi.fn(), dryRun: vi.fn() } };
});

vi.mock("../components/CodeEditor", () => ({
  CodeEditor: ({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) => (
    <textarea aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));

import { ApiError, configs } from "../api/client";
import { ConfigPage } from "./ConfigPage";

const ROWS = [
  { name: "DirectoryClassification", sequence: 11, enabled: true, instruction: "Classify each directory.", example: '{"classifications": []}', version: 9 },
  { name: "Test", sequence: 14, enabled: false, instruction: "", example: "", version: null },
];

describe("ConfigPage", () => {
  beforeEach(() => {
    vi.mocked(configs.list).mockResolvedValue(ROWS);
    vi.mocked(configs.save).mockResolvedValue({ name: "DirectoryClassification", old_version: 9, new_version: 10 });
    vi.mocked(configs.setEnabled).mockResolvedValue({ name: "Test", enabled: true });
    vi.mocked(configs.scan).mockResolvedValue({ available: true, findings: [] });
    vi.mocked(configs.versions).mockResolvedValue([
      { version: 9, is_active: true, enabled: true, sequence: 11, instruction: "Classify each directory.", example: "{}", params: null, batch_size: 1, created_at: "2026-10-08T01:00:00" },
      { version: 8, is_active: false, enabled: true, sequence: 11, instruction: "Classify directories.", example: "{}", params: null, batch_size: 1, created_at: "2026-10-01T01:00:00" },
    ]);
  });

  it("lists steps with sequence, enabled switch and version", async () => {
    render(<ConfigPage stepType="extraction" title="Extraction config" />);

    expect(await screen.findByRole("cell", { name: "DirectoryClassification" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "v9" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Enable Test" })).toHaveAttribute("aria-checked", "false");
  });

  it("loads the selected step into the editors and saves only what changed", async () => {
    render(<ConfigPage stepType="extraction" title="Extraction config" />);
    await screen.findByRole("cell", { name: "DirectoryClassification" });

    const instruction = await screen.findByLabelText("Instruction");
    expect(instruction).toHaveValue("Classify each directory.");
    await userEvent.clear(instruction);
    await userEvent.type(instruction, "Classify every directory.");
    await userEvent.click(screen.getByRole("button", { name: /Save as new version/ }));

    await waitFor(() => expect(configs.save).toHaveBeenCalledWith("extraction", "DirectoryClassification", { instruction: "Classify every directory." }));
    expect(configs.scan).toHaveBeenCalledWith({ instruction: "Classify every directory." });
    expect(await screen.findByText(/Saved as v10/)).toBeInTheDocument();
    await waitFor(() => expect(configs.list).toHaveBeenCalledTimes(2));
  });

  it("heads each derivation phase, since step numbers start again per phase", async () => {
    vi.mocked(configs.list).mockResolvedValue([
      { name: "pagerank", phase: "prep", llm: false, sequence: 5, enabled: true, instruction: null, example: null, version: 3 },
      { name: "ApplicationComponent", phase: "generate", llm: true, sequence: 1, enabled: true, instruction: "Name it.", example: "", version: 7 },
      { name: "Node", phase: "generate", llm: true, sequence: 2, enabled: true, instruction: "Name it.", example: "", version: 2 },
      { name: "joint_consistency", phase: "refine", llm: false, sequence: 8, enabled: true, instruction: null, example: null, version: 4 },
    ]);
    render(<ConfigPage stepType="derivation" title="Derivation config" />);

    await screen.findByRole("cell", { name: "pagerank" });
    const headers = screen.getAllByRole("rowheader").map((h) => h.textContent);
    expect(headers).toEqual(["prep", "generate", "refine"]);
  });

  it("shows no prompt editors for a step without LLM calls and without texts", async () => {
    vi.mocked(configs.list).mockResolvedValue([
      { name: "pagerank", phase: "prep", llm: false, sequence: 5, enabled: true, instruction: null, example: null, params: '{"damping": 0.85}', version: 3 },
      { name: "orphan_elements", phase: "refine", llm: false, sequence: 1, enabled: true, instruction: "Kept text.", example: null, version: 2 },
    ]);
    render(<ConfigPage stepType="derivation" title="Derivation config" />);

    expect(await screen.findByLabelText("Params")).toHaveValue('{"damping": 0.85}');
    expect(screen.queryByRole("tab", { name: "Instruction" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Example" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("cell", { name: "orphan_elements" }));
    expect(await screen.findByRole("tab", { name: "Instruction" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Example" })).not.toBeInTheDocument();
  });

  it("explains the overfit scan without internal rule numbers", async () => {
    render(<ConfigPage stepType="derivation" title="Derivation config" />);
    expect(await screen.findByText("Changed texts are scanned for overfitting before they are saved.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/rule \d/);
  });

  it("switches a step on or off", async () => {
    render(<ConfigPage stepType="extraction" title="Extraction config" />);

    await userEvent.click(await screen.findByRole("switch", { name: "Enable Test" }));

    expect(configs.setEnabled).toHaveBeenCalledWith("extraction", "Test", true);
  });

  it("keeps the edited text when saving fails", async () => {
    vi.mocked(configs.save).mockRejectedValue(new ApiError(404, "Config not found for DirectoryClassification", {}));
    render(<ConfigPage stepType="extraction" title="Extraction config" />);
    const instruction = await screen.findByLabelText("Instruction");
    await userEvent.type(instruction, " More.");

    await userEvent.click(screen.getByRole("button", { name: /Save as new version/ }));

    expect(await screen.findByText(/Config not found/)).toBeInTheDocument();
    expect(screen.getByLabelText("Instruction")).toHaveValue("Classify each directory. More.");
  });

  it("asks before leaving unsaved changes", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<ConfigPage stepType="extraction" title="Extraction config" />);
    const instruction = await screen.findByLabelText("Instruction");
    await userEvent.type(instruction, "!");

    await userEvent.click(screen.getByRole("cell", { name: "Test" }));

    expect(confirm).toHaveBeenCalled();
    expect(screen.getByLabelText("Instruction")).toHaveValue("Classify each directory.!");
  });

  it("holds a save with overfit findings until it is confirmed", async () => {
    vi.mocked(configs.scan).mockResolvedValue({ available: true, findings: [{ field: "instruction", finding: "'widgetco' (repo term)" }] });
    render(<ConfigPage stepType="extraction" title="Extraction config" />);
    const instruction = await screen.findByLabelText("Instruction");
    await userEvent.type(instruction, " Like WidgetCo.");

    await userEvent.click(screen.getByRole("button", { name: /Save as new version/ }));

    expect(await screen.findByText(/'widgetco' \(repo term\)/)).toBeInTheDocument();
    expect(configs.save).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Save anyway" }));
    await waitFor(() => expect(configs.save).toHaveBeenCalled());
  });

  it("saves once and locks the editor while the scan and save run", async () => {
    let finishScan: (value: { available: boolean; findings: never[] }) => void = () => {};
    vi.mocked(configs.scan).mockImplementation(() => new Promise((resolve) => (finishScan = resolve)));
    render(<ConfigPage stepType="extraction" title="Extraction config" />);
    const instruction = await screen.findByLabelText("Instruction");
    await userEvent.type(instruction, "!");

    const button = screen.getByRole("button", { name: /Save as new version/ });
    await userEvent.click(button);
    expect(button).toBeDisabled();
    await userEvent.type(instruction, "?");
    expect(instruction).toHaveValue("Classify each directory.!");
    finishScan({ available: true, findings: [] });

    await waitFor(() => expect(configs.save).toHaveBeenCalledTimes(1));
    expect(configs.save).toHaveBeenCalledWith("extraction", "DirectoryClassification", { instruction: "Classify each directory.!" });
  });

  it("asks before switching off a step with unsaved changes", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<ConfigPage stepType="extraction" title="Extraction config" />);
    await userEvent.type(await screen.findByLabelText("Instruction"), "!");

    await userEvent.click(screen.getByRole("switch", { name: "Enable DirectoryClassification" }));

    expect(confirm).toHaveBeenCalled();
    expect(configs.setEnabled).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Instruction")).toHaveValue("Classify each directory.!");
    confirm.mockRestore();
  });

  it("history shows batch size and the settings a version changed", async () => {
    vi.mocked(configs.versions).mockResolvedValue([
      { version: 9, is_active: true, enabled: true, sequence: 11, instruction: "Classify each directory.", example: '{"classifications": []}', params: null, batch_size: 1, temperature: 0, max_tokens: null, created_at: "2026-10-08T01:00:00" },
      { version: 8, is_active: false, enabled: true, sequence: 11, instruction: "Classify each directory.", example: '{"classifications": []}', params: null, batch_size: 4, temperature: 0.2, max_tokens: null, created_at: "2026-10-01T01:00:00" },
    ]);
    render(<ConfigPage stepType="extraction" title="Extraction config" />);
    await screen.findByLabelText("Instruction");
    await userEvent.click(screen.getByRole("tab", { name: "History" }));
    await userEvent.click(await screen.findByRole("button", { name: /v8/ }));

    expect(screen.getByText("+ 4")).toBeInTheDocument();
    expect(screen.getByText("- Temperature: 0")).toBeInTheDocument();
    expect(screen.getByText("+ Temperature: 0.2")).toBeInTheDocument();
  });

  it("edits params as JSON and refuses anything but an object", async () => {
    render(<ConfigPage stepType="extraction" title="Extraction config" />);
    await screen.findByLabelText("Instruction");
    await userEvent.click(screen.getByRole("tab", { name: "Params" }));

    // user-event types "[[" as one literal "[": the draft is the valid JSON array [1], no object
    await userEvent.type(screen.getByLabelText("Params"), "[[1]");
    expect(screen.getByLabelText("Params")).toHaveValue("[1]");
    await userEvent.click(screen.getByRole("button", { name: /Save as new version/ }));

    expect(await screen.findByText(/params must be a JSON object/)).toBeInTheDocument();
    expect(configs.save).not.toHaveBeenCalled();
  });

  it("changes the batch size", async () => {
    render(<ConfigPage stepType="extraction" title="Extraction config" />);
    const batch = await screen.findByLabelText("Batch size");

    await userEvent.clear(batch);
    await userEvent.type(batch, "4");
    await userEvent.click(screen.getByRole("button", { name: /Save as new version/ }));

    await waitFor(() => expect(configs.save).toHaveBeenCalledWith("extraction", "DirectoryClassification", { batch_size: 4 }));
  });

  it("lists the versions and shows what an earlier one changed", async () => {
    render(<ConfigPage stepType="extraction" title="Extraction config" />);
    await screen.findByLabelText("Instruction");

    await userEvent.click(screen.getByRole("tab", { name: "History" }));
    await userEvent.click(await screen.findByRole("button", { name: /v8/ }));

    expect(configs.versions).toHaveBeenCalledWith("extraction", "DirectoryClassification");
    expect(screen.getByText("- Classify each directory.")).toBeInTheDocument();
    expect(screen.getByText("+ Classify directories.")).toBeInTheDocument();
  });

  it("dry-runs a derivation step's candidate query without the LLM", async () => {
    vi.mocked(configs.list).mockResolvedValue([
      { name: "Node", sequence: 3, enabled: true, instruction: "Pick nodes.", example: "", version: 4, input_graph_query: "MATCH (n:Graph:Technology) RETURN n", batch_size: 10, params: null },
    ]);
    vi.mocked(configs.dryRun).mockResolvedValue({ count: 3, rows: [{ n: { labels: ["Technology"], id: "tech::r::queue" } }] });
    render(<ConfigPage stepType="derivation" title="Derivation config" />);
    await screen.findByLabelText("Instruction");

    await userEvent.click(screen.getByRole("tab", { name: "Candidate query" }));
    expect(screen.getByLabelText("Candidate query")).toHaveValue("MATCH (n:Graph:Technology) RETURN n");
    await userEvent.click(screen.getByRole("button", { name: /Dry run/ }));

    expect(configs.dryRun).toHaveBeenCalledWith("Node", undefined);
    expect(await screen.findByText(/3 candidates/)).toBeInTheDocument();
    expect(screen.getByText(/tech::r::queue/)).toBeInTheDocument();
  });
});
