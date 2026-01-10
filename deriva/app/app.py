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
async def _(
    MarimoLiveProgressReporter,
    MarimoProgressReporter,
    asyncio,
    derivation_btn,
    extraction_btn,
    mo,
    run_deriva_btn,
    session,
):
    # Run pipeline based on button clicks
    _result = None
    _kind = "neutral"
    _summary = None
    _elapsed = 0.0

    if run_deriva_btn.value:
        import time

        _start = time.time()
        print("[Deriva] Running full pipeline...")

        _extraction_stats = {}
        _derivation_stats = {}
        _all_errors = []

        # Phase 1: Extraction with progress bar
        _ext_total = session.get_extraction_step_count()
        _ext_last = None

        for _update in mo.status.progress_bar(
            session.run_extraction_iter(),
            total=_ext_total,
            title="Extraction",
            subtitle=lambda u: f"{u.step}: {u.message}" if u.step else "Starting...",
            show_rate=True,
            show_eta=True,
        ):
            _ext_last = _update
            await asyncio.sleep(0.5)

        if _ext_last and _ext_last.stats:
            _extraction_stats = _ext_last.stats.get("stats", {})
            _all_errors.extend(_ext_last.stats.get("errors", []))

        # Phase 2: Derivation with progress bar
        _der_total = session.get_derivation_step_count()
        _der_last = None

        for _update in mo.status.progress_bar(
            session.run_derivation_iter(),
            total=_der_total,
            title="Derivation",
            subtitle=lambda u: f"{u.step}: {u.message}" if u.step else "Starting...",
            show_rate=True,
            show_eta=True,
        ):
            _der_last = _update
            await asyncio.sleep(0.5)

        if _der_last and _der_last.stats:
            _derivation_stats = _der_last.stats.get("stats", {})
            _all_errors.extend(_der_last.stats.get("errors", []))

        _elapsed = time.time() - _start
        _kind = "success" if len(_all_errors) == 0 else "danger"
        _steps_completed = _extraction_stats.get("steps_completed", 0) + _derivation_stats.get("steps_completed", 0)

        print(f"[Deriva] Pipeline complete: {_steps_completed} steps in {_elapsed:.1f}s")
        _msg = f"""**Pipeline Complete** ({_elapsed:.1f}s)
- Extraction: {_extraction_stats.get("nodes_created", 0)} nodes
- Derivation: {_derivation_stats.get("elements_created", 0)} elements
- Steps completed: {_steps_completed}
- Errors: {len(_all_errors)}"""

        if _all_errors:
            _result = {"errors": _all_errors}
        else:
            _result = None

    elif extraction_btn.value:
        import time

        _start = time.time()
        print("[Deriva] Running extraction...")

        # Get total step count for determinate progress bar
        _total_steps = session.get_extraction_step_count()

        # Use progress_bar as iterator wrapper (documented pattern)
        _last_update = None
        _step_messages = []

        for _update in mo.status.progress_bar(
            session.run_extraction_iter(),
            total=_total_steps,
            title="Extraction",
            subtitle=lambda u: f"{u.step}: {u.message}" if u.step else "Starting...",
            show_rate=True,
            show_eta=True,
        ):
            _last_update = _update
            if _update.status == "complete" and _update.step:
                _step_messages.append(f"- {_update.step}: {_update.message}")
            await asyncio.sleep(0.5)

        _elapsed = time.time() - _start

        # Extract final stats from last update
        if _last_update and _last_update.stats:
            _final = _last_update.stats
            _success = _final.get("success", True)
            _stats = _final.get("stats", {})
            _errors = _final.get("errors", [])
        else:
            _success = False
            _stats = {}
            _errors = ["No updates received"]

        _kind = "success" if _success else "danger"

        # Build step details
        _step_details = ""
        if _step_messages:
            _step_details = "\n\n**Steps:**\n" + "\n".join(_step_messages)

        _msg = f"""**Extraction Complete** ({_elapsed:.1f}s)
- Repos: {_stats.get("repos_processed", 0)}
- Nodes: {_stats.get("nodes_created", 0)}
- Edges: {_stats.get("edges_created", 0)}
- Steps: {_stats.get("steps_completed", 0)}{_step_details}"""

        if _errors:
            _result = {"errors": _errors}
        else:
            _result = None

    elif derivation_btn.value:
        import time

        _start = time.time()
        print("[Deriva] Running derivation...")

        # Get total step count for determinate progress bar
        _total_steps = session.get_derivation_step_count()

        # Use progress_bar as iterator wrapper (documented pattern)
        _last_update = None
        _step_messages = []

        for _update in mo.status.progress_bar(
            session.run_derivation_iter(),
            total=_total_steps,
            title="Derivation",
            subtitle=lambda u: f"{u.step}: {u.message}" if u.step else "Starting...",
            show_rate=True,
            show_eta=True,
        ):
            _last_update = _update
            if _update.status == "complete" and _update.step:
                _step_messages.append(f"- {_update.step}: {_update.message}")
            await asyncio.sleep(0.5)

        _elapsed = time.time() - _start

        # Extract final stats from last update
        if _last_update and _last_update.stats:
            _final = _last_update.stats
            _success = _final.get("success", True)
            _stats = _final.get("stats", {})
            _errors = _final.get("errors", [])
        else:
            _success = False
            _stats = {}
            _errors = ["No updates received"]

        _kind = "success" if _success else "danger"

        print(f"[Deriva] Derivation complete: {_stats.get('elements_created', 0)} elements in {_elapsed:.1f}s")
        _msg = f"""**Derivation Complete** ({_elapsed:.1f}s)
- Elements: {_stats.get("elements_created", 0)}
- Relationships: {_stats.get("relationships_created", 0)}
- Steps: {_stats.get("steps_completed", 0)}"""

        if _errors:
            _result = {"errors": _errors}
        else:
            _result = None

    else:
        _msg = "Click a button to run pipeline steps"

    if _result and _result.get("errors"):
        _msg += "\n\n**Errors:**\n" + "\n".join(f"- {e}" for e in _result["errors"][:5])

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
        print(f"[Deriva] Creating run: {run_desc_input.value}")
        _result = session.create_run(run_desc_input.value)
        if _result.get("success"):
            print(f"[Deriva] Run created: {_result['description']}")
            mo.callout(mo.md(f"Created run: {_result['description']}"), kind="success")
        else:
            print(f"[Deriva] Run creation failed: {_result.get('error')}")
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
        print(f"[Deriva] Cloning repository: {repo_url_input.value}")
        _result = session.clone_repository(
            url=repo_url_input.value,
            name=repo_name_input.value or None,
        )
        if _result.get("success"):
            print(f"[Deriva] Repository cloned: {_result['name']}")
            set_repos_refresh(get_repos_refresh() + 1)
            mo.callout(mo.md(f"Cloned **{_result['name']}**"), kind="success")
        else:
            print(f"[Deriva] Clone failed: {_result.get('error')}")
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
        print(f"[Deriva] Deleting {len(_selected)} repository(s)...")
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
            print(f"[Deriva] Deleted: {', '.join(_deleted)}")
            mo.callout(mo.md(f"Deleted: **{', '.join(_deleted)}**"), kind="success")
        if _errors:
            print(f"[Deriva] Delete errors: {len(_errors)}")
            mo.callout(mo.md("Errors:\n" + "\n".join(f"- {e}" for e in _errors)), kind="danger")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Neo4j
    """)
    return


@app.cell
def _(mo, session):
    # Always try DB connectivity first - this is the most reliable check
    _db_connected = False
    _db_error = None
    _docker_status = None

    try:
        _stats = session.get_graph_stats()
        _db_connected = True
    except Exception as e:
        _db_error = str(e)

    # Also try Docker status for additional info
    try:
        _docker_status = session.get_neo4j_status()
    except Exception:
        pass  # Docker status is optional

    if _db_connected:
        _kind = "success"
        _port = _docker_status.get("port", 7687) if _docker_status else 7687
        _text = f"**Status:** Connected\n- Port: {_port}\n- Nodes: {_stats.get('total_nodes', 0)}"
    else:
        _kind = "warn"
        _text = "**Status:** Not connected"
        if _db_error:
            _text += f"\n- Error: {_db_error[:100]}"

    start_neo4j_btn = mo.ui.run_button(label="Start", disabled=_db_connected)
    stop_neo4j_btn = mo.ui.run_button(label="Stop", disabled=not _db_connected)

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
        print("[Deriva] Starting Neo4j...")
        try:
            _result = session.start_neo4j()
            if _result.get("success", True):
                print("[Deriva] Neo4j start initiated")
                mo.callout(mo.md("Neo4j starting..."), kind="info")
            else:
                print(f"[Deriva] Neo4j start failed: {_result.get('error', 'Unknown')}")
                mo.callout(mo.md(f"Error: {_result.get('error', 'Unknown')}"), kind="danger")
        except Exception as e:
            print(f"[Deriva] Neo4j start error: {str(e)[:100]}")
            mo.callout(mo.md(f"Docker error: {str(e)[:100]}"), kind="danger")
    elif stop_neo4j_btn.value:
        print("[Deriva] Stopping Neo4j...")
        try:
            _result = session.stop_neo4j()
            if _result.get("success", True):
                print("[Deriva] Neo4j stop initiated")
                mo.callout(mo.md("Neo4j stopping..."), kind="info")
            else:
                print(f"[Deriva] Neo4j stop failed: {_result.get('error', 'Unknown')}")
                mo.callout(mo.md(f"Error: {_result.get('error', 'Unknown')}"), kind="danger")
        except Exception as e:
            print(f"[Deriva] Neo4j stop error: {str(e)[:100]}")
            mo.callout(mo.md(f"Docker error: {str(e)[:100]}"), kind="danger")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Graph Statistics
    """)
    return


