import { useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { status as fetchStatus } from "./api/client";
import type { DbStatus } from "./api/types";
import { ConfigPage } from "./pages/ConfigPage";
import { General } from "./pages/General";
import { IntermediateOntologyPage, OutputOntologyPage } from "./pages/Ontology";
import { Repositories } from "./pages/Repositories";
import { Banner } from "./shell/Banner";
import { Menu } from "./shell/Menu";
import { type Mode, TopBar } from "./shell/TopBar";
import { Workspace } from "./workspace/Workspace";

/** Database ownership, polled so the banner clears when a CLI run releases the files. */
function useDbStatus(intervalMs = 10000): DbStatus {
  const [db, setDb] = useState<DbStatus>({ state: "not_connected" });

  useEffect(() => {
    let cancelled = false;
    const poll = () =>
      fetchStatus()
        .then((s) => !cancelled && setDb(s.db))
        .catch(() => !cancelled && setDb({ state: "not_connected" }));
    poll();
    const timer = window.setInterval(poll, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [intervalMs]);

  return db;
}

export function Shell() {
  const [mode, setMode] = useState<Mode>("run");
  const db = useDbStatus();

  return (
    <div className="app">
      <TopBar mode={mode} onModeChange={setMode} db={db} />
      <Banner db={db} />
      <div className="body">
        <Menu />
        <main className="content">
          <Routes>
            <Route path="/" element={<Workspace mode={mode} />} />
            <Route path="/repositories" element={<Repositories />} />
            <Route path="/general" element={<General />} />
            <Route path="/ontology/intermediate" element={<IntermediateOntologyPage />} />
            <Route path="/config/extraction" element={<ConfigPage stepType="extraction" title="Extraction config" />} />
            <Route path="/ontology/output" element={<OutputOntologyPage />} />
            <Route path="/config/derivation" element={<ConfigPage stepType="derivation" title="Derivation config" />} />
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
