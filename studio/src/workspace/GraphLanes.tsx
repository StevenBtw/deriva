import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { graph } from "../api/client";
import type { GraphView, LinkedView } from "../api/types";
import { GraphWidget } from "../widgets/GraphWidget";
import { type AppendBatch, LinkedGraphWidget } from "../widgets/LinkedGraphWidget";
import { changedElements, clusterPaletteFromTokens, lanesChanged, linkedNote, newItems, removedItems, toWidgetIds, typeColors, viewNote, withClusterColors, withLaneLayouts, withLayerColors, withModelLane } from "./linkedView";

const EMPTY: GraphView = { nodes: [], edges: [] };
// A view as the widget draws it in full: the model lane at the end, the elements in their layer colours
const drawn = (view: LinkedView): LinkedView => ({ ...view, lanes: withModelLane(withLaneLayouts(view.lanes)), nodes: withLayerColors(view.nodes) });
// Rank filters: all nodes, or those at or above a PageRank percentile (the elements' sources always stay)
const RANKS = [
  { label: "All", minRank: undefined },
  { label: "Top 50%", minRank: 50 },
  { label: "Top 20%", minRank: 80 },
] as const;

type Drawn = { nodes: number; edges: number };

/** The intermediate graph and the output graph: linked in one canvas (live links), or as two separate graphs to explore. */
export function GraphLanes({ refresh, dark, pulse = [], onOpenModel }: { refresh: number; dark: boolean; pulse?: string[]; onOpenModel?: () => void }) {
  const [mode, setMode] = useState<"linked" | "separate">("linked");
  const unsupported = useCallback(() => setMode("separate"), []);

  return (
    <div className="lanes-host">
      <div className="seg lanes-switch" role="group" aria-label="Graph view">
        {(["linked", "separate"] as const).map((m) => (
          <button key={m} type="button" className={mode === m ? "on" : ""} aria-pressed={mode === m} onClick={() => setMode(m)}>
            {m === "linked" ? "Linked" : "Separate"}
          </button>
        ))}
      </div>
      {mode === "linked" ? (
        <LinkedLanes refresh={refresh} dark={dark} pulse={pulse} onUnsupported={unsupported} onOpenModel={onOpenModel} />
      ) : (
        <SeparateLanes refresh={refresh} dark={dark} />
      )}
    </div>
  );
}

/**
 * One linked canvas: the first view drawn in full, every later step as one batch (its new items, and what left the sample
 * or the model, which a widget with "remove" fades out in place; an older widget redraws instead); the model's glyph ends it.
 */