@app.cell
def _(mo):
    # State for graph stats refresh
    get_graph_refresh, set_graph_refresh = mo.state(0)
    return get_graph_refresh, set_graph_refresh


@app.cell
def _(get_graph_refresh, mo, session):
    _ = get_graph_refresh()
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
def _(clear_graph_btn, get_graph_refresh, mo, session, set_graph_refresh):
    if clear_graph_btn.value:
        print("[Deriva] Clearing graph...")
        _result = session.clear_graph()
        set_graph_refresh(get_graph_refresh() + 1)
        _kind = "success" if _result.get("success") else "danger"
        if _result.get("success"):
            print("[Deriva] Graph cleared")
        else:
            print(f"[Deriva] Clear graph failed: {_result.get('error', 'Unknown')}")
        mo.callout(mo.md(_result.get("message", _result.get("error", "Unknown"))), kind=_kind)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## ArchiMate Model
    """)
    return


@app.cell
def _(mo):
    # State for ArchiMate model stats refresh
    get_model_refresh, set_model_refresh = mo.state(0)
    return get_model_refresh, set_model_refresh


@app.cell
def _(get_model_refresh, mo, session):
    _ = get_model_refresh()
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
        print(f"[Deriva] Exporting model to {export_path_input.value}...")
        _result = session.export_model(output_path=export_path_input.value)
        if _result.get("success"):
            print(f"[Deriva] Model exported: {_result['elements_exported']} elements")
            mo.callout(
                mo.md(f"Exported {_result['elements_exported']} elements to `{_result['output_path']}`"),
                kind="success",
            )
        else:
            print(f"[Deriva] Export failed: {_result.get('error')}")
            mo.callout(mo.md(f"Error: {_result.get('error')}"), kind="danger")
    return


@app.cell
def _(mo):
    clear_model_btn = mo.ui.run_button(label="Clear Model", kind="danger")
    clear_model_btn
    return (clear_model_btn,)


@app.cell
def _(clear_model_btn, get_model_refresh, mo, session, set_model_refresh):
    if clear_model_btn.value:
        print("[Deriva] Clearing ArchiMate model...")
        _result = session.clear_model()
        set_model_refresh(get_model_refresh() + 1)
        _kind = "success" if _result.get("success") else "danger"
        if _result.get("success"):
            print("[Deriva] ArchiMate model cleared")
        else:
            print(f"[Deriva] Clear model failed: {_result.get('error', 'Unknown')}")
        mo.callout(mo.md(_result.get("message", _result.get("error", "Unknown"))), kind=_kind)
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


@app.cell
def _(mo):
    llm_cache_checkbox = mo.ui.checkbox(label="Enable response caching", value=True)
    llm_cache_checkbox
    return (llm_cache_checkbox,)


@app.cell
def _(llm_cache_checkbox, mo, session):
    _status = "enabled" if llm_cache_checkbox.value else "disabled"
    print(f"[Deriva] LLM cache: {_status}")
    _result = session.toggle_llm_cache(llm_cache_checkbox.value)
    mo.md(f"Cache: **{_status}**")
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
def _(mo):
    # State for file type refresh
    get_ft_refresh, set_ft_refresh = mo.state(0)
    return get_ft_refresh, set_ft_refresh


@app.cell
def _(get_ft_refresh, mo, session):
    _ = get_ft_refresh()
    _file_types = session.get_file_types()
    _stats = session.get_file_type_stats()

    mo.md(f"**Types:** {_stats['types']} | **Subtypes:** {_stats['subtypes']} | **Total:** {_stats['total']}")
    return


@app.cell
def _(get_ft_refresh, mo, session):
    _ = get_ft_refresh()
    _file_types = session.get_file_types()
    _rows = [{"Extension": ft["extension"], "Type": ft["file_type"], "Subtype": ft.get("subtype", "") or ""} for ft in _file_types[:50]]

    ft_table = mo.ui.table(_rows, label="File Type Registry", selection="single")
    ft_table
    return (ft_table,)


@app.cell
def _(ft_table, mo):
    _selected = ft_table.value[0] if ft_table and ft_table.value else None
    if _selected:
        ft_ext_display = mo.ui.text(value=_selected["Extension"], label="Extension", disabled=True)
        ft_type_input = mo.ui.text(value=_selected["Type"], label="Type")
        ft_subtype_input = mo.ui.text(value=_selected["Subtype"], label="Subtype")
        ft_save_btn = mo.ui.run_button(label="Save")
        mo.vstack([ft_ext_display, ft_type_input, ft_subtype_input, ft_save_btn])
    else:
        ft_ext_display = None
        ft_type_input = None
        ft_subtype_input = None
        ft_save_btn = None
        mo.md("_Select a file type to edit_")
    return ft_ext_display, ft_save_btn, ft_subtype_input, ft_type_input


@app.cell
def _(ft_ext_display, ft_save_btn, ft_subtype_input, ft_type_input, get_ft_refresh, mo, session, set_ft_refresh):
    if ft_save_btn and ft_save_btn.value and ft_ext_display:
        print(f"[Deriva] Saving file type: {ft_ext_display.value}")
        _ok = session.update_file_type(ft_ext_display.value, ft_type_input.value, ft_subtype_input.value)
        set_ft_refresh(get_ft_refresh() + 1)
        if _ok:
            print(f"[Deriva] File type saved: {ft_ext_display.value}")
            mo.callout(mo.md(f"Saved **{ft_ext_display.value}**: {ft_type_input.value}/{ft_subtype_input.value}"), kind="success")
        else:
            print(f"[Deriva] File type save failed: {ft_ext_display.value}")
            mo.callout(mo.md("Save failed"), kind="danger")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Extraction Steps
    """)
    return


