import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, configs, runs, trace } from "./client";

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    return error as ApiError;
  }
  throw new Error("expected the request to fail");
}

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(new Response(body === undefined ? "" : JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
}

describe("api client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parses JSON responses", async () => {
    vi.stubGlobal("fetch", respond(200, { status: "ok" }));

    await expect(api.get("/api/health")).resolves.toEqual({ status: "ok" });
  });

  it("sends JSON bodies with the method", async () => {
    const fetchMock = respond(200, { name: "Node", old_version: 21, new_version: 22 });
    vi.stubGlobal("fetch", fetchMock);

    await configs.save("derivation", "Node", { instruction: "text" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/configs/derivation/Node");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ instruction: "text" });
  });

  it("maps a held database to an ApiError with the pid", async () => {
    vi.stubGlobal("fetch", respond(503, { detail: "The databases are held by another process", held_by: 241896 }));

    const error = await failure(api.get("/api/repositories"));

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(503);
    expect(error.heldBy).toBe(241896);
  });

  it("maps a busy session to an ApiError with busy", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => new Response(JSON.stringify({ detail: "A pipeline step is running", busy: true }), { status: 503 })));

    const error = await failure(api.get("/api/graph/stats"));

    expect(error.busy).toBe(true);
    expect(error.message).toContain("pipeline step");
  });

  it("returns the run id and maps a running run to 409", async () => {
    vi.stubGlobal("fetch", respond(202, { run_id: "abc" }));
    await expect(runs.start("extraction", "deriva", true)).resolves.toEqual({ run_id: "abc" });

    vi.stubGlobal("fetch", respond(409, { detail: "Run abc is in progress", run_id: "abc" }));
    const error = await failure(runs.start("extraction", "deriva", false));
    expect(error.status).toBe(409);
  });

  it("fetches a run's calls and one call with its prompt", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await runs.calls("r1");
    await runs.call("r1", "c3");

    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/runs/r1/calls", "/api/runs/r1/calls/c3"]);
  });

  it("asks for an element's trace with the run whose calls to search", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await trace.element("dir::r::src/main", "r1");
    await trace.element("e1", null);

    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/trace/dir%3A%3Ar%3A%3Asrc%2Fmain?run_id=r1", "/api/trace/e1"]);
  });

  it("retries a read while the session is busy, then gives up with busy", async () => {
    const busy = () => new Response(JSON.stringify({ detail: "A pipeline step is running", busy: true }), { status: 503 });
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(async () => busy())
      .mockImplementationOnce(async () => busy())
      .mockImplementationOnce(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/api/graph/stats")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);

    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => busy()));
    const error = await failure(api.get("/api/graph/stats"));
    expect(error.busy).toBe(true);
  });

  it("does not repeat a write that answered busy", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ detail: "busy", busy: true }), { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);

    await failure(api.put("/api/settings/x", { value: "1" }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("encodes path segments", async () => {
    const fetchMock = respond(200, { extension: ".rs", deleted: true });
    vi.stubGlobal("fetch", fetchMock);

    await api.del(`/api/filetypes/${encodeURIComponent(".rs")}`);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/filetypes/.rs");
  });
});
