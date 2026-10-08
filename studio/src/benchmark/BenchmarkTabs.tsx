import type { BenchmarkGroup, ConsistencyRow, Flip, StepStability } from "../api/types";

const HEADLINE: [string, string][] = [
  ["graph_concepts", "Concepts"],
  ["graph_technologies", "Technologies"],
];

export function pct(row?: ConsistencyRow): string {
  if (!row || row.union === 0) return "n/a";
  return (row.score * 100).toFixed(1);
}

function band(score: number): string {
  return score >= 0.95 ? "hm-ok" : score >= 0.8 ? "hm-fair" : score >= 0.6 ? "hm-warn" : "hm-bad";
}

/** Consistency per repository and model: elements and relationships by name / by source, and the LLM-created graph nodes. */
export function ResultsTable({ groups }: { groups: BenchmarkGroup[] }) {
  if (!groups.length) return <div className="muted">Pick a session to see its results.</div>;
  return (
    <div>
      <table className="results">
        <thead>
          <tr>
            <th>Repository</th>
            <th>Model</th>
            <th>Runs</th>
            {HEADLINE.map(([, title]) => (
              <th key={title}>{title}</th>
            ))}
            <th>Elements name / source</th>
            <th>Relationships name / source</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => {
            const rows = Object.fromEntries(g.rows.map((r) => [r.key, r]));
            return (
              <tr key={`${g.repository}|${g.model}`}>
                <td>{g.repository}</td>
                <td>{g.model}</td>
                <td title={g.counts.map((c) => `${c.label}: ${c.elements} elements, ${c.relationships} relationships`).join("\n")}>{g.runs.length} runs</td>
                {HEADLINE.map(([key]) => (
                  <td key={key}>{pct(rows[key])}</td>
                ))}
                <td title={`${rows.el_source?.common ?? 0} of ${rows.el_source?.union ?? 0} by source in every run`}>
                  {pct(rows.el_name)} / {pct(rows.el_source)}
                </td>
                <td title={`${rows.rel_source?.common ?? 0} of ${rows.rel_source?.union ?? 0} by source in every run`}>
                  {pct(rows.rel_name)} / {pct(rows.rel_source)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {groups.map((g) => (
        <details key={`${g.repository}|${g.model}|detail`} className="note">
          <summary>
            {g.repository} · breakdown per type, provenance and extraction route
          </summary>
          {g.rows
            .filter((r) => r.key.includes(":"))
            .map((r) => (
              <div key={r.key} className="logline">
                {r.key} · {pct(r)} ({r.common}/{r.union})
              </div>
            ))}
        </details>
      ))}
      <div className="note">Budget: 90% by source. Samples per LLM call are 1 in every step (rule 7).</div>
    </div>
  );
}

/** Raw answer stability per step (rows, pipeline order) and repository (columns): where variance starts. */
export function StepsHeatmap({ steps }: { steps: Record<string, StepStability[]> }) {
  const repos = Object.keys(steps);
  if (!repos.length) return <div className="muted">No LLM answers recorded for these sessions.</div>;
  const order: string[] = [];
  for (const repo of repos) for (const s of steps[repo]) if (!order.includes(s.step)) order.push(s.step);
  const cell = (repo: string, step: string) => steps[repo].find((s) => s.step === step);

  return (
    <div style={{ display: "flex", gap: 20 }}>
      <table className="hm">
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Answer stability per step</th>
            {repos.map((r) => (
              <th key={r}>{r}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {order.map((step) => (
            <tr key={step}>
              <td className="hm-step">{step}</td>
              {repos.map((repo) => {
                const s = cell(repo, step);
                return s ? (
                  <td key={repo} className={band(s.score)} title={`${s.identical} of ${s.prompts} prompts answered identically`}>
                    {(s.score * 100).toFixed(1)}
                  </td>
                ) : (
                  <td key={repo} className="faint">
                    n/a
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="note" style={{ maxWidth: 340 }}>
        Where variance starts: the first cell below 95 in pipeline order. Same prompt, different answer means the LLM itself varies.
      </div>
    </div>
  );
}

/** Elements that are not in every run, with the cause per run that misses them. */
export function FlipsList({ flips, repos, repo, onRepo }: { flips: Flip[]; repos: string[]; repo: string; onRepo: (repo: string) => void }) {
  return (
    <div>
      {repos.length > 1 && (
        <select aria-label="Repository" value={repo} onChange={(e) => onRepo(e.target.value)}>
          {repos.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      )}
      {!flips.length && <div className="muted">Every element is in every run.</div>}
      <div className="trace">
        {flips.map((f, i) => (
          <div key={`${f.type}|${f.source}`} className="step">
            <span className="n">{i + 1}</span>
            <div>
              <b>
                {f.type} "{Object.values(f.names)[0] ?? f.source}"
              </b>
              : source {f.source} in {f.present.join(", ")}
              {Object.keys(f.also_from).length > 0 && <span className="faint"> (elsewhere from {Object.entries(f.also_from).map(([run, src]) => `${src} in ${run}`).join(", ")})</span>}
              <div className="muted">{f.cause}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
