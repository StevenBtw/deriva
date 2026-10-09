import { useEffect, useRef } from "react";

import type { ModelElement, ModelRelationship } from "../api/types";
import type { Loader } from "./host";
import { useWidget } from "./useWidget";

type Props = {
  elements: ModelElement[];
  relationships: ModelRelationship[];
  dark: boolean;
  height?: number;
  onSelect?: (element: Record<string, unknown> | null) => void;
  loader?: Loader;
};

/** anywidget-archimate showing the model in its layered view; clicks report the selected element. */
export function ArchimateWidget({ elements, relationships, dark, height = 620, onSelect, loader }: Props) {
  const { ref, model, error } = useWidget(
    "/widgets/anywidget-archimate/index.js",
    "/widgets/anywidget-archimate/styles.css",
    () => ({ elements, relationships, width: "100%", height, dark_mode: dark, selected_element: null }),
    loader,
  );
  const select = useRef(onSelect);

  useEffect(() => {
    select.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    if (!model) return;
    const listener = () => select.current?.((model.get("selected_element") as Record<string, unknown> | null) ?? null);
    model.on("change:selected_element", listener);
    return () => model.off("change:selected_element", listener);
  }, [model]);

  useEffect(() => {
    if (!model) return;
    model.set("elements", elements);
    model.set("relationships", relationships);
    model.save_changes();
  }, [model, elements, relationships]);

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