@app.cell
def _(mo):
    # State for extraction config refresh
    get_ext_refresh, set_ext_refresh = mo.state(0)
    return get_ext_refresh, set_ext_refresh


@app.cell
def _(get_ext_refresh, mo, session):
    _ = get_ext_refresh()
    _configs = session.get_extraction_configs()
    _versions = session.get_config_versions().get("extraction", {})
    _rows = [
        {
            "Seq": c["sequence"],
            "Node Type": c["node_type"],
            "Ver": _versions.get(c["node_type"], 1),
            "Enabled": "Yes" if c["enabled"] else "",
            "Input": (c["input_sources"] or "")[:30],
        }
        for c in sorted(_configs, key=lambda x: x["sequence"])
    ]

    mo.ui.table(_rows, label="Extraction Configuration")
    return


@app.cell
def _(get_ext_refresh, mo, session):
    _ = get_ext_refresh()
    _configs = session.get_extraction_configs()
    _options = [c["node_type"] for c in _configs]

    ext_node_type_select = mo.ui.dropdown(options=_options, label="Node Type", value=_options[0] if _options else None)
    ext_node_type_select
    return (ext_node_type_select,)


@app.cell
def _(ext_node_type_select, get_ext_refresh, mo, session):
    _ = get_ext_refresh()
    ext_enabled = None
    ext_instruction = None
    ext_input_sources = None
    ext_save_btn = None

    if ext_node_type_select and ext_node_type_select.value:
        _configs = session.get_extraction_configs()
        _cfg = next((c for c in _configs if c["node_type"] == ext_node_type_select.value), None)
        _versions = session.get_config_versions().get("extraction", {})
        _ver = _versions.get(ext_node_type_select.value, 1)

        if _cfg:
            ext_enabled = mo.ui.checkbox(label="Enabled", value=_cfg["enabled"])
            ext_instruction = mo.ui.text_area(value=_cfg["instruction"] or "", label="Instruction", rows=3)
            ext_input_sources = mo.ui.text(value=_cfg["input_sources"] or "", label="Input Sources")
            ext_save_btn = mo.ui.run_button(label="Save")

    # Build form or placeholder
    if ext_enabled is not None:
        ext_form = mo.vstack([mo.md(f"**Current version:** {_ver}"), ext_enabled, ext_instruction, ext_input_sources, ext_save_btn])
    else:
        ext_form = mo.md("_Select a node type to edit_")
    return ext_enabled, ext_input_sources, ext_instruction, ext_save_btn, ext_form


