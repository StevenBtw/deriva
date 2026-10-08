import { describe, expect, it } from "vitest";

import type { RunEvent } from "./types";
import { followRun } from "./events";

class FakeEventSource {
  static last: FakeEventSource | null = null;
  url: string;
  closed = false;
  listeners: Record<string, ((e: { data: string; lastEventId: string }) => void)[]> = {};

  constructor(url: string) {
    this.url = url;
    FakeEventSource.last = this;
  }

  addEventListener(name: string, cb: (e: { data: string; lastEventId: string }) => void) {
    (this.listeners[name] ??= []).push(cb);
  }

  close() {
    this.closed = true;
  }

  emit(name: string, seq: number, data: object) {
    for (const cb of this.listeners[name] ?? []) cb({ data: JSON.stringify(data), lastEventId: String(seq) });
  }
}

describe("followRun", () => {
  it("passes events in order and stops after a terminal event", () => {
    const seen: RunEvent[] = [];
    const ended: string[] = [];
    followRun("r1", (e) => seen.push(e), (name) => ended.push(name), FakeEventSource as unknown as typeof EventSource);
    const source = FakeEventSource.last!;

    source.emit("started", 1, { kind: "extraction" });
    source.emit("progress", 2, { step: "Repository", status: "complete" });
    source.emit("finished", 3, {});

    expect(source.url).toBe("/api/runs/r1/events");
    expect(seen.map((e) => [e.seq, e.event])).toEqual([
      [1, "started"],
      [2, "progress"],
      [3, "finished"],
    ]);
    expect(seen[1].data.step).toBe("Repository");
    expect(ended).toEqual(["finished"]);
    expect(source.closed).toBe(true);
  });

  it("passes llm events through without ending the run", () => {
    const seen: RunEvent[] = [];
    const ended: string[] = [];
    followRun("r1", (e) => seen.push(e), (name) => ended.push(name), FakeEventSource as unknown as typeof EventSource);
    const source = FakeEventSource.last!;

    source.emit("llm", 1, { call_id: "c1", step: "DirectoryClassification", cache_hit: false });

    expect(seen.map((e) => e.event)).toEqual(["llm"]);
    expect(seen[0].data.call_id).toBe("c1");
    expect(ended).toEqual([]);
    expect(source.closed).toBe(false);
  });

  it("dedupes events replayed after a reconnect", () => {
    const seen: number[] = [];
    followRun("r2", (e) => seen.push(e.seq), () => {}, FakeEventSource as unknown as typeof EventSource);
    const source = FakeEventSource.last!;

    source.emit("progress", 1, {});
    source.emit("progress", 2, {});
    source.emit("progress", 2, {});
    source.emit("progress", 1, {});
    source.emit("progress", 3, {});

    expect(seen).toEqual([1, 2, 3]);
  });

  it("can be closed by the caller", () => {
    const close = followRun("r3", () => {}, () => {}, FakeEventSource as unknown as typeof EventSource);

    close();

    expect(FakeEventSource.last!.closed).toBe(true);
  });
});
