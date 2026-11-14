import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { model } from "../api/client";
import { Model } from "./Model";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, model: { ...actual.model, exports: vi.fn(), save: vi.fn() } };
});

const FOLDER = "H:/Deriva/deriva/workspace/output";

describe("Export config", () => {
  beforeEach(() => {
    vi.mocked(model.exports).mockResolvedValue({
      folder: FOLDER,
      suggested: "deriva-20261113-142900.xml",
      files: [{ name: "model.xml", bytes: 2048, modified: 1_791_900_000 }],
    });
    vi.mocked(model.save).mockResolvedValue({ success: true, output_path: `${FOLDER}/deriva-20261113-142900.xml`, elements_exported: 22, relationships_exported: 23, views_exported: 4 });
  });

  it("shows the folder, a suggested file name and the full path it will write", async () => {
    render(<Model />);

    expect(await screen.findByLabelText("File name")).toHaveValue("deriva-20261113-142900.xml");
    expect(screen.getByText(`${FOLDER}/deriva-20261113-142900.xml`)).toBeInTheDocument();
    expect(screen.getByText("model.xml")).toBeInTheDocument();
  });

  it("adds .xml to a name without it and refuses a name with a folder in it", async () => {
    render(<Model />);
    const name = await screen.findByLabelText("File name");

    await userEvent.clear(name);
    await userEvent.type(name, "release");
    expect(screen.getByText(`${FOLDER}/release.xml`)).toBeInTheDocument();

    await userEvent.clear(name);
    await userEvent.type(name, "../elsewhere");
    expect(screen.getByText(/a file name only/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("warns before replacing an existing export", async () => {
    render(<Model />);
    const name = await screen.findByLabelText("File name");

    await userEvent.clear(name);
    await userEvent.type(name, "model.xml");

    expect(screen.getByText(/replaces model\.xml/i)).toBeInTheDocument();
  });

  it("saves into the output folder and says what it wrote", async () => {
    render(<Model />);
    await screen.findByLabelText("File name");

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(model.save).toHaveBeenCalledWith("workspace/output/deriva-20261113-142900.xml");
    await waitFor(() => expect(screen.getByText(/22 elements · 23 relationships · 4 views/)).toBeInTheDocument());
  });

  it("reads the list again after a save, so the new file shows up", async () => {
    const saved = { name: "deriva-20261113-142900.xml", bytes: 4096, modified: 1_791_900_100 };
    vi.mocked(model.exports)
      .mockResolvedValueOnce({ folder: FOLDER, suggested: saved.name, files: [{ name: "model.xml", bytes: 2048, modified: 1_791_900_000 }] })
      .mockResolvedValueOnce({ folder: FOLDER, suggested: "deriva-20261113-143000.xml", files: [saved, { name: "model.xml", bytes: 2048, modified: 1_791_900_000 }] });
    render(<Model />);
    await screen.findByLabelText("File name");
    expect(screen.queryByRole("cell", { name: saved.name })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("cell", { name: saved.name })).toBeInTheDocument();
  });

  it("keeps a name typed before the suggestion arrives", async () => {
    let answer: (value: Awaited<ReturnType<typeof model.exports>>) => void = () => {};
    vi.mocked(model.exports).mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    render(<Model />);
    const name = screen.getByLabelText("File name");

    await userEvent.type(name, "mine");
    answer({ folder: FOLDER, suggested: "deriva-20261113-142900.xml", files: [] });

    expect(await screen.findByText(`${FOLDER}/mine.xml`)).toBeInTheDocument();
    expect(name).toHaveValue("mine");
  });

  it("announces a failure to screen readers", async () => {
    vi.mocked(model.exports).mockRejectedValueOnce(new Error("The output folder cannot be read"));
    render(<Model />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The output folder cannot be read");
  });
});
