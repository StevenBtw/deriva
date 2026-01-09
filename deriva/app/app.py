import marimo

__generated_with = "0.19.0"
app = marimo.App(width="columns", app_title="Deriva")


@app.cell(column=0, hide_code=True)
def _(mo):
    mo.md(r"""
    # Deriva
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Run Deriva
    """)
    return


@app.cell
def _(mo):
    run_deriva_btn = mo.ui.run_button(label="Run Deriva", kind="success")
    extraction_btn = mo.ui.run_button(label="Run Extraction")
    derivation_btn = mo.ui.run_button(label="Run Derivation")

    mo.vstack(
        [
            run_deriva_btn,
            mo.md("---"),
            mo.md("### Individual Steps"),
            mo.hstack([extraction_btn, derivation_btn]),
        ]
    )
    return derivation_btn, extraction_btn, run_deriva_btn


@app.cell
def _(MarimoProgressReporter, derivation_btn, extraction_btn, mo, run_deriva_btn, session):
    # Run pipeline based on button clicks
    _result = None
    _kind = "neutral"
    _progress = None
    _summary = None

    if run_deriva_btn.value:
        _progress = MarimoProgressReporter()
        with mo.status.spinner("Running pipeline..."):
            _result = session.run_pipeline(verbose=False, progress=_progress)
        _summary = _progress.get_summary()
        _kind = "success" if _result.get("success") else "danger"
        _stats = _result.get("stats", {})
        _msg = f"""**Pipeline Complete** ({_summary['elapsed_seconds']:.1f}s)
- Extraction: {_stats.get("extraction", {}).get("nodes_created", 0)} nodes
- Derivation: {_stats.get("derivation", {}).get("elements_created", 0)} elements
- Steps completed: {_summary['steps_completed']}
- Errors: {len(_result.get("errors", []))}"""
    elif extraction_btn.value:
        _progress = MarimoProgressReporter()
        with mo.status.spinner("Running extraction..."):
            _result = session.run_extraction(verbose=False, progress=_progress)
        _summary = _progress.get_summary()
        _kind = "success" if _result.get("success") else "danger"
        _stats = _result.get("stats", {})
        _msg = f"""**Extraction Complete** ({_summary['elapsed_seconds']:.1f}s)
- Repos: {_stats.get("repos_processed", 0)}
- Nodes: {_stats.get("nodes_created", 0)}
- Edges: {_stats.get("edges_created", 0)}
- Steps completed: {_summary['steps_completed']}"""
    elif derivation_btn.value:
        _progress = MarimoProgressReporter()
        with mo.status.spinner("Running derivation..."):
            _result = session.run_derivation(verbose=False, progress=_progress)
        _summary = _progress.get_summary()
        _kind = "success" if _result.get("success") else "danger"
        _stats = _result.get("stats", {})
        _msg = f"""**Derivation Complete** ({_summary['elapsed_seconds']:.1f}s)
- Elements: {_stats.get("elements_created", 0)}
- Relationships: {_stats.get("relationships_created", 0)}
- Steps completed: {_summary['steps_completed']}
- Issues: {_stats.get("issues_found", 0)}"""
    else:
        _msg = "Click a button to run pipeline steps"

    if _result and _result.get("errors"):
        _msg += "\n\n**Errors:**\n" + "\n".join(f"- {e}" for e in _result["errors"][:5])

    # Show step details if available
    if _summary and _summary.get("step_details"):
        _steps = _summary["step_details"]
        if _steps:
            _msg += "\n\n**Steps:**\n" + "\n".join(
                f"- {s['name']}: {s['message']}" for s in _steps if s["message"]
            )

    mo.callout(mo.md(_msg), kind=_kind)
    return


@app.cell(column=1, hide_code=True)
def _(mo):
    mo.md(r"""
    # Configuration
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Run Management
    """)
    return


