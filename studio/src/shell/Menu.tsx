import { type ReactNode, useState } from "react";
import { NavLink } from "react-router-dom";

import { HomeIcon, RingIcon } from "./RingIcon";

type Entry = { to: string; icon: ReactNode; label: string };

const GROUPS: { title: string | null; entries: Entry[] }[] = [
  { title: null, entries: [{ to: "/", icon: <HomeIcon />, label: "Workspace" }] },
  {
    title: "Sources",
    entries: [
      { to: "/repositories", icon: <RingIcon stage="outer" />, label: "Repositories" },
      { to: "/general", icon: "▤", label: "General & file types" },
      { to: "/storage", icon: "▦", label: "Runs & storage" },
    ],
  },
  {
    title: "Intermediate",
    entries: [
      { to: "/ontology/intermediate", icon: <RingIcon stage="second" />, label: "Intermediate ontology" },
      { to: "/config/extraction", icon: "✎", label: "Extraction config" },
    ],
  },
  {
    title: "Output",
    entries: [
      { to: "/ontology/output", icon: <RingIcon stage="inner" />, label: "Output ontology" },
      { to: "/config/derivation", icon: "✎", label: "Derivation config" },
    ],
  },
  {
    title: "Model",
    entries: [{ to: "/config/export", icon: <RingIcon stage="core" />, label: "Export config" }],
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
