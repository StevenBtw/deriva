import { useEffect, useRef } from "react";

import type { GraphView, TypeColors } from "../api/types";
import type { Loader } from "./host";
import { useWidget } from "./useWidget";

type Props = {
  database: "graph" | "model";
  view: GraphView;
  typeColors?: TypeColors;
  dark: boolean;
  height?: number;
  loader?: Loader;
};

/** anywidget-graph in grafeo server mode against the studio (/grafeo answers read-only from the embedded databases). */
export function GraphWidget({ database, view, typeColors, dark, height = 420, loader }: Props) {
  const { ref, model, error } = useWidget(
    "/widgets/anywidget-graph/index.js",
    "/widgets/anywidget-graph/styles.css",
    (el) => ({
      nodes: view.nodes,
      edges: view.edges,
      totals: view.totals ?? {},
      type_colors: typeColors ?? {},
      width: el.clientWidth || 600,
      height,
      // Newer anywidget-graph builds fill the host and follow its size; older ones ignore it
      fill: true,
      dark_mode: dark,
      database_backend: "grafeo",
      grafeo_connection_mode: "server",
      grafeo_server_url: `${window.location.origin}/grafeo`,
      connection_database: database,
      query_language: "cypher",
      show_query_input: true,
      // The shim has no Python trait defaults: left out, labels would stay off
      show_labels: true,
      show_toolbar: true,
      show_settings: true,
      max_nodes: 300,
    }),
    loader,
  );

  useEffect(() => {
    if (!model) return;
    model.set({ nodes: view.nodes, edges: view.edges, totals: view.totals ?? {} });
    model.save_changes();
  }, [model, view]);

  useEffect(() => {
    if (!model) return;
    model.set("dark_mode", dark);
    model.save_changes();
  }, [model, dark]);

  // Colours per type follow the theme; only a different set is sent
  const sentColors = useRef<{ model: unknown; key: string } | null>(null);
  useEffect(() => {
    if (!model) return;
    const key = JSON.stringify(typeColors ?? {});
    if (sentColors.current?.model === model && sentColors.current.key === key) return;
    sentColors.current = { model, key };
    model.set("type_colors", typeColors ?? {});
    model.save_changes();
  }, [model, typeColors]);

  return (
    <div className="widget-host">
      {error && (
        <div className="widget-error" role="alert">
          Widget could not be loaded: {error}
        </div>
      )}
      <div ref={ref} />
    </div>
  );
}