@app.cell
def _(mo):
    run_desc_input = mo.ui.text(placeholder="Run description", label="Description")
    create_run_btn = mo.ui.run_button(label="Create Run")
    mo.hstack([run_desc_input, create_run_btn])
    return create_run_btn, run_desc_input


@app.cell
def _(create_run_btn, mo, run_desc_input, session):
    if create_run_btn.value and run_desc_input.value:
        _result = session.create_run(run_desc_input.value)
        if _result.get("success"):
            mo.callout(mo.md(f"Created run: {_result['description']}"), kind="success")
        else:
            mo.callout(mo.md(f"Error: {_result.get('error')}"), kind="danger")
    return


@app.cell
def _(mo, session):
    _runs = session.get_runs(limit=5)
    _active = session.get_active_run()

    _rows = [
        {
            "ID": r["run_id"],
            "Description": r["description"],
            "Active": "Yes" if r["is_active"] else "",
        }
        for r in _runs
    ]

    mo.vstack(
        [
            mo.md(f"**Active Run:** {_active['description'] if _active else 'None'}"),
            mo.ui.table(_rows, label="Recent Runs") if _rows else mo.md("_No runs yet_"),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Repositories
    """)
    return


@app.cell
def _(get_repos_refresh, mo, session):
    # Depend on refresh state to trigger re-render after clone/delete
    _ = get_repos_refresh()
    _repos = session.get_repositories(detailed=True)
    _rows = [
        {
            "Name": r["name"],
            "Branch": r.get("branch", "") or "",
            "URL": r["url"][:50] + "..." if len(r.get("url", "")) > 50 else r.get("url", ""),
        }
        for r in _repos
    ]

    repos_table = mo.ui.table(_rows, label="Repositories", selection="multi") if _rows else None
    repos_table if repos_table else mo.md("_No repositories cloned_")
    return (repos_table,)


@app.cell
def _(mo):
    repo_url_input = mo.ui.text(placeholder="https://github.com/...", label="Repository URL")
    repo_name_input = mo.ui.text(placeholder="(optional)", label="Name")
    clone_btn = mo.ui.run_button(label="Clone")

    mo.hstack([repo_url_input, repo_name_input, clone_btn])
    return clone_btn, repo_name_input, repo_url_input


@app.cell
def _(clone_btn, get_repos_refresh, mo, repo_name_input, repo_url_input, session, set_repos_refresh):
    if clone_btn.value and repo_url_input.value:
        _result = session.clone_repository(
            url=repo_url_input.value,
            name=repo_name_input.value or None,
        )
        if _result.get("success"):
            set_repos_refresh(get_repos_refresh() + 1)
            mo.callout(mo.md(f"Cloned **{_result['name']}**"), kind="success")
        else:
            mo.callout(mo.md(f"Error: {_result.get('error')}"), kind="danger")
    return


@app.cell
def _(mo, repos_table):
    _selected = repos_table.value if repos_table else []
    _count = len(_selected)
    _has_selection = _count > 0
    _names = ", ".join(r["Name"] for r in _selected) if _has_selection else ""
    delete_repo_btn = mo.ui.run_button(label=f"Delete ({_count})" if _has_selection else "Delete Selected", kind="danger", disabled=not _has_selection)
    mo.hstack([delete_repo_btn, mo.md(f"Selected: **{_names}**" if _has_selection else "_Select repositories to delete_")])
    return (delete_repo_btn,)


@app.cell
def _(delete_repo_btn, get_repos_refresh, mo, repos_table, session, set_repos_refresh):
    if delete_repo_btn.value and repos_table and repos_table.value:
        _selected = repos_table.value
        _deleted = []
        _errors = []
        for repo in _selected:
            _result = session.delete_repository(repo["Name"], force=True)
            if _result.get("success"):
                _deleted.append(repo["Name"])
            else:
                _errors.append(f"{repo['Name']}: {_result.get('error')}")
        # Trigger refresh
        set_repos_refresh(get_repos_refresh() + 1)
        if _deleted:
            mo.callout(mo.md(f"Deleted: **{', '.join(_deleted)}**"), kind="success")
        if _errors:
            mo.callout(mo.md(f"Errors:\n" + "\n".join(f"- {e}" for e in _errors)), kind="danger")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Neo4j
    """)
    return


@app.cell
def _(mo, session):
    # Try to get container status, fall back to checking database connectivity
    _docker_error = None
    _db_error = None
    _db_connected = False
    try:
        _status = session.get_neo4j_status()
        _running = _status.get("running", False)
    except Exception as e:
        _docker_error = str(e)
        _running = False
        _status = {}

    # If Docker check failed, try to verify Neo4j connectivity directly
    if _docker_error:
        try:
            _stats = session.get_graph_stats()
            _db_connected = True
            _running = True  # Database is accessible
        except Exception as e:
            _db_connected = False
            _db_error = str(e)

    if _docker_error and _db_connected:
        _kind = "success"
        _text = "**Status:** Connected (Docker status unavailable)\n- Database is accessible"
    elif _running:
        _kind = "success"
        _text = f"**Status:** Running\n- Port: {_status.get('port', 7687)}"
    else:
        _kind = "warn"
        _text = "**Status:** Not connected"
        if _db_error:
            _text += f"\n- DB error: {_db_error[:150]}"

    start_neo4j_btn = mo.ui.run_button(label="Start", disabled=_running)
    stop_neo4j_btn = mo.ui.run_button(label="Stop", disabled=not _running)

    mo.vstack(
        [
            mo.callout(mo.md(_text), kind=_kind),
            mo.hstack([start_neo4j_btn, stop_neo4j_btn]),
        ]
    )
    return start_neo4j_btn, stop_neo4j_btn


@app.cell
def _(mo, session, start_neo4j_btn, stop_neo4j_btn):
    if start_neo4j_btn.value:
        try:
            _result = session.start_neo4j()
            if _result.get("success", True):
                mo.callout(mo.md("Neo4j starting..."), kind="info")
            else:
                mo.callout(mo.md(f"Error: {_result.get('error', 'Unknown')}"), kind="danger")
        except Exception as e:
            mo.callout(mo.md(f"Docker error: {str(e)[:100]}"), kind="danger")
    elif stop_neo4j_btn.value:
        try:
            _result = session.stop_neo4j()
            if _result.get("success", True):
                mo.callout(mo.md("Neo4j stopping..."), kind="info")
            else:
                mo.callout(mo.md(f"Error: {_result.get('error', 'Unknown')}"), kind="danger")
        except Exception as e:
            mo.callout(mo.md(f"Docker error: {str(e)[:100]}"), kind="danger")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Graph Statistics
    """)
    return


@app.cell
def _(mo, session):
    _stats = session.get_graph_stats()
    _total = _stats.get("total_nodes", 0)
    _by_type = _stats.get("by_type", {})

    _rows = [{"Type": k, "Count": v} for k, v in _by_type.items() if v > 0]

    mo.vstack(
        [
            mo.md(f"**Total Nodes:** {_total}"),
            mo.ui.table(_rows, label="By Type") if _rows else mo.md("_Graph empty_"),
        ]
    )
    return


@app.cell
def _(mo):
    clear_graph_btn = mo.ui.run_button(label="Clear Graph", kind="danger")
    clear_graph_btn
    return (clear_graph_btn,)


@app.cell
def _(clear_graph_btn, mo, session):
    if clear_graph_btn.value:
        _result = session.clear_graph()
        _kind = "success" if _result.get("success") else "danger"
        mo.callout(mo.md(_result.get("message", _result.get("error", "Unknown"))), kind=_kind)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## ArchiMate Model
    """)
    return


