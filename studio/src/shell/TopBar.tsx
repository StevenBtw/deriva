import type { DbStatus } from "../api/types";
import { nextTheme, useTheme } from "../theme/theme";
import { Logo } from "./Logo";

export type Mode = "run" | "benchmark";

const THEME_LABEL = { system: "System", light: "Light", dark: "Dark" } as const;

type Props = {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  db: DbStatus;
  status?: string;
  onOpenDocs?: () => void;
  onOpenLlm?: () => void;
};

export function TopBar({ mode, onModeChange, db, status, onOpenDocs, onOpenLlm }: Props) {
  const [theme, setTheme] = useTheme();
  const dbLabel = db.busy ? "DB busy" : db.state === "owned" ? "DB" : db.state === "held" ? `DB held (PID ${db.held_by ?? "?"})` : "DB not connected";

  return (
    <header className="topbar">
      <div className="logo">
        <Logo />
        Deriva Studio
      </div>
      <div className="seg" role="group" aria-label="Mode">
        <button type="button" className={mode === "run" ? "on" : ""} aria-pressed={mode === "run"} onClick={() => onModeChange("run")}>
          Run
        </button>
        <button type="button" className={mode === "benchmark" ? "on" : ""} aria-pressed={mode === "benchmark"} onClick={() => onModeChange("benchmark")}>
          Benchmark
        </button>
      </div>
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
        <span className={`util db-${db.state}`} title={db.error ?? undefined}>
          <span className="dot" aria-hidden="true" />
          {dbLabel}
        </span>
      </div>
    </header>
  );
}
