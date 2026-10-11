import { useEffect, useRef, useState } from "react";

import { type Loader, mountWidget, type WidgetModel } from "./host";

type Result = { moduleUrl: string; cssUrl: string; loader?: Loader; model?: WidgetModel; error?: string };

/** Mount a widget module into a div once; returns the element ref, the model (when ready) and a load error. */
export function useWidget(moduleUrl: string, cssUrl: string, initialState: (el: HTMLDivElement) => Record<string, unknown>, loader?: Loader) {
  const ref = useRef<HTMLDivElement | null>(null);
  // A result keeps the inputs it was mounted from: after a reload no destroyed model or old error is handed out
  const [result, setResult] = useState<Result | null>(null);
  const initial = useRef(initialState);

  useEffect(() => {
    let cancelled = false;
    let destroy: (() => void) | null = null;
    const el = ref.current;
    if (!el) return;
    // Each attempt renders into an element of its own: one that finishes after its replacement writes into a detached element
    const host = document.createElement("div");
    host.style.height = "100%";
    el.appendChild(host);
    mountWidget({ moduleUrl, cssUrl, el: host, state: initial.current(el), loader })
      .then((mounted) => {
        if (cancelled) {
          mounted.destroy();
          return;
        }
        destroy = mounted.destroy;
        setResult({ moduleUrl, cssUrl, loader, model: mounted.model });
      })
      .catch((reason: unknown) => {
        if (!cancelled) setResult({ moduleUrl, cssUrl, loader, error: reason instanceof Error ? reason.message : String(reason) });
      });
    return () => {
      cancelled = true;
      destroy?.();
      host.remove();
    };
  }, [moduleUrl, cssUrl, loader]);

  const current = result && result.moduleUrl === moduleUrl && result.cssUrl === cssUrl && result.loader === loader ? result : null;
  return { ref, model: current?.model ?? null, error: current?.error ?? null };
}
