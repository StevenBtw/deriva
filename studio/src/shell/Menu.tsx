import { useState } from "react";
import { NavLink } from "react-router-dom";

type Entry = { to: string; icon: string; label: string };

const GROUPS: { title: string | null; entries: Entry[] }[] = [
  { title: null, entries: [{ to: "/", icon: "◉", label: "Workspace" }] },
  {
    title: "Sources",
    entries: [
      { to: "/repositories", icon: "▣", label: "Repositories" },
      { to: "/general", icon: "▤", label: "General & file types" },
    ],
  },
  {
    title: "Intermediate",
    entries: [
      { to: "/ontology/intermediate", icon: "◇", label: "Intermediate ontology" },
      { to: "/config/extraction", icon: "✎", label: "Extraction config" },
    ],
  },
  {
    title: "Output",
    entries: [
      { to: "/ontology/output", icon: "◆", label: "Output ontology" },
      { to: "/config/derivation", icon: "⇄", label: "Derivation config" },
    ],
  },
];

export function Menu() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <nav className={`menu${collapsed ? " collapsed" : ""}`} aria-label="Studio">
      {GROUPS.map((group, i) => (
        <div key={group.title ?? i} className="menu-section">
          {group.title && <div className="menu-group">{group.title}</div>}
          {group.entries.map((entry) => (
            <NavLink key={entry.to} to={entry.to} end={entry.to === "/"} className="menu-link" title={entry.label}>
              <span className="menu-icon" aria-hidden="true">
                {entry.icon}
              </span>
              <span className="menu-label">{entry.label}</span>
            </NavLink>
          ))}
        </div>
      ))}
      <div className="menu-spacer" />
      <button
        type="button"
        className="menu-link menu-toggle"
        aria-expanded={!collapsed}
        aria-label={collapsed ? "Expand menu" : "Collapse menu"}
        onClick={() => setCollapsed((c) => !c)}
      >
        <span className="menu-icon" aria-hidden="true">
          {collapsed ? "»" : "«"}
        </span>
        <span className="menu-label">Collapse</span>
      </button>
    </nav>
  );
}
