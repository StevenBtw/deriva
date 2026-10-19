import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, runs: { ...actual.runs, calls: vi.fn() } };
});

import { runs } from "../api/client";
import type { RunEvent } from "../api/types";
import { BottomPanel } from "./BottomPanel";

const step = (seq: number, status: string, message: string): RunEvent => ({ seq, event: "progress", data: { phase: "extraction", step: "File", status, message } });
const end = (seq: number, errors: string[]): RunEvent => ({
  seq,
  event: "progress",
  data: { phase: "extraction", step: "", status: "complete", message: `10 nodes (${errors.length} errors)`, stats: { success: errors.length === 0, errors } },
});
const panel = (events: RunEvent[]) => <BottomPanel events={events} status="" runId="r1" runStatus="finished" tab="errors" onTab={() => {}} />;

describe("BottomPanel errors", () => {
  beforeEach(() => {
    vi.mocked(runs.calls).mockResolvedValue([]);
    URL.createObjectURL = vi.fn(() => "blob:errors");
    URL.revokeObjectURL = vi.fn();
  });

  it("lists the errors of steps that completed, not only of steps that failed", () => {
    render(panel([step(1, "error", "Error in Method: boom"), end(2, ["Failed to read a/b.xsd: [WinError 3]", "Failed to read c.wsdl: [WinError 3]"])]));

    expect(screen.getByRole("tab", { name: "Errors (3)" })).toBeInTheDocument();
    expect(screen.getByText("File: Error in Method: boom")).toBeInTheDocument();
    expect(screen.getByText("Failed to read a/b.xsd: [WinError 3]")).toBeInTheDocument();
    expect(screen.getByText("Failed to read c.wsdl: [WinError 3]")).toBeInTheDocument();
  });

  it("shows a sample of a long list and downloads all of it", async () => {
    const many = Array.from({ length: 120 }, (_, i) => `Failed to read file${i}.xsd`);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(panel([end(1, many)]));

    expect(screen.getByText("Failed to read file49.xsd")).toBeInTheDocument();
    expect(screen.queryByText("Failed to read file50.xsd")).not.toBeInTheDocument();
    expect(screen.getByText("50 of 120 shown")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Download all 120" }));

    const blob = vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob;
    expect((await blob.text()).split("\n")).toHaveLength(120);
    expect(click).toHaveBeenCalledOnce();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:errors");
  });

  it("says when a run had no errors", () => {
    render(panel([end(1, [])]));

    expect(screen.getByText("No errors in this run.")).toBeInTheDocument();
  });
});
