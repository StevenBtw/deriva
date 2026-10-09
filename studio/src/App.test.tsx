import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("./workspace/Workspace", () => ({ Workspace: () => <h2>Workspace page</h2> }));
vi.mock("./pages/Repositories", () => ({ Repositories: () => <h2>Repositories page</h2> }));
vi.mock("./pages/General", () => ({ General: () => <h2>General page</h2> }));
vi.mock("./pages/ConfigPage", () => ({ ConfigPage: ({ stepType }: { stepType: string }) => <h2>{stepType} config page</h2> }));
vi.mock("./api/client", async () => {
  const actual = await vi.importActual<typeof import("./api/client")>("./api/client");
  return { ...actual, status: vi.fn().mockResolvedValue({ version: "0.8.0", db: { state: "held", held_by: 4242 } }) };
});

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

    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it("shows the database status from the API", async () => {
    at("/");

    expect(await screen.findByRole("status")).toHaveTextContent("4242");
  });
});