@app.cell
def _(mo, session):
    _stats = session.get_archimate_stats()
    _total = _stats.get("total_elements", 0)
    _rels = _stats.get("total_relationships", 0)
    _by_type = _stats.get("by_type", {})

    _rows = [{"Type": k, "Count": v} for k, v in _by_type.items() if v > 0]

    mo.vstack(
        [
            mo.md(f"**Elements:** {_total} | **Relationships:** {_rels}"),
            mo.ui.table(_rows, label="By Type") if _rows else mo.md("_Model empty_"),
        ]
    )
    return


@app.cell
def _(mo):
    export_path_input = mo.ui.text(value="workspace/output/model.archimate", label="Export Path")
    export_btn = mo.ui.run_button(label="Export Model")

    mo.hstack([export_path_input, export_btn])
    return export_btn, export_path_input


@app.cell
def _(export_btn, export_path_input, mo, session):
    if export_btn.value:
        _result = session.export_model(output_path=export_path_input.value)
        if _result.get("success"):
            mo.callout(
                mo.md(f"Exported {_result['elements_exported']} elements to `{_result['output_path']}`"),
                kind="success",
            )
        else:
            mo.callout(mo.md(f"Error: {_result.get('error')}"), kind="danger")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## LLM
    """)
    return


@app.cell
def _(mo, session):
    _status = session.get_llm_status()
    if _status.get("configured"):
        _text = f"**Provider:** {_status.get('provider')}\n**Model:** {_status.get('model')}"
        mo.callout(mo.md(_text), kind="success")
    else:
        mo.callout(mo.md("LLM not configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."), kind="warn")
    return


@app.cell(column=2, hide_code=True)
def _(mo):
    mo.md(r"""
    # Extraction Settings
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## File Types
    """)
    return


@app.cell
def _(mo, session):
    _file_types = session.get_file_types()
    _stats = session.get_file_type_stats()

    mo.md(f"**Types:** {_stats['types']} | **Subtypes:** {_stats['subtypes']} | **Total:** {_stats['total']}")
    return


@app.cell
def _(mo, session):
    _file_types = session.get_file_types()
    _rows = [{"Extension": ft["extension"], "Type": ft["file_type"], "Subtype": ft.get("subtype", "") or ""} for ft in _file_types[:50]]

    mo.ui.table(_rows, label="File Type Registry", selection=None)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Extraction Steps
    """)
    return


