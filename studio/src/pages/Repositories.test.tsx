import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, repositories: { list: vi.fn(), info: vi.fn(), clone: vi.fn(), remove: vi.fn(), data: vi.fn(), clearModel: vi.fn(), clearData: vi.fn(), update: vi.fn(), unregistered: vi.fn(), register: vi.fn(), coverage: vi.fn() } };
});

import { ApiError, repositories } from "../api/client";
import type { RunSummary } from "../api/types";
import { Repositories } from "./Repositories";

const DERIVA = { name: "deriva", branch: "release/0.7.1", last_commit: "ef815ce improved classification", size_mb: 10.9, is_dirty: false, url: "https://github.com/x/deriva", path: "workspace/repositories/deriva" };
const RUN = (run_id: string, kind: RunSummary["kind"], status: string, started_at: number) => ({ run_id, kind, repository: "deriva", status, events: 3, started_at, finished_at: started_at + 60 });
const DATA = {
  repository: "deriva",
  graph: { nodes: 4536, edges: 9129 },
  model: { elements: 46, relationships: 48 },
  database_bytes: 2_831_155,
  last_runs: { extraction: RUN("r1", "all", "finished", 1_792_300_000), derivation: RUN("r2", "derivation", "cancelled", 1_792_310_000) },
};
const ROW = (extension: string, files: number, reader: "parser" | "llm" | null, with_symbols: number) => ({ extension, files, in_graph: files, file_type: "source", subtype: "", reader, with_symbols, unreadable: 0 });
const COMPLETE = { files: 166, in_graph: 166, extensions: [ROW(".py", 87, "parser", 76)], missing: [], unreadable: [], nodes: {}, complete: true, reasons: [], notes: ["12 source files are read by no extraction step: .sh (10), .css (1), .html (1)"] };
const INCOMPLETE = {
  ...COMPLETE,
  files: 4,
  in_graph: 3,
  extensions: [ROW(".java", 3, "parser", 0)],
  missing: ["gone.xsd"],
  unreadable: [{ path: "deep/A.java", reason: "path over 260 characters: [WinError 3]" }],
  complete: false,
  reasons: ["1 file is not in the graph (gone.xsd)", "none of the 3 source files gave a type or method (.java 3)"],
  notes: [],
};
const TOOLSHED = { name: "ToolShed", branch: "master", last_commit: "77c10b2 x", size_mb: 4.2, is_dirty: true, url: "u", path: "p" };