@app.cell
def _(ext_form):
    ext_form
    return


@app.cell
def _(
    ext_enabled,
    ext_input_sources,
    ext_instruction,
    ext_node_type_select,
    ext_save_btn,
    get_ext_refresh,
    mo,
    session,
    set_ext_refresh,
):
    if ext_save_btn and ext_save_btn.value and ext_node_type_select and ext_node_type_select.value:
        print(f"[Deriva] Saving extraction config: {ext_node_type_select.value}")
        _result = session.save_extraction_config(
            ext_node_type_select.value,
            enabled=ext_enabled.value if ext_enabled else False,
            instruction=ext_instruction.value if ext_instruction else "",
            input_sources=ext_input_sources.value if ext_input_sources else "",
        )
        set_ext_refresh(get_ext_refresh() + 1)
        if _result.get("success"):
            _new_ver = _result.get("new_version", "?")
            print(f"[Deriva] Extraction config saved: {ext_node_type_select.value} v{_new_ver}")
            mo.callout(mo.md(f"Saved **{ext_node_type_select.value}** → version {_new_ver}"), kind="success")
        else:
            print(f"[Deriva] Extraction config save failed: {ext_node_type_select.value}")
            mo.callout(mo.md(f"Failed: {_result.get('error', 'Unknown')}"), kind="danger")
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
def _(mo):
    # State for derivation config refresh
    get_der_refresh, set_der_refresh = mo.state(0)
    return get_der_refresh, set_der_refresh


