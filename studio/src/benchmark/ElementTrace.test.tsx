import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ElementTrace as Trace } from "../api/types";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, benchmarks: { trace: vi.fn() } };
});

import { benchmarks } from "../api/client";
import { ElementTrace } from "./ElementTrace";
import type { Item } from "./inspect";

const element = (run: string, source: string) => ({ run, identifier: run, name: "Worker", type: "ApplicationComponent", layer: "Application", source, by_source: `ApplicationComponent|${source}`, by_name: "ApplicationComponent|worker" });

const step = (run: string, present: boolean): Trace => ({
  run,
  present,
  name: present ? "Worker" : null,
  stage: present ? "created" : "filtered_out",
  refine: null,
  cause: present ? null : "candidate filtered_out",
  calls: present ? [{ call_id: `c-${run}`, step: "ApplicationComponent", schema: "derivation_output", cache_key: null, model: "m", temperature: 0, cache_hit: false, prompt: "the prompt", response: '{"elements": []}', error: null }] : [],
});

describe("ElementTrace", () => {
  it("traces each run of a by-name element by the source it has in that run", async () => {
    vi.mocked(benchmarks.trace).mockImplementation(async (_sessions, _repo, _type, source) =>
      source === "dir::r::a" ? [step("s/1", true), step("s/2", false)] : [step("s/1", false), step("s/2", true)],
    );
    const item: Item = { key: "ApplicationComponent|worker", type: "ApplicationComponent", layer: "Application", name: "Worker", byRun: { "s/1": element("s/1", "dir::r::a"), "s/2": element("s/2", "dir::r::b") } };

    render(<ElementTrace sessions={["s"]} repo="r" item={item} />);

    const trace = await screen.findByTestId("element-trace");
    expect(trace).toHaveTextContent('s/1: in the model as "Worker"');
    expect(trace).toHaveTextContent('s/2: in the model as "Worker"');
    expect(benchmarks.trace).toHaveBeenCalledTimes(2);
  });

  it("says whether the prompt or the answer is open", async () => {
    vi.mocked(benchmarks.trace).mockResolvedValue([step("s/1", true)]);
    const item: Item = { key: "k", type: "ApplicationComponent", layer: "Application", name: "Worker", byRun: { "s/1": element("s/1", "dir::r::a") } };
    render(<ElementTrace sessions={["s"]} repo="r" item={item} />);

    const prompt = await screen.findByRole("button", { name: /prompt/ });
    expect(prompt).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(prompt);

    expect(prompt).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /answer/ })).toHaveAttribute("aria-expanded", "false");
  });
});
