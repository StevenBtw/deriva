import { useEffect, useState } from "react";

import { graph } from "../api/client";
import type { GraphView } from "../api/types";
import { GraphWidget } from "../widgets/GraphWidget";

const EMPTY: GraphView = { nodes: [], edges: [] };

/** The intermediate graph and the output graph side by side; reloads when ``refresh`` changes. */
export function GraphLanes({ refresh, dark }: { refresh: number; dark: boolean }) {
  const [views, setViews] = useState<{ graph: GraphView; model: GraphView }>({ graph: EMPTY, model: EMPTY });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([graph.view("graph"), graph.view("model")])
      .then(([g, m]) => {
        if (!cancelled) {
          setViews({ graph: g, model: m });
          setError(null);
        }
      })
      .catch((reason: Error) => !cancelled && setError(reason.message));
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
            <span className="note">
              {views[database].nodes.length} nodes · {views[database].edges.length} edges
            </span>
          </div>
          <div className="lane-body">
            {error ? <div className="widget-error">{error}</div> : <GraphWidget database={database} view={views[database]} dark={dark} />}
          </div>
        </section>
      ))}
    </div>
  );
}
