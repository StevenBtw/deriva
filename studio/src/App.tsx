import { lazy, Suspense, useEffect, useState } from "react";
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";

import { ApiError, status as fetchStatus, modelConfigs } from "./api/client";
import type { DbStatus, Engines } from "./api/types";
import { Loading, LoadBoundary } from "./components/LazyLoad";
import { Banner } from "./shell/Banner";
import { Menu } from "./shell/Menu";
import { type Mode, TopBar } from "./shell/TopBar";

// Each page is a chunk of its own, loaded when its address is first opened
const ConfigPage = lazy(() =>
  import("./pages/ConfigPage").then((m) => ({ default: m.ConfigPage })),
);
const General = lazy(() =>
  import("./pages/General").then((m) => ({ default: m.General })),
);
const IntermediateOntologyPage = lazy(() =>
  import("./pages/Ontology").then((m) => ({
    default: m.IntermediateOntologyPage,
  })),
);
const OutputOntologyPage = lazy(() =>
  import("./pages/Ontology").then((m) => ({ default: m.OutputOntologyPage })),
);
const Model = lazy(() =>
  import("./pages/Model").then((m) => ({ default: m.Model })),
);
const Repositories = lazy(() =>
  import("./pages/Repositories").then((m) => ({ default: m.Repositories })),
);
const Storage = lazy(() =>
  import("./pages/Storage").then((m) => ({ default: m.Storage })),
);
const Workspace = lazy(() =>
  import("./workspace/Workspace").then((m) => ({ default: m.Workspace })),
);

type ShellStatus = {
  db: DbStatus;
  version?: string;
  benchmark: boolean;
  noModel: boolean;
  environment?: { os?: string; python?: string };
  engines?: Engines;
  /** The studio refused the request: this browser has not opened the launch link (the guard's 401). */
  locked?: boolean;
};

// While the studio does not answer, the wait between status requests doubles from the poll interval up to this
const MAX_POLL_MS = 60000;

/** Database ownership, version, installed features and whether a model exists; polled so the banners follow changes.
 * A studio that does not answer at all (a network error, no response) is asked again later and later (the interval
 * doubled per miss, at most a minute), and only for its status; an error answer counts as an answer. A studio that
 * refuses this browser (401) is asked for its status only, at the usual interval: the launch link opened in another tab
 * lets this one in, and its first answer unlocks the page. The model list follows every answer but a 401. */
function useShellStatus(intervalMs = 10000): ShellStatus {
  const [shell, setShell] = useState<ShellStatus>({
    db: { state: "not_connected" },
    benchmark: true,
    noModel: false,
  });

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let misses = 0;
    const next = (ms: number) => {
      if (!cancelled) timer = window.setTimeout(poll, ms);
    };
    // Whether a model exists, after any answer but a refusal (an error answer included, so it cannot go stale).
    // Each request takes the next number and only the latest one's answer counts: a slow older answer cannot
    // overwrite a newer one
    let modelRequest = 0;
    const refreshModels = () => {
      const request = ++modelRequest;
      modelConfigs
        .list()
        .then(
          (models) =>
            !cancelled &&
            request === modelRequest &&
            setShell((now) => ({ ...now, noModel: models.length === 0 })),
        )
        .catch(() => {});
    };
    const poll = () => {
      fetchStatus()
        .then((s) => {
          if (cancelled) return;
          misses = 0;
          setShell((now) => ({
            ...now,
            locked: false,
            db: s.db,
            version: s.version,
            benchmark: s.features?.benchmark ?? true,
            environment: s.environment,
            engines: s.engines,
          }));
          refreshModels();
          next(intervalMs);
        })
        .catch((reason) => {
          if (cancelled) return;
          // Refused: the launch link page, and the status asked again (a 401 is a cheap answer) until this browser is let in
          if (reason instanceof ApiError && reason.status === 401) {
            misses = 0;
            setShell((now) => ({ ...now, locked: true }));
            next(intervalMs);
            return;
          }
          // An error answer (500, 503) is still an answer: the studio is there, so no notice and the usual interval,
          // and the database keeps its last known state
          if (reason instanceof ApiError) {
            misses = 0;
            setShell((now) => ({ ...now, locked: false, db: { ...now.db, unanswered: false } }));
            refreshModels();
            next(intervalMs);
            return;
          }
          // No answer (a slow or stopped studio) says nothing about the database: keep its last known state
          setShell((now) => ({
            ...now,
            db: { ...now.db, unanswered: true },
          }));
          misses += 1;
          next(Math.min(intervalMs * 2 ** misses, MAX_POLL_MS));
        });
    };
    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
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
  const { db, version, benchmark, noModel, environment, engines, locked } =
    useShellStatus();
  const { pathname } = useLocation();
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
        engines={engines}
      />
      <Banner db={db} noModel={noModel} />
      <div className="body">
        <Menu />
        <main className="content">
          <LoadBoundary resetKey={pathname}>
            <Suspense fallback={<Loading />}>
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
                    <ConfigPage
                      stepType="extraction"
                      title="Extraction config"
                    />
                  }
                />
                <Route
                  path="/ontology/output"
                  element={<OutputOntologyPage />}
                />
                <Route
                  path="/config/derivation"
                  element={
                    <ConfigPage
                      stepType="derivation"
                      title="Derivation config"
                    />
                  }
                />
                <Route path="/config/export" element={<Model />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </LoadBoundary>
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
