import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Banner } from "./Banner";
import { TopBar } from "./TopBar";

describe("TopBar", () => {
  it("cycles the theme and applies it to the page", async () => {
    render(<TopBar mode="run" onModeChange={() => {}} db={{ state: "owned" }} />);
    const button = screen.getByRole("button", { name: /theme/i });

    await userEvent.click(button);
    expect(document.documentElement.dataset.theme).toBe("light");

    await userEvent.click(button);
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("switches between run and benchmark mode", async () => {
    const changes: string[] = [];
    render(<TopBar mode="run" onModeChange={(m) => changes.push(m)} db={{ state: "owned" }} />);

    await userEvent.click(screen.getByRole("button", { name: "Benchmark" }));

    expect(changes).toEqual(["benchmark"]);
  });

  it("says the database is busy while a step holds it", () => {
    render(<TopBar mode="run" onModeChange={() => {}} db={{ state: "owned", busy: true }} />);

    expect(screen.getByText("DB busy")).toBeInTheDocument();
  });

  it("links the API docs", () => {
    render(<TopBar mode="run" onModeChange={() => {}} db={{ state: "owned" }} />);

    expect(screen.getByRole("link", { name: /API/ })).toHaveAttribute("href", "/docs");
  });
});

describe("Banner", () => {
  it("explains a database held by another process", () => {
    render(<Banner db={{ state: "held", held_by: 241896 }} />);

    expect(screen.getByRole("status")).toHaveTextContent("241896");
  });

  it("is empty while the studio owns the databases", () => {
    const { container } = render(<Banner db={{ state: "owned" }} />);

    expect(container).toBeEmptyDOMElement();
  });
});
