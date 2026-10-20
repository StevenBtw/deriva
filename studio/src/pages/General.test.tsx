import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    settings: { get: vi.fn(), set: vi.fn() },
    fileTypes: { list: vi.fn(), add: vi.fn(), update: vi.fn(), remove: vi.fn() },
    modelConfigs: { list: vi.fn(), save: vi.fn(), remove: vi.fn(), test: vi.fn() },
  };
});

import { ApiError, fileTypes, modelConfigs, settings } from "../api/client";
import { General } from "./General";

describe("General", () => {
  beforeEach(() => {
    vi.mocked(settings.get).mockImplementation(async (key: string) => ({ key, value: key === "excluded_directories" ? '["node_modules", ".git"]' : "true" }));
    vi.mocked(settings.set).mockImplementation(async (key: string, value: string) => ({ key, value }));
    vi.mocked(fileTypes.list).mockResolvedValue({
      file_types: [
        { extension: ".java", file_type: "source", subtype: "java" },
        { extension: ".md", file_type: "docs", subtype: "markdown" },
      ],
      stats: { source: 1, docs: 1 },
    });
    vi.mocked(fileTypes.add).mockResolvedValue({ extension: ".rs", file_type: "source", subtype: "rust" });
    vi.mocked(fileTypes.update).mockResolvedValue({ extension: ".md", file_type: "docs", subtype: "md" });
    vi.mocked(fileTypes.remove).mockResolvedValue({ extension: ".md", deleted: true });
    vi.mocked(modelConfigs.list).mockResolvedValue([
      { name: "anthropic-haiku", provider: "anthropic", model: "claude-haiku", url: null, key: "sk-...abcd", key_env: null },
    ]);
    vi.mocked(modelConfigs.save).mockResolvedValue({ name: "x", saved: true });
    vi.mocked(modelConfigs.remove).mockResolvedValue(null);
  });

  it("edits excluded directories as chips and saves them as a JSON list", async () => {
    render(<General />);
    expect(await screen.findByText("node_modules")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Remove .git" }));
    await userEvent.type(screen.getByLabelText("Add excluded directory"), "dist{enter}");
    await userEvent.click(screen.getByRole("button", { name: /Save settings/ }));

    expect(settings.set).toHaveBeenCalledWith("excluded_directories", '["node_modules","dist"]');
  });

  it("starts from the built-in list while the setting is not set", async () => {
    vi.mocked(settings.get).mockImplementation(async (key: string) => ({ key, value: null, default: key === "excluded_directories" ? '[".git", "node_modules"]' : null }));
    render(<General />);

    expect(await screen.findByText(".git")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Add excluded directory"), "dist{enter}");
    await userEvent.click(screen.getByRole("button", { name: /Save settings/ }));

    expect(settings.set).toHaveBeenCalledWith("excluded_directories", '[".git","node_modules","dist"]');
  });

  it("lets a stored value that is no list of names be replaced", async () => {
    vi.mocked(settings.get).mockImplementation(async (key: string) => ({ key, value: key === "excluded_directories" ? "{}" : null }));
    render(<General />);

    expect(await screen.findByText(/not a JSON list/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Add excluded directory"), "dist{enter}");
    await userEvent.click(screen.getByRole("button", { name: /Save settings/ }));

    expect(settings.set).toHaveBeenCalledWith("excluded_directories", '["dist"]');
  });

  it("lets deriva-dev switch off that full derivation runs start from an empty model", async () => {
    vi.mocked(settings.get).mockImplementation(async (key: string) => ({ key, value: key === "excluded_directories" ? "[]" : null }));
    render(<General benchmark />);

    const toggle = await screen.findByRole("checkbox", { name: "Full derivation runs start from an empty model" });
    await waitFor(() => expect(toggle).toBeChecked());
    await userEvent.click(toggle);

    await waitFor(() => expect(settings.set).toHaveBeenCalledWith("derivation_clear_model", "false"));
    expect(toggle).not.toBeChecked();
  });

  it("sets how many nodes the graph views sample, from the built-in 300", async () => {
    vi.mocked(settings.get).mockImplementation(async (key: string) => ({ key, value: key === "excluded_directories" ? "[]" : null, default: key === "graph_view_nodes" ? "300" : null }));
    render(<General />);
    const count = await screen.findByRole("spinbutton", { name: "Nodes in the graph views" });
    await waitFor(() => expect(count).toHaveValue(300));

    await userEvent.clear(count);
    await userEvent.type(count, "1200");
    await userEvent.click(screen.getByRole("button", { name: "Save the node count" }));

    expect(settings.set).toHaveBeenCalledWith("graph_view_nodes", "1200");
    expect(await screen.findByText(/Saved: the graph views now sample 1,200 nodes/)).toBeInTheDocument();
  });

  it("says why a node count is refused and keeps what was typed", async () => {
    vi.mocked(settings.get).mockImplementation(async (key: string) => ({ key, value: key === "excluded_directories" ? "[]" : key === "graph_view_nodes" ? "800" : null }));
    vi.mocked(settings.set).mockRejectedValueOnce(new Error("graph_view_nodes must be a whole number from 50 to 5000, not '9000'"));
    render(<General />);
    const count = await screen.findByRole("spinbutton", { name: "Nodes in the graph views" });
    await waitFor(() => expect(count).toHaveValue(800));

    await userEvent.clear(count);
    await userEvent.type(count, "9000");
    await userEvent.click(screen.getByRole("button", { name: "Save the node count" }));

    expect(await screen.findByText(/from 50 to 5000/)).toBeInTheDocument();
    expect(count).toHaveValue(9000);
  });

  it("shows the stored setting and has no switch without benchmarking", async () => {
    vi.mocked(settings.get).mockImplementation(async (key: string) => ({ key, value: key === "excluded_directories" ? "[]" : "false" }));
    const { unmount } = render(<General benchmark />);
    const toggle = await screen.findByRole("checkbox", { name: "Full derivation runs start from an empty model" });
    await waitFor(() => expect(toggle).not.toBeChecked());
    unmount();

    render(<General benchmark={false} />);
    await screen.findByRole("heading", { name: "Settings" });
    expect(screen.queryByRole("checkbox", { name: "Full derivation runs start from an empty model" })).not.toBeInTheDocument();
  });

  it("lists file types with a filter", async () => {
    render(<General />);
    expect(await screen.findByRole("cell", { name: ".java" })).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Filter file types"), "mark");

    expect(screen.queryByRole("cell", { name: ".java" })).not.toBeInTheDocument();
    expect(screen.getByRole("cell", { name: ".md" })).toBeInTheDocument();
  });

  it("adds a file type and reports a duplicate", async () => {
    render(<General />);
    await screen.findByRole("cell", { name: ".java" });

    await userEvent.type(screen.getByLabelText("New extension"), ".rs");
    await userEvent.type(screen.getByLabelText("New type"), "source");
    await userEvent.type(screen.getByLabelText("New subtype"), "rust");
    await userEvent.click(screen.getByRole("button", { name: /^Add$/ }));
    expect(fileTypes.add).toHaveBeenCalledWith({ extension: ".rs", file_type: "source", subtype: "rust" });

    vi.mocked(fileTypes.add).mockRejectedValue(new ApiError(409, "File type exists: .java", {}));
    await userEvent.type(screen.getByLabelText("New extension"), ".java");
    await userEvent.type(screen.getByLabelText("New type"), "source");
    await userEvent.type(screen.getByLabelText("New subtype"), "java");
    await userEvent.click(screen.getByRole("button", { name: /^Add$/ }));
    expect(await screen.findByText("File type exists: .java")).toBeInTheDocument();
  });

  it("edits a file type inline and deletes one after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<General />);
    const row = (await screen.findByRole("cell", { name: ".md" })).closest("tr")!;

    await userEvent.click(within(row).getByRole("button", { name: "Edit" }));
    const subtype = within(row).getByLabelText("Subtype of .md");
    await userEvent.clear(subtype);
    await userEvent.type(subtype, "md");
    await userEvent.click(within(row).getByRole("button", { name: "Save" }));
    expect(fileTypes.update).toHaveBeenCalledWith(".md", "docs", "md");

    await userEvent.click(within((await screen.findByRole("cell", { name: ".md" })).closest("tr")!).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(fileTypes.remove).toHaveBeenCalledWith(".md"));
  });

  it("lists the model configs with masked keys and saves an edit without resending the key", async () => {
    render(<General />);
    const row = (await screen.findByText("anthropic-haiku")).closest("tr")!;
    expect(row).toHaveTextContent("sk-...abcd");

    await userEvent.click(within(row).getByRole("button", { name: "Edit" }));
    const model = screen.getByLabelText("Model id");
    await userEvent.clear(model);
    await userEvent.type(model, "claude-haiku-2");
    await userEvent.click(screen.getByRole("button", { name: "Save model" }));

    expect(modelConfigs.save).toHaveBeenCalledWith("anthropic-haiku", { provider: "anthropic", model: "claude-haiku-2", url: "", key: null, key_env: "" });
    await waitFor(() => expect(modelConfigs.list).toHaveBeenCalledTimes(2));
  });

  it("adds a model with its key and deletes one after a confirm", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<General />);
    await screen.findByText("anthropic-haiku");

    await userEvent.click(screen.getByRole("button", { name: "Add model" }));
    await userEvent.type(screen.getByLabelText("Model name"), "mistral-small");
    await userEvent.selectOptions(screen.getByLabelText("Provider"), "mistral");
    await userEvent.type(screen.getByLabelText("Model id"), "mistral-small-latest");
    await userEvent.type(screen.getByLabelText("API key"), "sk-new-key");
    await userEvent.click(screen.getByRole("button", { name: "Save model" }));
    expect(modelConfigs.save).toHaveBeenCalledWith("mistral-small", { provider: "mistral", model: "mistral-small-latest", url: "", key: "sk-new-key", key_env: "" });

    await userEvent.click(within(screen.getByText("anthropic-haiku").closest("tr")!).getByRole("button", { name: "Delete" }));
    expect(modelConfigs.remove).toHaveBeenCalledWith("anthropic-haiku");
  });

  it("tests a model config with one small call and says how it went", async () => {
    vi.mocked(modelConfigs.test).mockResolvedValue({
      ok: true, model: "anthropic-haiku", provider: "anthropic", model_id: "claude-haiku", served_model: "claude-haiku-5-5", latency_ms: 812.4, answer: "OK",
    });
    render(<General />);
    const row = (await screen.findByText("anthropic-haiku")).closest("tr")!;

    await userEvent.click(within(row).getByRole("button", { name: "Test" }));

    expect(modelConfigs.test).toHaveBeenCalledWith("anthropic-haiku");
    expect(await screen.findByText("Works: claude-haiku-5-5 answered in 0.8 s")).toBeInTheDocument();
  });

  it("says what to fix when a model config does not work", async () => {
    vi.mocked(modelConfigs.test).mockResolvedValue({
      ok: false, model: "anthropic-haiku", provider: "anthropic", model_id: "claude-haiku", error: "The provider refused the API key: check the key (ModelHTTPError)", detail: "status_code: 401",
    });
    render(<General />);
    const row = (await screen.findByText("anthropic-haiku")).closest("tr")!;

    await userEvent.click(within(row).getByRole("button", { name: "Test" }));

    const result = await screen.findByText("The provider refused the API key: check the key (ModelHTTPError)");
    expect(result).toHaveAttribute("title", "status_code: 401");
  });

  it("asks to test a model after saving it", async () => {
    render(<General />);
    const row = (await screen.findByText("anthropic-haiku")).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Edit" }));

    await userEvent.click(screen.getByRole("button", { name: "Save model" }));

    expect(await screen.findByText("Saved anthropic-haiku. Press Test to check its key and model id.")).toBeInTheDocument();
  });
});
