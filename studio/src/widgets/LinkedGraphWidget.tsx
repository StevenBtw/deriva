import { useEffect, useRef } from "react";

import type { LinkedView, Totals, TypeColors, WidgetEdge, WidgetNode } from "../api/types";
import { themeFromTokens } from "../workspace/linkedView";
import type { Loader } from "./host";
import { useWidget } from "./useWidget";

/** New items, plus what leaves (a widget with the "remove" feature fades it out; nothing moves). */
export type AppendBatch = { seq: number; nodes: WidgetNode[]; edges: WidgetEdge[]; remove?: { nodes: string[]; edges: WidgetEdge[] } };

type Props = {
  view: LinkedView;
  batch: AppendBatch | null;
  pulse: string[];
  totals?: Totals;
  typeColors?: TypeColors;
  dark: boolean;
  loader?: Loader;
  onUnsupported?: () => void;
  onFeatures?: (features: string[]) => void;
  onLaneAction?: (lane: string) => void;
};

/** Both graphs in one anywidget-graph canvas: lanes, cross-lane links, live append, pulsing candidates, the studio theme. */
export function LinkedGraphWidget({ view, batch, pulse, totals, typeColors, dark, loader, onUnsupported, onFeatures, onLaneAction }: Props) {
  const { ref, model, error } = useWidget(
    "/widgets/anywidget-graph/index.js",
    "/widgets/anywidget-graph/styles.css",
    (el) => ({
      nodes: view.nodes,
      edges: view.edges,
      lanes: view.lanes,
      theme: themeFromTokens(getComputedStyle(document.documentElement)),
      width: el.clientWidth || 900,
      height: 520,
      fill: true,
      dark_mode: dark,
      show_query_input: false,
      // The shim has no Python trait defaults: left out, labels would stay off
      show_labels: true,
      show_toolbar: true,
      show_settings: true,
      max_nodes: 2000,
      append_stagger_ms: 60,
      append_animation: "draw",
    }),
    loader,
  );
  const sentPulse = useRef("");
  const sentTotals = useRef("");
  const sentColors = useRef("");

  useEffect(() => {
    if (!model) return;
    const features = model.get("_features");
    const list = Array.isArray(features) ? features.map(String) : [];
    onFeatures?.(list);
    if (!list.includes("lanes")) onUnsupported?.();
  }, [model, onUnsupported, onFeatures]);

  // The sample's totals: "shown / total" per type in the widget's legend (builds without "totals" ignore them)
  useEffect(() => {
    if (!model) return;
    const key = JSON.stringify(totals ?? {});
    if (key === sentTotals.current) return;
    sentTotals.current = key;
    model.set("totals", totals ?? {});
    model.save_changes();
  }, [model, totals]);

  // One colour per type for the nodes and the legend (per theme; builds without "type_colors" ignore it)
  useEffect(() => {
    if (!model) return;
    const key = JSON.stringify(typeColors ?? {});
    if (key === sentColors.current) return;
    sentColors.current = key;
    model.set("type_colors", typeColors ?? {});
    model.save_changes();
  }, [model, typeColors]);

  // A click on an action lane's glyph (the model)
  useEffect(() => {
    if (!model || !onLaneAction) return;
    const handler = () => {
      const action = model.get("lane_action") as { lane?: string } | undefined;
      if (action?.lane) onLaneAction(action.lane);
    };
    model.on("change:lane_action", handler);
    return () => model.off("change:lane_action", handler);
  }, [model, onLaneAction]);

  // A full view (first load, or a reload after removals) replaces what is drawn
  useEffect(() => {
    if (!model) return;
    model.set({ lanes: view.lanes, nodes: view.nodes, edges: view.edges });
    model.save_changes();
  }, [model, view]);

  // Batches that arrive before the widget is ready wait here and go in order once it is
  const waiting = useRef<NonNullable<typeof batch>[]>([]);
  useEffect(() => {
    if (!batch) return;
    if (!model) {
      waiting.current.push(batch);
      return;
    }
    const queue = waiting.current.splice(0);
    if (queue[queue.length - 1] !== batch) queue.push(batch);
    for (const item of queue) {
      model.set("append_batch", item);
      model.save_changes();
    }
  }, [model, batch]);

  // Only a different set of candidates is sent: every set redraws the canvas
  useEffect(() => {
    if (!model) return;
    const key = pulse.join("\n");
    if (key === sentPulse.current) return;
    sentPulse.current = key;
    model.set("pulse_nodes", pulse);
    model.save_changes();
  }, [model, pulse]);

  // Theme switch: new colours, nothing reloaded
  useEffect(() => {
    if (!model) return;
    model.set({ dark_mode: dark, theme: themeFromTokens(getComputedStyle(document.documentElement)) });
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
