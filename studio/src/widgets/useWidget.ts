import { useEffect, useRef, useState } from "react";

import { type Loader, mountWidget, type WidgetModel } from "./host";

/** Mount a widget module into a div once; returns the element ref, the model (when ready) and a load error. */
export function useWidget(moduleUrl: string, cssUrl: string, initialState: (el: HTMLDivElement) => Record<string, unknown>, loader?: Loader) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [model, setModel] = useState<WidgetModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const initial = useRef(initialState);

  useEffect(() => {
    let cancelled = false;
    let destroy: (() => void) | null = null;
    const el = ref.current;
    if (!el) return;
    mountWidget({ moduleUrl, cssUrl, el, state: initial.current(el), loader })
      .then((mounted) => {
        if (cancelled) {
          mounted.destroy();
          return;
        }
        destroy = mounted.destroy;
        setModel(mounted.model);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
      destroy?.();
      if (el) el.innerHTML = "";
    };
  }, [moduleUrl, cssUrl, loader]);

  return { ref, model, error };
}
