import { useState } from "react";

import type { InspectorView } from "../api/types";
import { useTheme } from "../theme/theme";
import { ArchimateWidget } from "../widgets/ArchimateWidget";
import { diagramOf, type Filter, type Identity, type Item, itemsOf, keep, type Status, statusPair, statusRun, statusUnion } from "./inspect";

type View = { kind: "union" } | { kind: "run"; run: string } | { kind: "side" };
type Group = "layer" | "cause";

const LAYERS: [string, string][] = [
  ["Business", "biz"],
  ["Application", "appl"],
  ["Technology", "tech"],
  ["Other", "other"],
];

function Pill({ on, onClick, children }: { on: boolean; onClick: () => void; children: string }) {
  return (
    <button type="button" className={`pill${on ? " on" : ""}`} aria-pressed={on} onClick={onClick}>
      {children}
    </button>
  );
}

function Box({ item, status, run, onSelect }: { item: Item; status: Status; run?: string; onSelect?: (item: Item) => void }) {
  const layer = LAYERS.find(([name]) => name === item.layer)?.[1] ?? "other";
  const name = (run && item.byRun[run]?.name) || item.name;
  return (
    <div className={`el ${layer} ${status.cls}`} onClick={() => onSelect?.(item)}>
      <div className="t">{item.type}</div>
      {name}
      {status.text && <div className={`st ${status.diff ? "warn" : "faint"}`}>{status.text}</div>}
    </div>
  );
}

function Layers({ rows, group, run, onSelect }: { rows: [Item, Status][]; group: Group; run?: string; onSelect?: (item: Item) => void }) {
  if (!rows.length) return <div className="diffsum">Nothing to show with this filter.</div>;
  if (group === "cause") {
    const groups = new Map<string, [Item, Status][]>();
    for (const row of rows) {
      const key = row[1].diff ? (row[0].cause ?? "other") : "Stable";
      groups.set(key, [...(groups.get(key) ?? []), row]);
    }
    const ordered = [...groups.entries()].sort((a, b) => Number(a[0] === "Stable") - Number(b[0] === "Stable"));
    return (
      <>
        {ordered.map(([cause, items]) => (
          <div key={cause} className="layer cause">
            <div className="lt">
              {cause} · {items.length}
            </div>
            <div className="els">
              {items.map(([item, status]) => (
                <Box key={item.key} item={item} status={status} run={run} onSelect={onSelect} />
              ))}
            </div>
          </div>
        ))}
      </>
    );
  }
  return (
    <>
      {LAYERS.filter(([name]) => name !== "Other" || rows.some(([i]) => i.layer === "Other")).map(([name, cls]) => {
        const items = rows.filter(([item]) => item.layer === name);
        return (
          <div key={name} className={`layer ${cls}`}>
            <div className="lt">{name}</div>
            <div className="els">
              {items.length ? items.map(([item, status]) => <Box key={item.key} item={item} status={status} run={run} onSelect={onSelect} />) : <span className="faint">none</span>}
            </div>
          </div>
        );
      })}
    </>
  );
}

