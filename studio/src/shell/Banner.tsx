import { Link } from "react-router-dom";

import type { DbStatus } from "../api/types";

type Props = { db: DbStatus; busy?: boolean; noModel?: boolean };

/** Shown when the studio cannot use the databases (a CLI run holds them, a step is running) or has no LLM model yet. */
export function Banner({ db, busy, noModel }: Props) {
  if (db.state === "held") {
    return (
      <div className="banner warn" role="status">
        The databases are held by another process (PID {db.held_by ?? "unknown"}), for example a CLI benchmark. The studio shows what it can and
        retries when that process ends.
      </div>
    );
  }
  // The status poll reports a step holding the session as db.busy
  if (busy ?? db.busy) {
    return (
      <div className="banner" role="status">
        A pipeline step is running; data views refresh when it finishes.
      </div>
    );
  }
  if (noModel) {
    return (
      <div className="banner" role="status">
        No LLM model is configured. Structural steps run without one; the LLM steps need a model. <Link to="/general">Add a model in General</Link>
      </div>
    );
  }
  return null;
}