function LinkedLanes({
  refresh,
  dark,
  pulse,
  onUnsupported,
  onOpenModel,
}: {
  refresh: number;
  dark: boolean;
  pulse: string[];
  onUnsupported: () => void;
  onOpenModel?: () => void;
}) {
  // base: the view the widget was last drawn from in full; current: base plus every batch since
  const [base, setBase] = useState<LinkedView | null>(null);
  const [current, setCurrent] = useState<LinkedView | null>(null);
  const [batch, setBatch] = useState<AppendBatch | null>(null);
  const shown = useRef<LinkedView | null>(null);
  const seq = useRef(0);
  // What the widget build supports (its _features); a ref, since it only steers the next refresh
  const features = useRef<string[]>([]);
  const onFeatures = useCallback((list: string[]) => {
    features.current = list;
  }, []);
  const [error, setError] = useState<string | null>(null);
  const [minRank, setMinRank] = useState<number | undefined>(undefined);
  const [colourBy, setColourBy] = useState<"type" | "cluster">("type");
  // A new rank filter draws the view afresh (it is a different sample, not the next step of a run)
  const drawnRank = useRef<number | undefined>(undefined);
  // Colouring by cluster recolours the whole view at every step (the clusters change as it grows): no batches then
  const byCluster = useRef(false);
  // Every full draw ends the batches: the last one is not sent again on top of it
  const redraw = useCallback((view: LinkedView) => {
    setBase(drawn(view));
    setBatch(null);
  }, []);
  // A new colour mode draws the whole current view (base and the batches since), not the base alone
  const colourWith = (by: "type" | "cluster") => {
    if (by === colourBy) return;
    byCluster.current = by === "cluster";
    setColourBy(by);
    if (current) redraw(current);
  };

  useEffect(() => {
    let cancelled = false;
    if (drawnRank.current !== minRank) {
      shown.current = null;
      drawnRank.current = minRank;
    }
    graph
      .linked(undefined, minRank)
      .then((next) => {
        if (cancelled) return;
        setError(null);
        const previous = shown.current;
        shown.current = next;
        setCurrent(next);
        const removed = previous ? removedItems(previous, next) : null;
        const changed = previous ? changedElements(previous, next) : [];
        const leaving = Boolean(removed && (removed.nodes.length || removed.edges.length || changed.length));
        if (!previous || !removed || byCluster.current || lanesChanged(previous, next) || !features.current.includes("append") || (leaving && !features.current.includes("remove"))) {
          redraw(next);
          return;
        }
        const items = newItems(previous, next);
        if (!items.nodes.length && !items.edges.length && !leaving) return;
        const remove = removed.nodes.length || removed.edges.length ? { remove: removed } : {};
        // Changed elements go again with their new state (grey when rejected); the widget keeps them where they are
        setBatch({ seq: ++seq.current, nodes: withLayerColors([...changed, ...items.nodes]), edges: items.edges, ...remove });
      })
      .catch((reason: Error) => {
        // A refresh that misses its turn during a run keeps what is drawn; the next step or the run's end catches up
        if (!cancelled && !shown.current) setError(reason.message);
      });
    return () => {
      cancelled = true;
    };
  }, [refresh, minRank, redraw]);

  // Colour by cluster: the eight largest Louvain clusters of the whole current view take the cluster palette
  const clusterColour = useMemo(() => {
    if (colourBy !== "cluster" || !current) return null;
    const { palette, other } = clusterPaletteFromTokens(getComputedStyle(document.documentElement));
    return new Map(withClusterColors(current.nodes, palette, other).filter((n) => n.lane === "intermediate").map((n) => [n.id, n.color as string]));
    // dark: the palette is read again when the theme changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [colourBy, current, dark]);
  const paint = useCallback(<T extends { id: string }>(nodes: T[]): T[] => (clusterColour ? nodes.map((n) => (clusterColour.has(n.id) ? { ...n, color: clusterColour.get(n.id) } : n)) : nodes), [clusterColour]);
  // Batches come only while colouring by type, so they need no paint (a new paint object would send one again)
  const shownView = useMemo(() => (base ? { ...base, nodes: paint(base.nodes) } : null), [base, paint]);

  const pulseIds = useMemo(() => (current ? toWidgetIds(current, pulse) : []), [current, pulse]);
  const colors = useMemo(() => typeColors(current?.nodes ?? [], dark), [current, dark]);
  const onLaneAction = useCallback((lane: string) => lane === "model" && onOpenModel?.(), [onOpenModel]);

  if (error) return <div className="widget-error">{error}</div>;
  if (!base || !current || !shownView) return <div className="faint">Loading the graphs…</div>;
  return (
    <section className="lane lane-linked">
      <div className="lane-title">
        Repository to model
        <span className="note">
          {linkedNote(current)}
          {current.missing_links > 0 && ` · ${current.missing_links} links not shown`}
        </span>
      </div>
      <div className="lane-tools">
        <div className="seg" role="group" aria-label="Colour the intermediate graph by">
          {(["type", "cluster"] as const).map((by) => (
            <button key={by} type="button" className={colourBy === by ? "on" : ""} aria-pressed={colourBy === by} onClick={() => colourWith(by)}>
              {by === "type" ? "Type" : "Cluster"}
            </button>
          ))}
        </div>
        <div className="seg" role="group" aria-label="Show graph nodes by rank">
          {RANKS.map((rank) => (
            <button key={rank.label} type="button" className={minRank === rank.minRank ? "on" : ""} aria-pressed={minRank === rank.minRank} onClick={() => setMinRank(rank.minRank)}>
              {rank.label}
            </button>
          ))}
        </div>
        {colourBy === "cluster" && <span className="note">the eight largest Louvain clusters in colour, the rest in grey</span>}
      </div>
      <div className="lane-body">
        <LinkedGraphWidget
          view={shownView}
          batch={batch}
          pulse={pulseIds}
          totals={current.totals}
          typeColors={colors}
          dark={dark}
          onUnsupported={onUnsupported}
          onFeatures={onFeatures}
          onLaneAction={onLaneAction}
        />
      </div>
    </section>
  );
}

/** The two graphs side by side, each with its own query bar. */
function SeparateLanes({ refresh, dark }: { refresh: number; dark: boolean }) {
  const [views, setViews] = useState<{ graph: GraphView; model: GraphView }>({ graph: EMPTY, model: EMPTY });
  // Each graph loads and fails on its own: one failed query keeps the other lane
  const [errors, setErrors] = useState<{ graph?: string; model?: string }>({});
  // What each widget draws: its view, or the result of a query typed in its query box
  const [drawn, setDrawn] = useState<{ graph?: Drawn; model?: Drawn }>({});
  const onDrawn = useMemo(
    () => ({
      graph: (counts: Drawn) => setDrawn((current) => ({ ...current, graph: counts })),
      model: (counts: Drawn) => setDrawn((current) => ({ ...current, model: counts })),
    }),
    [],
  );
  // The model pane's nodes are all elements (the output lane's role in the linked view)
  const colors = useMemo(
    () => ({ graph: typeColors([], dark), model: typeColors(views.model.nodes.map((node) => ({ ...node, lane: "output" })), dark) }),
    [views, dark],
  );

  useEffect(() => {
    let cancelled = false;
    for (const database of ["graph", "model"] as const) {
      graph
        .view(database)
        .then((view) => {
          if (cancelled) return;
          setViews((current) => ({ ...current, [database]: view }));
          setErrors((current) => ({ ...current, [database]: undefined }));
        })
        .catch((reason: Error) => !cancelled && setErrors((current) => ({ ...current, [database]: reason.message })));
    }
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  return (
    <div className="lanes">
      {(["graph", "model"] as const).map((database) => (
        <section key={database} className="lane">
          <div className="lane-title">
            {database === "graph" ? "Intermediate graph" : "Output graph (model)"}
            <span className="note">{viewNote(views[database], drawn[database])}</span>
          </div>
          <div className="lane-body">
            {errors[database] ? <div className="widget-error">{errors[database]}</div> : <GraphWidget database={database} view={views[database]} typeColors={colors[database]} dark={dark} onDrawn={onDrawn[database]} />}
          </div>
        </section>
      ))}
    </div>
  );
}
