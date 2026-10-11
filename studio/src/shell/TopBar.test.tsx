import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
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

  it("shows the Deriva mark next to the name", () => {
    const { container } = render(<TopBar mode="run" onModeChange={() => {}} db={{ state: "owned" }} />);

    const logo = container.querySelector(".logo");
    expect(logo).toHaveTextContent("Deriva Studio");
    // Decorative: the name next to it is the accessible label
    expect(logo?.querySelector("svg.mark")).toHaveAttribute("aria-hidden", "true");
  });

  it("shows the version next to the name", () => {
    const { container } = render(<TopBar mode="run" onModeChange={() => {}} db={{ state: "owned" }} version="0.8.0" />);

    expect(container.querySelector(".logo")).toHaveTextContent("Deriva Studio");
    expect(screen.getByText("v0.8.0")).toBeInTheDocument();
  });

  it("offers no Benchmark mode when benchmarking is not installed", () => {
    render(<TopBar mode="run" onModeChange={() => {}} db={{ state: "owned" }} benchmark={false} />);

    expect(screen.queryByRole("button", { name: "Benchmark" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Mode" })).not.toBeInTheDocument();
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

  it("says a pipeline step is running when the status reports the session busy", () => {
    render(<Banner db={{ state: "owned", busy: true }} />);

    expect(screen.getByRole("status")).toHaveTextContent("A pipeline step is running");
  });

  it("is empty while the studio owns the databases", () => {
    const { container } = render(<Banner db={{ state: "owned" }} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("points to General when no LLM model is configured", () => {
    render(
      <MemoryRouter>
        <Banner db={{ state: "owned" }} noModel />
      </MemoryRouter>,
    );

    expect(screen.getByRole("status")).toHaveTextContent("No LLM model is configured");
    expect(screen.getByRole("link", { name: "Add a model in General" })).toHaveAttribute("href", "/general");
  });

  it("puts a held database before the model hint", () => {
    render(
      <MemoryRouter>
        <Banner db={{ state: "held", held_by: 7 }} noModel />
      </MemoryRouter>,
    );

    expect(screen.getByRole("status")).toHaveTextContent("PID 7");
    expect(screen.queryByText(/No LLM model/)).not.toBeInTheDocument();
  });
});