describe("Repositories", () => {
  beforeEach(() => {
    vi.mocked(repositories.list).mockResolvedValue([DERIVA, TOOLSHED]);
    vi.mocked(repositories.clone).mockResolvedValue({ name: "sampleapp", success: true });
    vi.mocked(repositories.remove).mockResolvedValue({ success: true });
    vi.mocked(repositories.data).mockResolvedValue(DATA);
    vi.mocked(repositories.clearModel).mockResolvedValue({ success: true });
    vi.mocked(repositories.clearData).mockResolvedValue({ success: true });
    vi.mocked(repositories.update).mockResolvedValue({ success: true, repository: { ...DERIVA, last_commit: "9a8b7c6 newer" } });
    vi.mocked(repositories.unregistered).mockResolvedValue([]);
    vi.mocked(repositories.coverage).mockResolvedValue(COMPLETE);
    vi.mocked(repositories.register).mockResolvedValue({ success: true, name: "orphan", branch: "main", last_commit: "1234567abc first" });
  });

  it("lists repositories and shows the selected one's details", async () => {
    render(<Repositories />);

    expect(await screen.findByRole("cell", { name: "deriva" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "ToolShed" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("cell", { name: "ToolShed" }));

    expect(screen.getByRole("heading", { name: "ToolShed" })).toBeInTheDocument();
    expect(screen.getByText(/uncommitted changes/i)).toBeInTheDocument();
  });

  it("selects a repository from the keyboard", async () => {
    render(<Repositories />);
    const row = (await screen.findByRole("cell", { name: "ToolShed" })).closest("tr")!;

    row.focus();
    await userEvent.keyboard("{Enter}");

    expect(screen.getByRole("heading", { name: "ToolShed" })).toBeInTheDocument();
  });

  it("clones a repository and refreshes the list", async () => {
    render(<Repositories />);
    await screen.findByRole("cell", { name: "deriva" });
    await userEvent.click(screen.getByRole("button", { name: /Clone repository/ }));

    await userEvent.click(screen.getByLabelText("Git URL"));
    await userEvent.paste("https://github.com/example/sample-app");
    await userEvent.type(screen.getByLabelText("Name (optional)"), "sampleapp");
    await userEvent.click(screen.getByRole("button", { name: /^Clone$/ }));

    expect(repositories.clone).toHaveBeenCalledWith("https://github.com/example/sample-app", "sampleapp", "");
    await waitFor(() => expect(repositories.list).toHaveBeenCalledTimes(2));
  });

  it("offers to register a git folder in the workspace that has no record", async () => {
    vi.mocked(repositories.unregistered).mockResolvedValue(["orphan"]);
    render(<Repositories />);

    expect(await screen.findByText(/orphan/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Register orphan" }));

    expect(repositories.register).toHaveBeenCalledWith("orphan");
    expect(await screen.findByText("Registered orphan: branch main at 1234567 first. Run it from the Workspace.")).toBeInTheDocument();
    await waitFor(() => expect(repositories.list).toHaveBeenCalledTimes(2));
  });

  it("marks a stale record and deletes only its record", async () => {
    vi.mocked(repositories.list).mockResolvedValue([{ name: "gone", path: "p", stale: "its folder is gone" }]);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Repositories />);

    expect(await screen.findByRole("cell", { name: "stale" })).toHaveAttribute("title", "its folder is gone");
    expect(screen.getByRole("button", { name: "Update clone" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /Delete/ }));

    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/Remove the record of gone\? Its folder is gone; no files are deleted/));
    expect(repositories.remove).toHaveBeenCalledWith("gone", false, false);
    expect(await screen.findByText("Removed the record of gone.")).toBeInTheDocument();
  });

  it("asks before deleting and passes force for a dirty repository", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Repositories />);
    await userEvent.click(await screen.findByRole("cell", { name: "ToolShed" }));

    await userEvent.click(screen.getByRole("button", { name: /Delete/ }));

    expect(confirm).toHaveBeenCalled();
    expect(repositories.remove).toHaveBeenCalledWith("ToolShed", true, false);
  });

  it("does nothing when the deletion is not confirmed", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<Repositories />);
    await userEvent.click(await screen.findByRole("cell", { name: "deriva" }));

    await userEvent.click(screen.getByRole("button", { name: /Delete/ }));

    expect(repositories.remove).not.toHaveBeenCalled();
  });

  it("shows API errors inline", async () => {
    vi.mocked(repositories.clone).mockRejectedValue(new ApiError(400, "repository exists", {}));
    render(<Repositories />);
    await screen.findByRole("cell", { name: "deriva" });
    await userEvent.click(screen.getByRole("button", { name: /Clone repository/ }));
    await userEvent.click(screen.getByLabelText("Git URL"));
    await userEvent.paste("https://example.org/x.git");

    await userEvent.click(screen.getByRole("button", { name: /^Clone$/ }));

    expect(await screen.findByText("repository exists")).toBeInTheDocument();
  });

  it("shows what the selected repository's graph database holds and its last runs", async () => {
    render(<Repositories />);

    expect(await screen.findByText(/4,536 nodes · 9,129 edges/)).toBeInTheDocument();
    expect(screen.getByText(/46 elements · 48 relationships/)).toBeInTheDocument();
    expect(screen.getByText(/2\.7 MB/)).toBeInTheDocument();
    expect(screen.getByText(/all · finished/)).toBeInTheDocument();
    expect(screen.getByText(/derivation · cancelled/)).toBeInTheDocument();
    expect(repositories.data).toHaveBeenCalledWith("deriva");
  });

  it("says the extraction is complete and what it noticed", async () => {
    render(<Repositories />);

    expect(await screen.findByText("Complete: 166 of 166 files in the graph")).toBeInTheDocument();
    expect(screen.getByText("12 source files are read by no extraction step: .sh (10), .css (1), .html (1)")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: ".py" })).toBeInTheDocument();
    expect(repositories.coverage).toHaveBeenCalledWith("deriva");
  });

  it("says why an extraction is incomplete and downloads the files that did not make it", async () => {
    vi.mocked(repositories.coverage).mockResolvedValue(INCOMPLETE);
    URL.createObjectURL = vi.fn(() => "blob:coverage");
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<Repositories />);

    expect(await screen.findByText("Incomplete: 3 of 4 files in the graph")).toBeInTheDocument();
    expect(screen.getByText("none of the 3 source files gave a type or method (.java 3)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Download the list (2)" }));

    const text = await (vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob).text();
    expect(text.split("\n")).toEqual(["not in the graph: gone.xsd", "could not be read: deep/A.java: path over 260 characters: [WinError 3]"]);
    expect(click).toHaveBeenCalledOnce();
  });

  it("says why the coverage could not be read", async () => {
    vi.mocked(repositories.coverage).mockRejectedValue(new ApiError(409, "A run is in progress; try again when it has finished", {}));
    render(<Repositories />);

    expect(await screen.findByText("A run is in progress; try again when it has finished")).toBeInTheDocument();
  });

  it("clears the model after a confirmation that names what goes, then counts again", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Repositories />);
    await screen.findByText(/4,536 nodes/);

    await userEvent.click(screen.getByRole("button", { name: "Clear model" }));

    expect(confirm.mock.calls[0][0]).toMatch(/46 elements and 48 relationships/);
    expect(repositories.clearModel).toHaveBeenCalledWith("deriva");
    await waitFor(() => expect(repositories.data).toHaveBeenCalledTimes(2));
  });

  it("clears graph and model together", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Repositories />);
    await screen.findByText(/4,536 nodes/);

    await userEvent.click(screen.getByRole("button", { name: "Clear graph and model" }));

    expect(confirm.mock.calls[0][0]).toMatch(/4,536 graph nodes and 46 model elements/);
    expect(repositories.clearData).toHaveBeenCalledWith("deriva");
  });

  it("updates the clone and shows its new commit", async () => {
    render(<Repositories />);
    await screen.findByText(/4,536 nodes/);

    await userEvent.click(screen.getByRole("button", { name: "Update clone" }));

    expect(repositories.update).toHaveBeenCalledWith("deriva");
    expect(await screen.findByText(/Updated to 9a8b7c6 newer; run extraction to read it/)).toBeInTheDocument();
    await waitFor(() => expect(repositories.list).toHaveBeenCalledTimes(2));
  });

  it("says when the clone was already up to date", async () => {
    vi.mocked(repositories.update).mockResolvedValue({ success: true, repository: { ...DERIVA, last_commit: "ef815ce1a2b3c4d5 improved classification" } });
    vi.mocked(repositories.list).mockResolvedValue([{ ...DERIVA, last_commit: "ef815ce1a2b3c4d5 improved classification" }]);
    render(<Repositories />);
    await screen.findByText(/4,536 nodes/);

    await userEvent.click(screen.getByRole("button", { name: "Update clone" }));

    expect(await screen.findByText("Already up to date at ef815ce improved classification")).toBeInTheDocument();
  });

  it("deletes the repository's graph and model too when asked", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Repositories />);
    await screen.findByText(/4,536 nodes/);

    await userEvent.click(screen.getByRole("checkbox", { name: /also delete its graph and model/ }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(confirm.mock.calls[0][0]).toMatch(/and its graph and model/);
    expect(repositories.remove).toHaveBeenCalledWith("deriva", false, true);
  });

  it("says why an action waits while a run is in progress", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(repositories.clearModel).mockRejectedValue(new ApiError(409, "A run is in progress; try again when it has finished", {}));
    render(<Repositories />);
    await screen.findByText(/4,536 nodes/);

    await userEvent.click(screen.getByRole("button", { name: "Clear model" }));

    expect(await screen.findByText("A run is in progress; try again when it has finished")).toBeInTheDocument();
  });

  it("says what it is doing while it clones and what it cloned", async () => {
    let finish: (value: unknown) => void = () => {};
    vi.mocked(repositories.clone).mockReturnValue(new Promise((resolve) => (finish = resolve)) as never);
    render(<Repositories />);
    await screen.findByRole("cell", { name: "deriva" });
    await userEvent.click(screen.getByRole("button", { name: /Clone repository/ }));
    await userEvent.click(screen.getByLabelText("Git URL"));
    await userEvent.paste("https://github.com/example/sample-app.git");
    expect(screen.getByLabelText("Name (optional)")).toHaveAttribute("placeholder", "sample-app");

    await userEvent.click(screen.getByRole("button", { name: /^Clone$/ }));
    expect(await screen.findByText("Cloning https://github.com/example/sample-app.git… a large repository takes longer")).toBeInTheDocument();

    finish({ success: true, name: "sample-app", branch: "main", last_commit: "f112fcef7f675a16 first commit", size_mb: 0.7 });
    expect(await screen.findByText("Cloned sample-app: branch main at f112fce first commit, 0.7 MB. Run it from the Workspace.")).toBeInTheDocument();
  });

  it("says what a delete removed and what stayed", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Repositories />);
    await screen.findByText(/4,536 nodes/);

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("Deleted the clone of deriva. Its graph and model stay; Runs & storage can delete them.")).toBeInTheDocument();
  });

  it("names the graph and model when they went too", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(repositories.remove).mockResolvedValue({ success: true, data_deleted: true });
    render(<Repositories />);
    await screen.findByText(/4,536 nodes/);

    await userEvent.click(screen.getByRole("checkbox", { name: /also delete its graph and model/ }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("Deleted deriva with its graph and model.")).toBeInTheDocument();
  });
});