@app.cell
def _(mo, session):
    _configs = session.get_extraction_configs()
    _rows = [
        {
            "Seq": c["sequence"],
            "Node Type": c["node_type"],
            "Enabled": "Yes" if c["enabled"] else "",
            "Input": (c["input_sources"] or "")[:30],
        }
        for c in sorted(_configs, key=lambda x: x["sequence"])
    ]

    mo.ui.table(_rows, label="Extraction Configuration")
    return


@app.cell
def _(mo, session):
    # Editable form for extraction config
    _configs = session.get_extraction_configs()
    _options = [c["node_type"] for c in _configs]

    ext_node_type_select = mo.ui.dropdown(options=_options, label="Node Type", value=_options[0] if _options else None)
    ext_node_type_select
    return (ext_node_type_select,)


@app.cell
def _(ext_node_type_select, mo, session):
    if ext_node_type_select.value:
        _configs = session.get_extraction_configs()
        _cfg = next((c for c in _configs if c["node_type"] == ext_node_type_select.value), None)

        if _cfg:
            ext_enabled = mo.ui.checkbox(label="Enabled", value=_cfg["enabled"])
            ext_instruction = mo.ui.text_area(value=_cfg["instruction"] or "", label="Instruction", rows=3)
            ext_input_sources = mo.ui.text(value=_cfg["input_sources"] or "", label="Input Sources")
            ext_save_btn = mo.ui.run_button(label="Save")

            mo.vstack([ext_enabled, ext_instruction, ext_input_sources, ext_save_btn])
    return ext_enabled, ext_input_sources, ext_instruction, ext_save_btn


