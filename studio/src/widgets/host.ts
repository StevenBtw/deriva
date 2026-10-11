/**
 * A minimal anywidget host: the model object a widget's front-end module expects
 * (get, set, on, off, save_changes, send), without Jupyter or marimo and without the
 * Python widget object. Widgets are loaded from /widgets/<name>/index.js (served by the studio).
 */

type Callback = (...args: unknown[]) => void;

export type WidgetModel = {
  get: (key: string) => unknown;
  /** One key, or several at once (every listener then sees all of them); changes are announced at once, as in Backbone. */
  set: (key: string | Record<string, unknown>, value?: unknown) => void;
  on: (event: string, callback: Callback) => void;
  off: (event?: string, callback?: Callback) => void;
  save_changes: () => void;
  send: (content: unknown, callbacks?: unknown, buffers?: unknown) => void;
};

export function createModel(initial: Record<string, unknown>, onSend?: (content: unknown) => void): WidgetModel {
  const state: Record<string, unknown> = { ...initial };
  const listeners = new Map<string, Set<Callback>>();

  const emit = (event: string, ...args: unknown[]) => {
    for (const callback of [...(listeners.get(event) ?? [])]) callback(...args);
  };

  const model: WidgetModel = {
    get: (key) => state[key],
    set: (key, value) => {
      const changes = typeof key === "string" ? { [key]: value } : key;
      // A value that stays the same is no change (a widget that sets it again in its listener does not loop)
      const changed = Object.keys(changes).filter((name) => !Object.is(state[name], changes[name]));
      Object.assign(state, changes);
      for (const name of changed) emit(`change:${name}`, model, state[name]);
      if (changed.length) emit("change", model);
    },
    on: (event, callback) => {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(callback);
    },
    off: (event, callback) => {
      if (event === undefined) listeners.clear();
      else if (callback === undefined) listeners.delete(event);
      else listeners.get(event)?.delete(callback);
    },
    // No kernel to sync with: set has announced every change already
    save_changes: () => {},
    send: (content) => onSend?.(content),
  };
  return model;
}

type WidgetModule = {
  default:
    | { initialize?: (ctx: { model: WidgetModel }) => unknown; render: (ctx: { model: WidgetModel; el: HTMLElement }) => unknown }
    | (() => unknown);
};

export type Loader = (url: string) => Promise<unknown>;

export const defaultLoader: Loader = (url) => import(/* @vite-ignore */ url);

const loadedStyles = new Set<string>();

function addStylesheet(href: string): void {
  if (loadedStyles.has(href) || document.head.querySelector(`link[href="${href}"]`)) {
    loadedStyles.add(href);
    return;
  }
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.appendChild(link);
  loadedStyles.add(href);
}

export async function mountWidget(options: {
  moduleUrl: string;
  cssUrl?: string;
  el: HTMLElement;
  state: Record<string, unknown>;
  loader?: Loader;
  onSend?: (content: unknown) => void;
}): Promise<{ model: WidgetModel; destroy: () => void }> {
  if (options.cssUrl) addStylesheet(options.cssUrl);
  const module = (await (options.loader ?? defaultLoader)(options.moduleUrl)) as WidgetModule;
  const widget = (typeof module.default === "function" ? await module.default() : module.default) as Exclude<WidgetModule["default"], () => unknown>;
  const model = createModel(options.state, options.onSend);
  const initCleanup = await widget.initialize?.({ model });
  const renderCleanup = await widget.render({ model, el: options.el });
  return {
    model,
    destroy: () => {
      if (typeof renderCleanup === "function") renderCleanup();
      if (typeof initCleanup === "function") initCleanup();
      model.off();
    },
  };
}
