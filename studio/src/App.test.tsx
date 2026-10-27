import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("./workspace/Workspace", () => ({
  Workspace: () => <h2>Workspace page</h2>,
}));
vi.mock("./pages/Repositories", () => ({
  Repositories: () => <h2>Repositories page</h2>,
}));
vi.mock("./pages/General", () => ({ General: () => <h2>General page</h2> }));
vi.mock("./pages/ConfigPage", () => ({
  ConfigPage: ({ stepType }: { stepType: string }) => (
    <h2>{stepType} config page</h2>
  ),
}));
vi.mock("./api/client", async () => {
  const actual =
    await vi.importActual<typeof import("./api/client")>("./api/client");
  return {
    ...actual,
    status: vi
      .fn()
      .mockResolvedValue({
        version: "0.8.0",
        db: { state: "held", held_by: 4242 },
      }),
    modelConfigs: { list: vi.fn().mockResolvedValue([{ name: "mistral" }]) },
  };
});

import { ApiError, modelConfigs, status } from "./api/client";
import { Shell } from "./App";

function at(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Shell />
    </MemoryRouter>,
  );
}

describe("Shell routes", () => {
  it.each([
    ["/", "Workspace page"],
    ["/repositories", "Repositories page"],
    ["/general", "General page"],
    ["/config/extraction", "extraction config page"],
    ["/config/derivation", "derivation config page"],
  ])("%s shows %s", async (path, heading) => {
    at(path);

    expect(
      await screen.findByRole("heading", { name: heading }),
    ).toBeInTheDocument();
  });

  it("answers an unknown address with a page that leads back to the workspace", async () => {
    at("/no/such/page");

    expect(
      await screen.findByRole("heading", { name: "Page not found" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Go to the workspace" }),
    ).toHaveAttribute("href", "/");
  });

  it("shows the database status from the API", async () => {
    at("/");

    expect(await screen.findByRole("status")).toHaveTextContent("4242");
  });

  it("shows the version, and no Benchmark mode when the install has no benchmarking", async () => {
    vi.mocked(status).mockResolvedValueOnce({
      version: "0.8.0",
      db: { state: "owned" },
      features: { benchmark: false },
    });
    at("/");

    expect(await screen.findByText("v0.8.0")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Benchmark" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the Benchmark mode when the API does not report features", async () => {
    vi.mocked(status).mockResolvedValueOnce({
      version: "0.8.0",
      db: { state: "owned" },
    });
    at("/");

    expect(await screen.findByText("v0.8.0")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Benchmark" }),
    ).toBeInTheDocument();
  });

  it("asks for the launch link when the studio refuses this browser", async () => {
    vi.mocked(status).mockRejectedValueOnce(
      new ApiError(401, "Open the studio from the link", {
        detail: "Open the studio from the link",
      }),
    );
    at("/");

    expect(
      await screen.findByRole("heading", {
        name: "Open the studio from its launch link",
      }),
    ).toBeInTheDocument();
  });

  it("says when no LLM model is configured", async () => {
    vi.mocked(status).mockResolvedValueOnce({
      version: "0.8.0",
      db: { state: "owned" },
    });
    vi.mocked(modelConfigs.list).mockResolvedValueOnce([]);
    at("/");

    expect(
      await screen.findByText(/No LLM model is configured/),
    ).toBeInTheDocument();
  });
});
