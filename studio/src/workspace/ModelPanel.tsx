import { useEffect, useMemo, useRef, useState } from "react";

import { model as modelApi } from "../api/client";
import type { Model, ModelLevel, ModelQuality } from "../api/types";
import { ArchimateWidget } from "../widgets/ArchimateWidget";

// The abstraction levels, as the exchange file's views are: a cross-level link shows on none of them
const LEVELS: readonly (readonly [ModelLevel, string])[] = [
  ["enterprise", "Enterprise"],
  ["solution", "Solution"],
  ["detail", "Detail"],
];

/** The output model in anywidget-archimate at one export level, optionally one generated view of it, with export and the selected element's details. */
export function ModelPanel({ dark, refresh, onSelect }: { dark: boolean; refresh: number; onSelect?: (elementId: string | null) => void }) {
  const [model, setModel] = useState<Model>({ elements: [], relationships: [] });
  const [level, setLevel] = useState<ModelLevel>("enterprise");
  // A view by name ("" = the whole model at this level)
  const [viewName, setViewName] = useState("");
  // The selection is an id: its details come from the model as it is now (a refresh can rename or remove it)
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  // The verdict on the model as a whole (every level); its reasons open on a click
  const [quality, setQuality] = useState<ModelQuality | null>(null);
  const [qualityOpen, setQualityOpen] = useState(false);
  const current = useRef<{ id: string | null; onSelect?: (elementId: string | null) => void }>({ id: null, onSelect });

  useEffect(() => {
    current.current = { id: selectedId, onSelect };
  }, [selectedId, onSelect]);

  useEffect(() => {
    // A slower, older answer must not replace a newer model
    let live = true;
    modelApi
      .get(level)
      .then((found) => {
        if (!live) return;
        setModel(found);
        setViewName((name) => (found.views ?? []).some((v) => v.name === name) ? name : "");
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
  }, [refresh, level]);

  useEffect(() => {
    let live = true;
    modelApi
      .quality()
      .then((found) => live && setQuality(found))
      .catch(() => live && setQuality(null));
    return () => {
      live = false;
    };
  }, [refresh]);

  const shown = useMemo(() => {
    const view = (model.views ?? []).find((v) => v.name === viewName);
    if (!view) return model;
    const ids = new Set(view.elements);
    // The relationships the view names (its level's); without the list, every relationship between its elements
    const named = view.relationships ? new Set(view.relationships) : null;
    const relationships = model.relationships.filter((r) => (named ? named.has(String(r.id)) : ids.has(r.source) && ids.has(r.target)));
    return { elements: model.elements.filter((e) => ids.has(String(e.id))), relationships };
  }, [model, viewName]);

  const selected = selectedId === null ? null : (model.elements.find((e) => String(e.id) === selectedId) ?? null);

  const select = (element: Record<string, unknown> | null) => {
    const id = element?.id ? String(element.id) : null;
    setSelectedId(id);
    onSelect?.(id);
  };

  // A download the browser saves; the studio keeps a copy under the same name in workspace/output
  const exportXml = async () => {
    try {
      const { blob, name } = await modelApi.download();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      link.click();
      URL.revokeObjectURL(url);
      setMessage(`Downloaded ${name}`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <div className="modelpanel">
      <div className="modelpanel-head">
        <b>Output model</b>
        <span className="muted">
          {shown.elements.length} elements · {shown.relationships.length} relationships
        </span>
        <span role="radiogroup" aria-label="Level" style={{ display: "inline-flex", gap: 8 }}>
          {LEVELS.map(([value, label]) => (
            <label key={value}>
              <input type="radio" name="model-level" value={value} checked={level === value} onChange={() => setLevel(value)} /> {label}
            </label>
          ))}
        </span>
        <label htmlFor="model-view" className="muted">
          Viewpoint
        </label>
        <select id="model-view" value={viewName} onChange={(e) => setViewName(e.target.value)}>
          <option value="">Whole model</option>
          {(model.views ?? []).map((v) => (
            <option key={v.name} value={v.name}>
              {v.name}
            </option>
          ))}
        </select>
        {message && <span className="note">{message}</span>}
        {quality && (
          <button
            type="button"
            className={`pill ${quality.verdict === "ok" ? "ok" : "warn"}`}
            aria-expanded={qualityOpen}
            title={quality.reasons.join("; ") || "No orphans, behaviour as well as structure, both layers, evidence behind every element"}
            onClick={() => setQualityOpen((open) => !open)}
          >
            {`Quality: ${quality.verdict}`}
          </button>
        )}
        <button type="button" style={{ marginLeft: "auto" }} onClick={exportXml}>
          ⤓ Export XML
        </button>
      </div>
      {quality && qualityOpen && (
        <div className="bd" style={{ padding: "0 14px 8px" }}>
          {quality.reasons.length === 0 && <div className="ok">Nothing to note.</div>}
          {quality.reasons.map((reason) => (
            <div key={reason} className="warn">
              {reason}
            </div>
          ))}
          {quality.unsupported.map((element) => (
            <div key={element.id} className="note mono">
              {`${element.name} (${element.type}) ← ${element.sources.join(", ")}`}
            </div>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 10, padding: "0 14px 14px", minHeight: 0 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <ArchimateWidget elements={shown.elements} relationships={shown.relationships} dark={dark} onSelect={select} />
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
