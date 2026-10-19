import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, model: { get: vi.fn(), download: vi.fn(), quality: vi.fn() } };
});

vi.mock("../widgets/ArchimateWidget", () => ({ ArchimateWidget: () => <div data-testid="model-widget" /> }));

import { ApiError, model } from "../api/client";
import { ModelPanel } from "./ModelPanel";

const QUALITY = {
  elements: 7,
  relationships: 3,
  orphans: [],
  orphan_share: 0.43,
  structural_share: 1,
  relationship_types: { Composition: 3 },
  layers: { Business: 0, Application: 6, Technology: 1 },
  unsupported: [],
  verdict: "ok" as const,
  reasons: [],
};
const OK = QUALITY;
const WEAK = {
  ...QUALITY,
  unsupported: [{ id: "in", name: "Inbound", type: "ApplicationComponent", sources: ["repo/In"] }],
  verdict: "weak" as const,
  reasons: ["3 of 7 elements (43%) have no relationship (above 25%)", "1 element has no file, type or method behind its sources (Inbound)"],
};

describe("ModelPanel export", () => {
  beforeEach(() => {
    vi.mocked(model.get).mockResolvedValue({ elements: [], relationships: [] });
    vi.mocked(model.quality).mockResolvedValue(OK);
    URL.createObjectURL = vi.fn(() => "blob:model");
    URL.revokeObjectURL = vi.fn();
  });

  it("downloads the exchange file under the name the studio gave it", async () => {
    vi.mocked(model.download).mockResolvedValue({ blob: new Blob(["<model/>"]), name: "deriva-20261019-153000.xml" });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<ModelPanel dark={false} refresh={0} />);

    await userEvent.click(screen.getByRole("button", { name: /Export XML/ }));

    expect(await screen.findByText("Downloaded deriva-20261019-153000.xml")).toBeInTheDocument();
    expect(click).toHaveBeenCalledOnce();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:model");
  });

  it("says why there is nothing to export", async () => {
    vi.mocked(model.download).mockRejectedValue(new ApiError(400, "No ArchiMate elements found. Run derivation first.", {}));
    render(<ModelPanel dark={false} refresh={0} />);

    await userEvent.click(screen.getByRole("button", { name: /Export XML/ }));

    expect(await screen.findByText("No ArchiMate elements found. Run derivation first.")).toBeInTheDocument();
  });
});

describe("ModelPanel quality", () => {
  beforeEach(() => {
    vi.mocked(model.get).mockResolvedValue({ elements: [], relationships: [] });
  });

  it("says the model is ok", async () => {
    vi.mocked(model.quality).mockResolvedValue(OK);
    render(<ModelPanel dark={false} refresh={0} />);

    expect(await screen.findByRole("button", { name: "Quality: ok" })).toBeInTheDocument();
  });

  it("opens why a model is weak and which elements have nothing behind them", async () => {
    vi.mocked(model.quality).mockResolvedValue(WEAK);
    render(<ModelPanel dark={false} refresh={0} />);

    await userEvent.click(await screen.findByRole("button", { name: "Quality: weak" }));

    expect(screen.getByText("3 of 7 elements (43%) have no relationship (above 25%)")).toBeInTheDocument();
    expect(screen.getByText("Inbound (ApplicationComponent) ← repo/In")).toBeInTheDocument();
  });

  it("asks again when the model is refreshed", async () => {
    vi.mocked(model.quality).mockResolvedValue(OK);
    const { rerender } = render(<ModelPanel dark={false} refresh={0} />);
    await screen.findByRole("button", { name: "Quality: ok" });

    vi.mocked(model.quality).mockResolvedValue(WEAK);
    rerender(<ModelPanel dark={false} refresh={1} />);

    expect(await screen.findByRole("button", { name: "Quality: weak" })).toBeInTheDocument();
  });
});
