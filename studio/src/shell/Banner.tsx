import type { DbStatus } from "../api/types";

type Props = { db: DbStatus; busy?: boolean };

/** Shown when the studio cannot use the databases: a CLI run holds them, or a pipeline step is running. */
export function Banner({ db, busy }: Props) {
  if (db.state === "held") {
    return (
      <div className="banner warn" role="status">
        The databases are held by another process (PID {db.held_by ?? "unknown"}), for example a CLI benchmark. The studio shows what it can and
        retries when that process ends.
      </div>
    );
  }
  if (busy) {
    return (
      <div className="banner" role="status">
        A pipeline step is running; data views refresh when it finishes.
      </div>
    );
  }
  return null;
}
