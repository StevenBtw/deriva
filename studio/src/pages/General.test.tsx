import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    settings: { get: vi.fn(), set: vi.fn() },
    fileTypes: { list: vi.fn(), add: vi.fn(), update: vi.fn(), remove: vi.fn() },
    modelConfigs: { list: vi.fn(), save: vi.fn(), remove: vi.fn() },
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
      { name: "anthropic-haiku", provider: "anthropic", model: "claude-haiku", url: null, key: "sk-...abcd", key_env: null, structured_output: null },
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

    expect(modelConfigs.save).toHaveBeenCalledWith("anthropic-haiku", { provider: "anthropic", model: "claude-haiku-2", url: "", key: null, key_env: null, structured_output: null });
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
    expect(modelConfigs.save).toHaveBeenCalledWith("mistral-small", { provider: "mistral", model: "mistral-small-latest", url: "", key: "sk-new-key", key_env: null, structured_output: null });

    await userEvent.click(within(screen.getByText("anthropic-haiku").closest("tr")!).getByRole("button", { name: "Delete" }));
    expect(modelConfigs.remove).toHaveBeenCalledWith("anthropic-haiku");
  });
});
