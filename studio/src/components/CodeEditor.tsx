import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { basicSetup } from "codemirror";
import { useEffect, useRef } from "react";

type Props = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  language?: "markdown" | "json";
  readOnly?: boolean;
};

/** A controlled CodeMirror 6 editor (prompt text as markdown, examples and params as JSON). */
export function CodeEditor({ label, value, onChange, language = "markdown", readOnly = false }: Props) {
  const host = useRef<HTMLDivElement | null>(null);
  const view = useRef<EditorView | null>(null);
  const change = useRef(onChange);

  useEffect(() => {
    change.current = onChange;
  }, [onChange]);

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          language === "json" ? json() : markdown(),
          EditorView.lineWrapping,
          EditorState.readOnly.of(readOnly),
          EditorView.contentAttributes.of({ "aria-label": label }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) change.current(update.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
    // The editor is created once per language/readOnly; value changes are applied below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, readOnly, label]);

  useEffect(() => {
    const editor = view.current;
    if (editor && editor.state.doc.toString() !== value) {
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
    }
  }, [value]);

  return <div className="codebox" ref={host} />;
}