@app.cell
def _(get_der_refresh, mo, session):
    _ = get_der_refresh()
    _configs = session.get_derivation_configs()
    _versions = session.get_config_versions().get("derivation", {})
    _rows = [
        {
            "Seq": c["sequence"],
            "Phase": c.get("phase", "generate"),
            "Step": c["element_type"],
            "Ver": _versions.get(c["element_type"], 1),
            "Enabled": "Yes" if c["enabled"] else "",
        }
        for c in sorted(_configs, key=lambda x: x["sequence"])
    ]

    mo.ui.table(_rows, label="Derivation Configuration")
    return


@app.cell
def _(get_der_refresh, mo, session):
    _ = get_der_refresh()
    _configs = session.get_derivation_configs()
    _options = [c["element_type"] for c in _configs]

    der_element_type_select = mo.ui.dropdown(options=_options, label="Element Type", value=_options[0] if _options else None)
    der_element_type_select
    return (der_element_type_select,)


@app.cell
def _(der_element_type_select, get_der_refresh, mo, session):
    _ = get_der_refresh()
    if der_element_type_select.value:
        _configs = session.get_derivation_configs()
        _cfg = next((c for c in _configs if c["element_type"] == der_element_type_select.value), None)
        _versions = session.get_config_versions().get("derivation", {})
        _ver = _versions.get(der_element_type_select.value, 1)

        if _cfg:
            der_enabled = mo.ui.checkbox(label="Enabled", value=_cfg["enabled"])
            der_instruction = mo.ui.text_area(value=_cfg["instruction"] or "", label="Instruction", rows=3)
            der_query = mo.ui.text_area(value=_cfg["input_graph_query"] or "", label="Graph Query", rows=2)
            der_save_btn = mo.ui.run_button(label="Save")

            mo.vstack([mo.md(f"**Current version:** {_ver}"), der_enabled, der_instruction, der_query, der_save_btn])
    return der_enabled, der_instruction, der_query, der_save_btn


@app.cell
def _(
    der_element_type_select,
    der_enabled,
    der_instruction,
    der_query,
    der_save_btn,
    get_der_refresh,
    mo,
    session,
    set_der_refresh,
):
    if der_save_btn.value and der_element_type_select.value:
        print(f"[Deriva] Saving derivation config: {der_element_type_select.value}")
        _result = session.save_derivation_config(
            der_element_type_select.value,
            enabled=der_enabled.value,
            instruction=der_instruction.value,
            input_graph_query=der_query.value,
        )
        set_der_refresh(get_der_refresh() + 1)
        if _result.get("success"):
            _new_ver = _result.get("new_version", "?")
            print(f"[Deriva] Derivation config saved: {der_element_type_select.value} v{_new_ver}")
            mo.callout(mo.md(f"Saved **{der_element_type_select.value}** → version {_new_ver}"), kind="success")
        else:
            print(f"[Deriva] Derivation config save failed: {der_element_type_select.value}")
            mo.callout(mo.md(f"Failed: {_result.get('error', 'Unknown')}"), kind="danger")
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
    import asyncio

    from deriva.app.progress import MarimoLiveProgressReporter, MarimoProgressReporter
    from deriva.services.session import PipelineSession

    session = PipelineSession(auto_connect=True)
    return MarimoLiveProgressReporter, MarimoProgressReporter, PipelineSession, asyncio, session


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


def main() -> None:
    """Entry point for the Marimo app."""
    app.run()


if __name__ == "__main__":
    main()
