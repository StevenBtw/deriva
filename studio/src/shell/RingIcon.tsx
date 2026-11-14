import { INNER, OUTER } from "./Logo";

// The middle contour of the full mark (assets/brand), between the logo's outer and inner rings
const SECOND =
  "M51.2 32 C51.2 32.6 51.1 33.3 51 33.9 C50.9 34.5 50.7 35.1 50.5 35.7 C50.3 36.3 50 36.8 49.8 37.4 C49.6 38 49.3 38.5 49.1 39.1 C48.8 39.6 48.5 40.1 48.2 40.7 C47.9 41.2 47.6 41.7 47.2 42.2 C46.9 42.7 46.5 43.1 46 43.5 C45.6 43.9 45.1 44.3 44.6 44.6 C44.1 45 43.6 45.2 43.1 45.5 C42.5 45.7 42 45.9 41.4 46.1 C40.9 46.3 40.4 46.5 39.9 46.7 C39.3 46.9 38.8 47.1 38.4 47.3 C37.9 47.6 37.4 47.8 36.9 48.1 C36.4 48.3 35.9 48.6 35.4 48.9 C34.8 49.1 34.3 49.4 33.7 49.5 C33.2 49.7 32.6 49.8 32 49.9 C31.4 49.9 30.8 49.9 30.3 49.7 C29.7 49.6 29.1 49.4 28.6 49.2 C28.1 48.9 27.6 48.6 27.1 48.3 C26.6 47.9 26.1 47.6 25.7 47.2 C25.2 46.9 24.8 46.5 24.4 46.2 C23.9 46 23.5 45.7 23 45.4 C22.6 45.2 22.1 45 21.6 44.7 C21.1 44.5 20.5 44.3 20 44 C19.5 43.7 19 43.4 18.5 43 C18.1 42.7 17.6 42.3 17.3 41.8 C16.9 41.4 16.6 40.9 16.4 40.3 C16.1 39.8 16 39.3 15.8 38.7 C15.7 38.1 15.6 37.6 15.6 37 C15.5 36.4 15.4 35.9 15.4 35.3 C15.3 34.8 15.2 34.2 15.2 33.7 C15.1 33.1 15 32.6 14.9 32 C14.7 31.4 14.6 30.9 14.5 30.3 C14.4 29.7 14.3 29.1 14.3 28.5 C14.3 27.9 14.3 27.3 14.4 26.7 C14.5 26.1 14.6 25.4 14.8 24.9 C15 24.3 15.2 23.7 15.5 23.2 C15.8 22.6 16.1 22.1 16.5 21.6 C16.8 21.1 17.2 20.6 17.6 20.2 C17.9 19.7 18.3 19.2 18.7 18.7 C19.2 18.3 19.6 17.8 20 17.4 C20.5 17 20.9 16.6 21.5 16.2 C22 15.9 22.5 15.6 23.1 15.3 C23.7 15.1 24.3 14.9 24.9 14.8 C25.5 14.8 26.2 14.8 26.8 14.8 C27.4 14.9 28 15 28.7 15.2 C29.3 15.3 29.8 15.5 30.4 15.7 C31 15.9 31.5 16.1 32 16.2 C32.5 16.4 33 16.5 33.5 16.5 C34 16.6 34.5 16.6 35.1 16.7 C35.6 16.7 36.1 16.7 36.6 16.7 C37.2 16.7 37.7 16.7 38.3 16.8 C38.8 16.9 39.4 17 39.9 17.2 C40.4 17.4 40.9 17.7 41.4 18 C41.8 18.3 42.2 18.7 42.6 19.1 C43 19.5 43.3 19.9 43.6 20.4 C44 20.8 44.3 21.2 44.6 21.7 C44.9 22.1 45.2 22.5 45.6 22.9 C45.9 23.3 46.3 23.7 46.7 24.1 C47.1 24.5 47.6 24.9 48 25.4 C48.4 25.8 48.9 26.3 49.3 26.8 C49.7 27.3 50 27.8 50.3 28.4 C50.6 28.9 50.9 29.5 51 30.1 C51.1 30.7 51.2 31.4 51.2 32 Z";

export type RingStage = "outer" | "second" | "inner" | "core";

/**
 * A menu icon from the Deriva mark: all three rings and the core, faint, with the ring of the entry's pipeline stage at
 * full strength (outer: the repository, second: the intermediate graph, inner: the output graph, core: the model), the
 * same mapping as the steps on deriva.dev. On the active page the stage's ring takes the accent colour.
 */
export function RingIcon({ stage }: { stage: RingStage }) {
  const on = (s: RingStage) => (s === stage ? "ring ring-on" : "ring");
  return (
    <svg className="ring-icon" data-stage={stage} width="16" height="16" viewBox="7 7 50 50" aria-hidden="true" focusable="false">
      <path className={on("outer")} d={OUTER} />
      <path className={on("second")} d={SECOND} />
      <path className={on("inner")} d={INNER} />
      <circle className={stage === "core" ? "core core-on" : "core"} cx="32" cy="32" r={stage === "core" ? 8 : 5} />
    </svg>
  );
}

/** The start page's icon: a house in the ring icons' size and line weight, so the menu reads as one set. */
export function HomeIcon() {
  return (
    <svg className="home-icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M2.5 7.2 8 2.6l5.5 4.6" />
      <path d="M4 6.2V13h3V9.6h2V13h3V6.2" />
    </svg>
  );
}
