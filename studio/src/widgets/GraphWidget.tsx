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
  /** Further widget settings (layout, edge_arrows, highlight_neighbors, show_query_input, ...), sent again when they change */
  settings?: Record<string, unknown>;
  /** The node the host selects (null: none), as a viewer's click would */
  selected?: string | null;
  /** The node a viewer selects, or null when the selection is cleared */
  onSelect?: (id: string | null) => void;
};

/** anywidget-graph in grafeo server mode against the studio (/grafeo answers read-only from the embedded databases). */
export function GraphWidget({ database, view, typeColors, dark, height = 420, loader, settings, selected, onSelect }: Props) {
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
      ...settings,
      ...(selected ? { selected_node: { id: selected }, selected_nodes: [selected] } : {}),
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

  // Only a different set of settings is sent (a new object with the same values is no change)
  const sentSettings = useRef("");
  useEffect(() => {
    if (!model || !settings) return;
    const key = JSON.stringify(settings);
    if (key === sentSettings.current) return;
    sentSettings.current = key;
    model.set(settings);
    model.save_changes();
  }, [model, settings]);

  useEffect(() => {
    if (!model || selected === undefined) return;
    const current = model.get("selected_node") as { id?: string } | null | undefined;
    if ((current?.id ?? null) === selected) return;
    model.set({ selected_node: selected ? { id: selected } : null, selected_nodes: selected ? [selected] : [] });
    model.save_changes();
  }, [model, selected]);

  useEffect(() => {
    if (!model || !onSelect) return;
    const report = () => {
      const node = model.get("selected_node") as { id?: unknown } | null | undefined;
      onSelect(node?.id === undefined || node?.id === null ? null : String(node.id));
    };
    model.on("change:selected_node", report);
    return () => model.off("change:selected_node", report);
  }, [model, onSelect]);

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
