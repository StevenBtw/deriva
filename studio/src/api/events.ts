import type { RunEvent, RunEventName } from "./types";

const NAMES: RunEventName[] = ["started", "progress", "llm", "finished", "cancelled", "error"];
const TERMINAL: RunEventName[] = ["finished", "cancelled", "error"];

/**
 * Follow a run's server-sent events. The browser reconnects by itself with Last-Event-ID;
 * events it receives twice around a reconnect are dropped by sequence number.
 * Returns a function that stops following.
 */
export function followRun(
  runId: string,
  onEvent: (event: RunEvent) => void,
  onEnd: (name: RunEventName, lost?: boolean) => void,
  Source: typeof EventSource = EventSource,
): () => void {
  const source = new Source(`/api/runs/${encodeURIComponent(runId)}/events`);
  let lastSeq = 0;
  let closed = false;

  const close = () => {
    if (!closed) {
      closed = true;
      source.close();
    }
  };

  // A stream the browser gave up (a run the server no longer knows, after a restart) ends with ``lost``:
  // the caller decides what that says about the run; while it reconnects (readyState CONNECTING) the run goes on
  source.onerror = () => {
    if (!closed && source.readyState === 2) {
      close();
      onEnd("error", true);
    }
  };

  for (const name of NAMES) {
    source.addEventListener(name, (raw: Event) => {
      const message = raw as MessageEvent<string>;
      const seq = Number(message.lastEventId);
      if (!Number.isFinite(seq) || seq <= lastSeq) return;
      lastSeq = seq;
      onEvent({ seq, event: name, data: JSON.parse(message.data) });
      if (TERMINAL.includes(name)) {
        close();
        onEnd(name);
      }
    });
  }
  return close;
}
