import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, repositories: { list: vi.fn(), info: vi.fn(), clone: vi.fn(), remove: vi.fn() } };
});

import { ApiError, repositories } from "../api/client";
import { Repositories } from "./Repositories";

const DERIVA = { name: "deriva", branch: "release/0.7.1", last_commit: "ef815ce improved classification", size_mb: 10.9, is_dirty: false, url: "https://github.com/x/deriva", path: "workspace/repositories/deriva" };
const TEASTORE = { name: "TeaStore", branch: "master", last_commit: "77c10b2 x", size_mb: 4.2, is_dirty: true, url: "u", path: "p" };

describe("Repositories", () => {
  beforeEach(() => {
    vi.mocked(repositories.list).mockResolvedValue([DERIVA, TEASTORE]);
    vi.mocked(repositories.clone).mockResolvedValue({ name: "carddemo", success: true });
    vi.mocked(repositories.remove).mockResolvedValue({ success: true });
  });

  it("lists repositories and shows the selected one's details", async () => {
    render(<Repositories />);

    expect(await screen.findByRole("cell", { name: "deriva" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "TeaStore" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("cell", { name: "TeaStore" }));

    expect(screen.getByRole("heading", { name: "TeaStore" })).toBeInTheDocument();
    expect(screen.getByText(/uncommitted changes/i)).toBeInTheDocument();
  });

  it("clones a repository and refreshes the list", async () => {
    render(<Repositories />);
    await screen.findByRole("cell", { name: "deriva" });
    await userEvent.click(screen.getByRole("button", { name: /Clone repository/ }));

    await userEvent.click(screen.getByLabelText("Git URL"));
    await userEvent.paste("https://github.com/aws-samples/aws-mainframe-modernization-carddemo");
    await userEvent.type(screen.getByLabelText("Name (optional)"), "carddemo");
    await userEvent.click(screen.getByRole("button", { name: /^Clone$/ }));

    expect(repositories.clone).toHaveBeenCalledWith("https://github.com/aws-samples/aws-mainframe-modernization-carddemo", "carddemo", "");
    await waitFor(() => expect(repositories.list).toHaveBeenCalledTimes(2));
  });

  it("asks before deleting and passes force for a dirty repository", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Repositories />);
    await userEvent.click(await screen.findByRole("cell", { name: "TeaStore" }));

    await userEvent.click(screen.getByRole("button", { name: /Delete/ }));

    expect(confirm).toHaveBeenCalled();
    expect(repositories.remove).toHaveBeenCalledWith("TeaStore", true);
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
});
