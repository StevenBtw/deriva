import { useEffect, useRef, useState } from "react";

import { model as modelApi } from "../api/client";
import type { Model } from "../api/types";
import { ArchimateWidget } from "../widgets/ArchimateWidget";

/** The output model in anywidget-archimate, with export and the selected element's details. */
export function ModelPanel({ dark, refresh, onSelect }: { dark: boolean; refresh: number; onSelect?: (elementId: string | null) => void }) {
  const [model, setModel] = useState<Model>({ elements: [], relationships: [] });
  // The selection is an id: its details come from the model as it is now (a refresh can rename or remove it)
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const current = useRef<{ id: string | null; onSelect?: (elementId: string | null) => void }>({ id: null, onSelect });

  useEffect(() => {
    current.current = { id: selectedId, onSelect };
  }, [selectedId, onSelect]);

  useEffect(() => {
    // A slower, older answer must not replace a newer model
    let live = true;
    modelApi
      .get()
      .then((found) => {
        if (!live) return;
        setModel(found);
        const { id, onSelect: notify } = current.current;
        if (id !== null && !found.elements.some((e) => String(e.id) === id)) {
          setSelectedId(null);
          notify?.(null);
        }
      })
      .catch((reason: Error) => live && setMessage(reason.message));
    return () => {
      live = false;
    };
  }, [refresh]);

  const selected = selectedId === null ? null : (model.elements.find((e) => String(e.id) === selectedId) ?? null);

  const select = (element: Record<string, unknown> | null) => {
    const id = element?.id ? String(element.id) : null;
    setSelectedId(id);
    onSelect?.(id);
  };

  const exportXml = async () => {
    try {
      const result = await modelApi.exportXml("workspace/output/model.xml");
      setMessage(result.success ? `Exported to ${result.path ?? "workspace/output/model.xml"}` : (result.error ?? "Export failed"));
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <div className="modelpanel">
      <div className="modelpanel-head">
        <b>Output model</b>
        <span className="muted">
          {model.elements.length} elements · {model.relationships.length} relationships
        </span>
        {message && <span className="note">{message}</span>}
        <button type="button" style={{ marginLeft: "auto" }} onClick={exportXml}>
          ⤓ Export XML
        </button>
      </div>
      <div style={{ display: "flex", gap: 10, padding: "0 14px 14px", minHeight: 0 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <ArchimateWidget elements={model.elements} relationships={model.relationships} dark={dark} onSelect={select} />
        </div>
        {selected && (
          <aside className="card" style={{ width: 240 }}>
            <div className="hd">
              <h3>{selected.name || selected.id}</h3>
            </div>
            <div className="bd kv" style={{ gridTemplateColumns: "80px 1fr" }}>
              <span className="muted">Type</span>
              <span>{selected.type}</span>
              <span className="muted">Id</span>
              <span className="mono">{selected.id}</span>
              <span className="muted">Trace</span>
              <span className="note">Sources, relationships and LLM calls in the Trace tab below.</span>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
