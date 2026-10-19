import type { DbStatus } from "../api/types";
import { nextTheme, useTheme } from "../theme/theme";
import { GITHUB_URL, detectBrowser, detectOs, newIssueUrl } from "./issueReport";
import { Logo } from "./Logo";

export type Mode = "run" | "benchmark";

const THEME_LABEL = { system: "System", light: "Light", dark: "Dark" } as const;

type Props = {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  db: DbStatus;
  version?: string;
  /** False when the install has no benchmarking (deriva-studio without deriva-dev): only Run mode. */
  benchmark?: boolean;
  /** The machine the studio server runs on (from /api/status); the browser is detected here. */
  environment?: { os?: string; python?: string };
  status?: string;
  onOpenDocs?: () => void;
  onOpenLlm?: () => void;
};

export function TopBar({ mode, onModeChange, db, version, benchmark = true, environment, status, onOpenDocs, onOpenLlm }: Props) {
  const [theme, setTheme] = useTheme();
  const dbLabel = db.unanswered
    ? "Studio not answering"
    : db.busy
      ? "DB busy"
      : db.state === "owned"
        ? "DB"
        : db.state === "held"
          ? `DB held (PID ${db.held_by ?? "?"})`
          : "DB not connected";
  const dbTitle = db.unanswered ? `The studio did not answer its last status request; last known state: ${db.state}` : (db.error ?? undefined);
  /** A new bug report with what this install knows about itself pre-filled. */
  const issueUrl = newIssueUrl({
    version,
    install: benchmark ? "deriva-dev" : "deriva-studio",
    os: environment?.os ?? detectOs(),
    python: environment?.python,
    browser: detectBrowser(),
  });

  return (
    <header className="topbar">
      <div className="logo">
        <Logo />
        Deriva Studio
        {version && <span className="version">v{version}</span>}
      </div>
      {benchmark && (
        <div className="seg" role="group" aria-label="Mode">
          <button type="button" className={mode === "run" ? "on" : ""} aria-pressed={mode === "run"} onClick={() => onModeChange("run")}>
            Run
          </button>
          <button type="button" className={mode === "benchmark" ? "on" : ""} aria-pressed={mode === "benchmark"} onClick={() => onModeChange("benchmark")}>
            Benchmark
          </button>
        </div>
      )}
      {status && <div className="runstatus">{status}</div>}
      <div className="topbar-right">
        {onOpenLlm && (
          <button type="button" className="util" onClick={onOpenLlm}>
            ⚿ LLM
          </button>
        )}
        <button type="button" className="util" aria-label={`Theme: ${THEME_LABEL[theme]}`} onClick={() => setTheme(nextTheme(theme))}>
          ◐ {THEME_LABEL[theme]}
        </button>
        <a className="util" href="/docs" target="_blank" rel="noreferrer">
          {"{ }"} API
        </a>
        {onOpenDocs && (
          <button type="button" className="util" onClick={onOpenDocs}>
            ? Docs
          </button>
        )}
        <a className="util" href={GITHUB_URL} target="_blank" rel="noreferrer">
          <GitHubMark />
          GitHub
        </a>
        <a className="util" href={issueUrl} target="_blank" rel="noreferrer">
          <BugIcon />
          Report issue
        </a>
        <span className={`util db-${db.state}`} title={dbTitle}>
          <span className="dot" aria-hidden="true" />
          {dbLabel}
        </span>
      </div>
    </header>
  );
}

/** The GitHub mark, small and monochrome (the theme colours it through currentColor). */
function GitHubMark() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"
      />
    </svg>
  );
}

/** A small bug glyph for the report issue link. */
function BugIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="3.4" r="1.7" fill="currentColor" />
      <ellipse cx="8" cy="9.2" rx="3.4" ry="4.4" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path
        d="M8 4.8v8.8M4.6 9.2h6.8M5.4 6.4 3.2 4.6M10.6 6.4l2.2-1.8M5.4 12 3.2 13.8M10.6 12l2.2 1.8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}
