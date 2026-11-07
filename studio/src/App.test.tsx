import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
// A page whose chunk cannot be fetched (a stopped studio, a newer build)
vi.mock("./pages/Storage", () => {
  throw new Error("Failed to fetch dynamically imported module");
});
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

  it("loads a page on demand: its fallback first, then the page", async () => {
    // A page loads once per studio: a fresh copy of the shell has loaded none yet
    vi.resetModules();
    const { Shell: FreshShell } = await import("./App");
    render(
      <MemoryRouter initialEntries={["/repositories"]}>
        <FreshShell />
      </MemoryRouter>,
    );

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Repositories page" }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Repositories page" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
  });

  it("shows an error, not a blank page, when a page cannot be loaded", async () => {
    // React reports the caught error on the console; the test needs only the page
    const report = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      at("/storage");

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "This page could not be loaded",
      );
    } finally {
      report.mockRestore();
    }
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

describe("Status polling", () => {
  const ANSWER = { version: "0.8.0", db: { state: "owned" as const } };
  // Lets the poll's promises settle and the timers up to then fire, without waiting for real
  const after = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(status).mockReset();
    vi.mocked(modelConfigs.list).mockReset().mockResolvedValue([{ name: "mistral" }] as never);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("asks every 10 seconds while the studio answers", async () => {
    vi.mocked(status).mockResolvedValue(ANSWER);
    at("/");
    await after(0);
    expect(status).toHaveBeenCalledTimes(1);

    await after(10_000);
    expect(status).toHaveBeenCalledTimes(2);
    await after(10_000);
    expect(status).toHaveBeenCalledTimes(3);
    expect(modelConfigs.list).toHaveBeenCalledTimes(3);
  });

  it("backs off while the studio does not answer, says it is not reachable, and clears that once it answers", async () => {
    vi.mocked(status).mockRejectedValue(new TypeError("Failed to fetch"));
    at("/");
    await after(0);
    expect(status).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toHaveTextContent(/The studio is not reachable/);

    // 20 s after the first miss, then 40 s, then never more than a minute between tries
    await after(19_999);
    expect(status).toHaveBeenCalledTimes(1);
    await after(1);
    expect(status).toHaveBeenCalledTimes(2);
    await after(40_000);
    expect(status).toHaveBeenCalledTimes(3);
    await after(60_000);
    expect(status).toHaveBeenCalledTimes(4);
    await after(60_000);
    expect(status).toHaveBeenCalledTimes(5);
    // The model list is no use while the studio is gone: only the status is asked
    expect(modelConfigs.list).toHaveBeenCalledTimes(0);

    vi.mocked(status).mockResolvedValue(ANSWER);
    await after(60_000);
    expect(status).toHaveBeenCalledTimes(6);
    expect(screen.queryByText(/The studio is not reachable/)).not.toBeInTheDocument();
    expect(modelConfigs.list).toHaveBeenCalledTimes(1);
    await after(10_000);
    expect(status).toHaveBeenCalledTimes(7);
  });

  it("treats an error answer as an answer: no notice, the last known state kept, the next request at the normal interval", async () => {
    vi.mocked(status).mockResolvedValueOnce(ANSWER);
    at("/");
    await after(0);
    vi.mocked(status).mockRejectedValue(new ApiError(500, "Internal Server Error", { detail: "Internal Server Error" }));

    await after(10_000);
    expect(status).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("DB")).toBeInTheDocument();
    // An error answer refreshes the model list as any answer does, so "no model" cannot go stale
    expect(modelConfigs.list).toHaveBeenCalledTimes(2);
    await after(10_000);
    expect(status).toHaveBeenCalledTimes(3);
    expect(modelConfigs.list).toHaveBeenCalledTimes(3);
  });

  it("clears the not-reachable notice when the studio answers again, even with an error", async () => {
    vi.mocked(status).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    at("/");
    await after(0);
    expect(screen.getByRole("alert")).toHaveTextContent(/The studio is not reachable/);
    vi.mocked(status).mockRejectedValue(new ApiError(503, "Service Unavailable", { detail: "Service Unavailable" }));

    await after(20_000);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await after(10_000);
    expect(status).toHaveBeenCalledTimes(3);
  });

  it("points a refused browser to the launch link, keeps asking for the status only, and unlocks on the first answer", async () => {
    // The launch link opened in another tab sets the cookie for this tab too: the next answer lets it in
    vi.mocked(status).mockRejectedValue(new ApiError(401, "Open the studio from the link", { detail: "Open the studio from the link" }));
    at("/");
    await after(0);
    expect(screen.getByRole("heading", { name: "Open the studio from its launch link" })).toBeInTheDocument();

    await after(10_000);
    expect(status).toHaveBeenCalledTimes(2);
    await after(10_000);
    expect(status).toHaveBeenCalledTimes(3);
    expect(modelConfigs.list).toHaveBeenCalledTimes(0);

    vi.mocked(status).mockResolvedValue(ANSWER);
    await after(10_000);
    expect(screen.queryByRole("heading", { name: "Open the studio from its launch link" })).not.toBeInTheDocument();
    expect(modelConfigs.list).toHaveBeenCalledTimes(1);
  });

  it("unlocks a refused page on an error answer too: the guard checks the token before every route", async () => {
    vi.mocked(status).mockRejectedValueOnce(new ApiError(401, "Open the studio from the link", { detail: "Open the studio from the link" }));
    vi.mocked(status).mockRejectedValue(new ApiError(500, "Internal Server Error", { detail: "Internal Server Error" }));
    at("/");
    await after(0);
    expect(screen.getByRole("heading", { name: "Open the studio from its launch link" })).toBeInTheDocument();

    await after(10_000);
    expect(screen.queryByRole("heading", { name: "Open the studio from its launch link" })).not.toBeInTheDocument();
  });

  it("keeps the newest model list when an older request answers after it", async () => {
    vi.mocked(status).mockResolvedValue(ANSWER);
    // The first model list request answers late; the second answers at once
    let answerFirst: (models: { name: string }[]) => void = () => {};
    vi.mocked(modelConfigs.list)
      .mockImplementationOnce(() => new Promise((resolve) => (answerFirst = resolve as typeof answerFirst)) as never)
      .mockResolvedValueOnce([] as never);
    at("/");
    await after(0);
    await after(10_000);
    expect(screen.getByText(/No LLM model is configured/)).toBeInTheDocument();

    // The older answer (a model exists) arrives last and is ignored: the newest says there is none
    await act(async () => answerFirst([{ name: "mistral" }]));
    expect(screen.getByText(/No LLM model is configured/)).toBeInTheDocument();
  });
});
