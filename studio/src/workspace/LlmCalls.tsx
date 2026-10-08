import { useState } from "react";

import { runs } from "../api/client";
import type { LlmCall, RunEvent } from "../api/types";

/** What a call row shows: from a live ``llm`` event or from a listed call. */
export type CallFacts = {
  call_id?: string;
  seq?: number;
  step?: string | null;
  cache_hit?: boolean | null;
  latency_ms?: number | null;
  tokens_in?: number | null;
  temperature?: number | null;
  error?: string | null;
};

const number = new Intl.NumberFormat("en-US");

function milliseconds(ms?: number | null): string {
  const value = ms ?? 0;
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ms`;
}

/** Step, tokens, latency, cache state and temperature (where recorded) of one call, plus its error. */
function facts(d: CallFacts): string[] {
  const parts = [d.step ?? "no step", `${number.format(d.tokens_in ?? 0)} tokens in`, milliseconds(d.latency_ms), d.cache_hit ? "cache hit" : "cache miss"];
  if (d.temperature != null) parts.push(`temperature ${d.temperature}`);
  return d.error ? [...parts, `error: ${d.error}`] : parts;
}

/** A call's prompt and answer, fetched from the run's call log the first time they are opened. */
function useCallDetail(runId: string | null, callId?: string) {
  const [detail, setDetail] = useState<LlmCall | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const load = () => {
    if (detail || !runId || !callId) return;
    runs
      .call(runId, callId)
      .then(setDetail)
      .catch((reason: Error) => setFailed(reason.message));
  };
  return { detail, failed, load };
}

type Part = "prompt" | "answer";

/** One LLM call as a log line (``lead`` before and ``tail`` after its facts) with prompt and answer to unfold. */
export function CallLine({ runId, data, time, lead = [], tail = [] }: { runId: string | null; data: CallFacts; time?: string; lead?: string[]; tail?: string[] }) {
  const [open, setOpen] = useState<Part | null>(null);
  const { detail, failed, load } = useCallDetail(runId, data.call_id);
  const toggle = (part: Part) => {
    setOpen((current) => (current === part ? null : part));
    load();
  };
  const shown = detail ? (open === "prompt" ? detail.prompt : (detail.response ?? detail.error ?? "")) : (failed ?? "Loading…");

  return (
    <>
      <div className={`logline${data.error ? " error" : ""}`}>
        {time !== undefined && <span className="ts">{time}</span>}
        <span className="k">◆</span>
        {[...lead, ...facts(data), ...tail].join(" · ")}
        <button type="button" className="linkbtn" onClick={() => toggle("prompt")}>
          prompt ▸
        </button>
        <button type="button" className="linkbtn" onClick={() => toggle("answer")}>
          answer ▸
        </button>
      </div>
      {open && <div className="expand">{shown}</div>}
    </>
  );
}

/** A live-log line for one LLM call. */
export function LlmLine({ runId, event, time }: { runId: string | null; event: RunEvent; time: string }) {
  return <CallLine runId={runId} data={event.data} time={time} lead={[`LLM #${event.data.seq}`]} />;
}

function PromptRow({ runId, call }: { runId: string | null; call: RunEvent }) {
  const [open, setOpen] = useState(false);
  const { detail, failed, load } = useCallDetail(runId, call.data.call_id);
  const toggle = () => {
    setOpen((o) => !o);
    load();
  };
  const shown = detail ? `PROMPT\n${detail.prompt}\n\nANSWER\n${detail.response ?? detail.error ?? ""}` : (failed ?? "Loading…");

  return (
    <>
      <div className={`logline${call.data.error ? " error" : ""}`}>
        <span className="ts">#{call.data.seq}</span>
        {facts(call.data).join(" · ")}
        <button type="button" className="linkbtn" onClick={toggle}>
          open ▸
        </button>
      </div>
      {open && <div className="expand">{shown}</div>}
    </>
  );
}

/** The run's LLM calls in order, each with its prompt and answer to open. */
export function PromptsList({ runId, calls }: { runId: string | null; calls: RunEvent[] }) {
  if (!calls.length) return <div className="muted">No LLM calls in this run yet.</div>;
  return (
    <div>
      {calls.map((call) => (
        <PromptRow key={call.seq} runId={runId} call={call} />
      ))}
    </div>
  );
}
