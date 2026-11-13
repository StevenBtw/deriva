import { useCallback, useEffect, useState } from "react";

import { model as modelApi } from "../api/client";
import type { ExportResult, ModelExports } from "../api/types";
import { size } from "../components/size";

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function when(seconds: number): string {
  const date = new Date(seconds * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** The name as it will be written: trimmed, with .xml added when it has no .xml extension. */
function fileName(name: string): string {
  const trimmed = name.trim();
  return !trimmed || /\.xml$/i.test(trimmed) ? trimmed : `${trimmed}.xml`;
}

/**
 * Export config: write the model as an ArchiMate exchange file into workspace/output, under a chosen name.
 * Shows the folder, the full path before saving, what the save wrote, and the exports already there.
 */
export function Model() {
  const [info, setInfo] = useState<ModelExports | null>(null);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<ExportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // After a save: the list again (the new file in it), keeping the name as typed
  const refresh = useCallback(async () => {
    try {
      setInfo(await modelApi.exports());
    } catch (reason) {
      setError(message(reason));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    modelApi
      .exports()
      .then((next) => {
        if (cancelled) return;
        setInfo(next);
        setName(next.suggested);
      })
      .catch((reason: unknown) => !cancelled && setError(message(reason)));
    return () => {
      cancelled = true;
    };
  }, []);

  const target = fileName(name);
  const invalid = /[\\/]/.test(name) || name.includes("..");
  const separator = info?.folder.includes("\\") ? "\\" : "/";
  const fullPath = info && target ? `${info.folder}${separator}${target}` : "";
  const replaces = Boolean(info?.files.some((file) => file.name === target));

  const save = async () => {
    setSaving(true);
    setResult(null);
    setError(null);
    try {
      const written = await modelApi.save(`workspace/output/${target}`);
      if (written.success) setResult(written);
      else setError(written.error ?? "The export failed");
      await refresh();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="page">
      <div className="pagehead">
        <h2>Export config</h2>
        <span className="sub">The model as an ArchiMate exchange file, to open in Archi</span>
      </div>
      <div className="pad stack">
        <div className="card export">
          <div className="export-row">
            <label htmlFor="export-name">File name</label>
            <input id="export-name" value={name} spellCheck={false} onChange={(event) => setName(event.target.value)} />
            <button type="button" className="primary small" disabled={saving || invalid || !target || !info} onClick={save}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
          {invalid ? (
            <p className="export-note bad">A file name only: the export always goes to the output folder.</p>
          ) : (
            fullPath && (
              <p className="export-note">
                Saves to <code className="export-path">{fullPath}</code>
                {replaces && <span className="warn"> · replaces {target}</span>}
              </p>
            )
          )}
          {result && (
            <p className="export-note ok">
              Saved: {result.elements_exported ?? 0} elements · {result.relationships_exported ?? 0} relationships · {result.views_exported ?? 0} views
            </p>
          )}
          {error && <p className="export-note bad">{error}</p>}
        </div>

        <div className="card export">
          <div className="export-head">
            <h3>Exports in the output folder</h3>
            {info && <code className="export-path">{info.folder}</code>}
          </div>
          {info && info.files.length === 0 && <p className="faint">No exports yet.</p>}
          {info && info.files.length > 0 && (
            <table className="export-list">
              <tbody>
                {info.files.map((file) => (
                  <tr key={file.name}>
                    <td className="mono">{file.name}</td>
                    <td className="num">{size(file.bytes)}</td>
                    <td className="num">{when(file.modified)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </section>
  );
}
