import { useEffect } from "react";

import type { GraphView } from "../api/types";
import type { Loader } from "./host";
import { useWidget } from "./useWidget";

type Props = {
  database: "graph" | "model";
  view: GraphView;
  dark: boolean;
  height?: number;
  loader?: Loader;
};

/** anywidget-graph in grafeo server mode against the studio (/grafeo answers read-only from the embedded databases). */
export function GraphWidget({ database, view, dark, height = 420, loader }: Props) {
  const { ref, model, error } = useWidget(
    "/widgets/anywidget-graph/index.js",
    "/widgets/anywidget-graph/styles.css",
    (el) => ({
      nodes: view.nodes,
      edges: view.edges,
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
      show_toolbar: true,
      show_settings: true,
      max_nodes: 300,
    }),
    loader,
  );

  useEffect(() => {
    if (!model) return;
    model.set("nodes", view.nodes);
    model.set("edges", view.edges);
    model.save_changes();
  }, [model, view]);

  useEffect(() => {
    if (!model) return;
    model.set("dark_mode", dark);
    model.save_changes();
  }, [model, dark]);

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
