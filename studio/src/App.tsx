import { useEffect, useState } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";

import { ApiError, status as fetchStatus, modelConfigs } from "./api/client";
import type { DbStatus } from "./api/types";
import { ConfigPage } from "./pages/ConfigPage";
import { General } from "./pages/General";
import { IntermediateOntologyPage, OutputOntologyPage } from "./pages/Ontology";
import { Repositories } from "./pages/Repositories";
import { Storage } from "./pages/Storage";
import { Banner } from "./shell/Banner";
import { Menu } from "./shell/Menu";
import { type Mode, TopBar } from "./shell/TopBar";
import { Workspace } from "./workspace/Workspace";

type ShellStatus = {
  db: DbStatus;
  version?: string;
  benchmark: boolean;
  noModel: boolean;
  environment?: { os?: string; python?: string };
  /** The studio refused the request: this browser has not opened the launch link (the guard's 401). */
  locked?: boolean;
};

/** Database ownership, version, installed features and whether a model exists; polled so the banners follow changes. */
function useShellStatus(intervalMs = 10000): ShellStatus {
  const [shell, setShell] = useState<ShellStatus>({
    db: { state: "not_connected" },
    benchmark: true,
    noModel: false,
  });

  useEffect(() => {
    let cancelled = false;
    const poll = () => {
      fetchStatus()
        .then(
          (s) =>
            !cancelled &&
            setShell((now) => ({
              ...now,
              locked: false,
              db: s.db,
              version: s.version,
              benchmark: s.features?.benchmark ?? true,
              environment: s.environment,
            })),
        )
        .catch((reason) => {
          if (cancelled) return;
          if (reason instanceof ApiError && reason.status === 401)
            setShell((now) => ({ ...now, locked: true }));
          // No answer (a slow or stopped studio) says nothing about the database: keep its last known state
          else
            setShell((now) => ({
              ...now,
              db: { ...now.db, unanswered: true },
            }));
        });
      modelConfigs
        .list()
        .then(
          (models) =>
            !cancelled &&
            setShell((now) => ({ ...now, noModel: models.length === 0 })),
        )
        .catch(() => {});
    };
    poll();
    const timer = window.setInterval(poll, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [intervalMs]);

  return shell;
}

/** A browser that has not opened this launch's link: the studio answers it nothing else. */
function Locked() {
  return (
    <section className="page">
      <div className="pagehead">
        <h2>Open the studio from its launch link</h2>
      </div>
      <div className="pad">
        <p>
          Each start of <code>deriva</code> prints a link with a fresh token in
          its terminal. Open that link: the studio then works in this browser
          until it stops.
        </p>
      </div>
    </section>
  );
}

/** An address the studio has no page for (an old bookmark, a typo). */
function NotFound() {
  return (
    <section className="page">
      <div className="pagehead">
        <h2>Page not found</h2>
      </div>
      <div className="pad">
        <Link to="/">Go to the workspace</Link>
      </div>
    </section>
  );
}

export function Shell() {
  const [chosenMode, setMode] = useState<Mode>("run");
  const { db, version, benchmark, noModel, environment, locked } =
    useShellStatus();
  // Without benchmarking installed there is only Run mode
  const mode = benchmark ? chosenMode : "run";
  if (locked) return <Locked />;

  return (
    <div className="app">
      <TopBar
        mode={mode}
        onModeChange={setMode}
        db={db}
        version={version}
        benchmark={benchmark}
        environment={environment}
      />
      <Banner db={db} noModel={noModel} />
      <div className="body">
        <Menu />
        <main className="content">
          <Routes>
            <Route path="/" element={<Workspace mode={mode} />} />
            <Route path="/repositories" element={<Repositories />} />
            <Route
              path="/general"
              element={<General benchmark={benchmark} />}
            />
            <Route path="/storage" element={<Storage />} />
            <Route
              path="/ontology/intermediate"
              element={<IntermediateOntologyPage />}
            />
            <Route
              path="/config/extraction"
              element={
                <ConfigPage stepType="extraction" title="Extraction config" />
              }
            />
            <Route path="/ontology/output" element={<OutputOntologyPage />} />
            <Route
              path="/config/derivation"
              element={
                <ConfigPage stepType="derivation" title="Derivation config" />
              }
            />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  );
}