/** The runs' models of one repository: all runs (agreement), one run, or two side by side; filtered, by source or name, grouped by layer or cause. */
export function Inspector({ view, onSelect }: { view: InspectorView | null; onSelect?: (item: Item) => void }) {
  const [shown, setShown] = useState<View>({ kind: "union" });
  const [filter, setFilter] = useState<Filter>("all");
  const [identity, setIdentity] = useState<Identity>("source");
  const [group, setGroup] = useState<Group>("layer");
  const [pair, setPair] = useState<{ a?: string; b?: string }>({});
  const [asDiagram, setAsDiagram] = useState(false);
  const [, , shownTheme] = useTheme();

  if (!view) return <div className="diffsum">Pick a session to inspect its models.</div>;
  const runs = view.runs;
  const items = itemsOf(view, identity);
  const a = pair.a ?? runs[0];
  const b = pair.b ?? runs[1] ?? runs[0];

  let body;
  if (asDiagram && shown.kind !== "side") {
    const diagram = diagramOf(view, identity, shown, filter);
    const byKey = new Map(items.map((item) => [item.key, item]));
    body = (
      <ArchimateWidget
        elements={diagram.elements}
        relationships={diagram.relationships}
        dark={shownTheme === "dark"}
        onSelect={(element) => {
          const item = element ? byKey.get(String(element.id)) : undefined;
          if (item) onSelect?.(item);
        }}
      />
    );
  } else if (shown.kind === "side") {
    const side = (s: "a" | "b") => items.map((item) => [item, statusPair(item, s, a, b, identity)] as [Item, Status | null]).filter((row): row is [Item, Status] => keep(row[1], filter));
    const differences = items.filter((item) => statusPair(item, "a", a, b, identity)?.diff).length;
    body = (
      <>
        <div className="diffsum">
          {a} vs {b} · {differences} difference{differences === 1 ? "" : "s"} by {identity} · faded = absent on this side
        </div>
        <div className="sbs">
          {(["a", "b"] as const).map((s) => (
            <div key={s}>
              <div className="colhd">{s === "a" ? a : b}</div>
              <Layers rows={side(s)} group={group} run={s === "a" ? a : b} onSelect={onSelect} />
            </div>
          ))}
        </div>
      </>
    );
  } else {
    const status = (item: Item) => (shown.kind === "run" ? statusRun(item, shown.run, runs, identity) : statusUnion(item, runs, identity));
    const rows = items.map((item) => [item, status(item)] as [Item, Status]).filter(([, st]) => keep(st, filter));
    const differences = items.filter((item) => status(item).diff).length;
    body = (
      <>
        <div className="diffsum">
          {shown.kind === "run" ? shown.run : `All ${runs.length} runs`} · {differences} of {items.length} elements differ by {identity}
          {identity === "name" ? " (source flips count as the same element)" : ""}
        </div>
        <Layers rows={rows} group={group} run={shown.kind === "run" ? shown.run : undefined} onSelect={onSelect} />
      </>
    );
  }

  return (
    <div className="inspector">
      <div className="modelbar">
        <div className="grp2">
          <span>Model</span>
          <Pill on={shown.kind === "union"} onClick={() => setShown({ kind: "union" })}>
            All runs
          </Pill>
          {runs.map((run) => (
            <Pill key={run} on={shown.kind === "run" && shown.run === run} onClick={() => setShown({ kind: "run", run })}>
              {run}
            </Pill>
          ))}
          <Pill on={shown.kind === "side"} onClick={() => setShown({ kind: "side" })}>
            Side by side
          </Pill>
        </div>
        {shown.kind === "side" && (
          <div className="grp2">
            <span>A</span>
            <select aria-label="Run A" value={a} onChange={(e) => setPair((p) => ({ ...p, a: e.target.value }))}>
              {runs.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
            <span>B</span>
            <select aria-label="Run B" value={b} onChange={(e) => setPair((p) => ({ ...p, b: e.target.value }))}>
              {runs.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </div>
        )}
        <div className="grp2">
          <span>Show</span>
          <Pill on={filter === "all"} onClick={() => setFilter("all")}>
            Everything
          </Pill>
          <Pill on={filter === "diff"} onClick={() => setFilter("diff")}>
            Only differences
          </Pill>
          <Pill on={filter === "stable"} onClick={() => setFilter("stable")}>
            Only stable
          </Pill>
        </div>
        <div className="grp2">
          <span>Identity</span>
          <Pill on={identity === "source"} onClick={() => setIdentity("source")}>
            by source
          </Pill>
          <Pill on={identity === "name"} onClick={() => setIdentity("name")}>
            by name
          </Pill>
        </div>
        {shown.kind !== "side" && (
          <div className="grp2">
            <span>Show as</span>
            <Pill on={!asDiagram} onClick={() => setAsDiagram(false)}>
              Boxes
            </Pill>
            <Pill on={asDiagram} onClick={() => setAsDiagram(true)}>
              Diagram
            </Pill>
          </div>
        )}
        <div className="grp2">
          <span>Group</span>
          <Pill on={group === "layer"} onClick={() => setGroup("layer")}>
            by layer
          </Pill>
          <Pill on={group === "cause"} onClick={() => setGroup("cause")}>
            by cause
          </Pill>
        </div>
      </div>
      {body}
    </div>
  );
}