@app.cell
def _(
    ext_enabled,
    ext_input_sources,
    ext_instruction,
    ext_node_type_select,
    ext_save_btn,
    mo,
    session,
):
    if ext_save_btn.value and ext_node_type_select.value:
        _ok = session.update_extraction_config(
            ext_node_type_select.value,
            enabled=ext_enabled.value,
            instruction=ext_instruction.value,
            input_sources=ext_input_sources.value,
        )
        mo.callout(mo.md("Saved" if _ok else "Failed"), kind="success" if _ok else "danger")
    return


@app.cell(column=3, hide_code=True)
def _(mo):
    mo.md(r"""
    # Derivation Settings
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Derivation Steps
    """)
    return


@app.cell
def _(mo, session):
    _configs = session.get_derivation_configs()
    _rows = [
        {
            "Seq": c["sequence"],
            "Phase": c.get("phase", "generate"),
            "Step": c["element_type"],
            "Enabled": "Yes" if c["enabled"] else "",
        }
        for c in sorted(_configs, key=lambda x: x["sequence"])
    ]

    mo.ui.table(_rows, label="Derivation Configuration")
    return


@app.cell
def _(mo, session):
    _configs = session.get_derivation_configs()
    _options = [c["element_type"] for c in _configs]

    der_element_type_select = mo.ui.dropdown(options=_options, label="Element Type", value=_options[0] if _options else None)
    der_element_type_select
    return (der_element_type_select,)


@app.cell
def _(der_element_type_select, mo, session):
    if der_element_type_select.value:
        _configs = session.get_derivation_configs()
        _cfg = next((c for c in _configs if c["element_type"] == der_element_type_select.value), None)

        if _cfg:
            der_enabled = mo.ui.checkbox(label="Enabled", value=_cfg["enabled"])
            der_instruction = mo.ui.text_area(value=_cfg["instruction"] or "", label="Instruction", rows=3)
            der_query = mo.ui.text_area(value=_cfg["input_graph_query"] or "", label="Graph Query", rows=2)
            der_save_btn = mo.ui.run_button(label="Save")

            mo.vstack([der_enabled, der_instruction, der_query, der_save_btn])
    return der_enabled, der_instruction, der_query, der_save_btn


@app.cell
def _(
    der_element_type_select,
    der_enabled,
    der_instruction,
    der_query,
    der_save_btn,
    mo,
    session,
):
    if der_save_btn.value and der_element_type_select.value:
        _ok = session.update_derivation_config(
            der_element_type_select.value,
            enabled=der_enabled.value,
            instruction=der_instruction.value,
            input_graph_query=der_query.value,
        )
        mo.callout(mo.md("Saved" if _ok else "Failed"), kind="success" if _ok else "danger")
    return


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(mo):
    # State for triggering refresh of repository list
    get_repos_refresh, set_repos_refresh = mo.state(0)
    return get_repos_refresh, set_repos_refresh


@app.cell
def _():
    from deriva.app.progress import MarimoProgressReporter
    from deriva.services.session import PipelineSession

    session = PipelineSession(auto_connect=True)
    return MarimoProgressReporter, session


@app.cell
def _(mo):
    # Sidebar navigation
    mo.sidebar(
        [
            mo.md("# Deriva"),
            mo.nav_menu(
                {
                    "#run-deriva": f"{mo.icon('lucide:play')} Run Deriva",
                    "#configuration": f"{mo.icon('lucide:settings')} Configuration",
                    "#extraction-settings": f"{mo.icon('lucide:filter')} Extraction Settings",
                    "#derivation-settings": f"{mo.icon('lucide:git-branch')} Derivation Settings",
                    "Contact": {
                        "https://github.com/StevenBtw/Deriva": f"{mo.icon('lucide:github')} GitHub",
                    },
                },
                orientation="vertical",
            ),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
