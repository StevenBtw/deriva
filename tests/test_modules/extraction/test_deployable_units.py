"""Deployable units from structure: containers, manifest entry points, mainframe applications, the fallback."""

from __future__ import annotations

from deriva.modules.extraction.deployable_units import RepoFacts, UnitRules, detect_units

RULES = UnitRules(code_subtypes=frozenset({"python", "java", "javascript", "typescript", "cobol"}))


def _file(path: str, subtype: str | None = None, file_type: str | None = None) -> dict:
    name = path.rsplit("/", 1)[-1]
    kind = file_type or ("source" if subtype else "config")
    return {"id": f"file::r::{path}", "path": path, "name": name, "file_type": kind, "subtype": subtype}


def _units(files, **facts):
    units = detect_units(RepoFacts(repository="r", files=files, **facts), RULES)
    return {u.path + (f"::{u.entry}" if u.entry else "") + (f"::{u.kind}" if u.kind in ("online", "batch") else ""): u for u in units}


def test_a_container_folder_with_own_code_is_a_unit_and_one_without_code_is_not():
    files = [
        _file("r/shop/Dockerfile"),
        _file("r/shop/src/App.java", "java"),
        _file("r/proxy/nginx/Dockerfile"),
        _file("r/proxy/nginx/nginx.conf"),
        _file("r/db/Dockerfile"),
        _file("r/db/setup.sql", "sql"),
    ]

    units = _units(files)

    assert list(units) == ["r/shop"]
    assert units["r/shop"].kind == "container" and units["r/shop"].members == {"r/shop/Dockerfile", "r/shop/src/App.java"}


def test_a_folder_that_holds_another_unit_is_no_unit_itself():
    files = [_file("r/Dockerfile.service"), _file("r/tool.py", "python"), _file("r/svc/Dockerfile"), _file("r/svc/main.py", "python")]

    assert list(_units(files)) == ["r/svc"]


def test_manifest_entry_points_make_units_and_plain_libraries_do_not():
    files = [
        _file("r/web/package.json"),
        _file("r/web/index.js", "javascript"),
        _file("r/lib/package.json"),
        _file("r/lib/index.js", "javascript"),
        _file("r/api/pom.xml"),
        _file("r/api/src/Api.java", "java"),
        _file("r/tool/pom.xml"),
        _file("r/tool/src/Main.java", "java"),
        _file("r/job/build.gradle"),
        _file("r/job/src/Job.java", "java"),
    ]
    manifests = {
        "r/web/package.json": '{"name": "web", "description": "The shop pages", "scripts": {"start": "serve"}}',
        "r/lib/package.json": '{"name": "lib", "main": "index.js"}',
        "r/api/pom.xml": "<project><artifactId>api</artifactId><packaging>war</packaging></project>",
        "r/tool/pom.xml": "<project><artifactId>tool</artifactId><packaging>jar</packaging></project>",
        "r/job/build.gradle": "plugins {\n  id 'application'\n}\n",
    }

    units = _units(files, manifests=manifests)

    assert sorted(units) == ["r/api", "r/job", "r/web"]
    assert units["r/web"].manifest_name == "web" and units["r/web"].manifest_description == "The shop pages"
    assert units["r/api"].kind == "war" and units["r/job"].kind == "application"


def test_a_spring_boot_module_with_a_dockerfile_is_one_unit_with_both_evidences():
    files = [_file("r/svc/Dockerfile"), _file("r/svc/pom.xml"), _file("r/svc/src/Svc.java", "java")]
    manifests = {"r/svc/pom.xml": "<project><build><plugin><artifactId>spring-boot-maven-plugin</artifactId></plugin></build></project>"}

    units = _units(files, manifests=manifests)

    assert list(units) == ["r/svc"] and units["r/svc"].evidence == ["container: r/svc/Dockerfile", "spring-boot: r/svc/pom.xml"]


def test_a_package_with_project_scripts_is_one_unit_with_the_files_its_entry_modules_import():
    files = [
        _file("r/pyproject.toml"),
        _file("r/pkg/__init__.py", "python"),
        _file("r/pkg/cli/main.py", "python"),
        _file("r/pkg/app/main.py", "python"),
        _file("r/pkg/core/model.py", "python"),
        _file("r/pkg/core/store.py", "python"),
        _file("r/pkg/unused.py", "python"),
    ]
    manifests = {"r/pyproject.toml": '[project]\nname = "pkg"\ndescription = "A tool"\n[project.scripts]\npkg-cli = "pkg.cli.main:run"\npkg-app = "pkg.app.main:run"\n'}
    imports = [("r/pkg/cli/main.py", "r/pkg/core/model.py"), ("r/pkg/core/model.py", "r/pkg/core/store.py"), ("r/pkg/app/main.py", "r/pkg/core/model.py")]

    units = _units(files, manifests=manifests, imports=imports)

    # No script is named like the package: the first by name is the unit's entry; every script is an entry point
    assert sorted(units) == ["r::pkg-app"]
    unit = units["r::pkg-app"]
    assert unit.members == {"r/pkg/cli/main.py", "r/pkg/app/main.py", "r/pkg/core/model.py", "r/pkg/core/store.py"}
    assert unit.name == "pkg-app" and unit.kind == "script"
    assert unit.evidence == ["script pkg-app = pkg.app.main:run: r/pyproject.toml", "script pkg-cli = pkg.cli.main:run: r/pyproject.toml"]


def test_a_script_named_like_its_package_is_the_entry_and_a_script_running_another_packages_module_adds_nothing():
    files = [
        _file("r/pyproject.toml"),
        _file("r/tool/cli.py", "python"),
        _file("r/packages/web/pyproject.toml"),
        _file("r/packages/web/src/tool/web/main.py", "python"),
        _file("r/packages/web/src/tool/web/pages.py", "python"),
    ]
    manifests = {
        "r/pyproject.toml": '[project]\nname = "tool"\n[project.scripts]\ntool = "tool.cli:main"\n',
        # The web package re-exports the root package's command (tool.cli lives in the root package, not here)
        "r/packages/web/pyproject.toml": '[project]\nname = "tool-web"\n[project.scripts]\nserve = "tool.web.main:main"\ntool-web = "tool.web.main:main"\ntool = "tool.cli:main"\n',
    }
    imports = [("r/packages/web/src/tool/web/main.py", "r/packages/web/src/tool/web/pages.py")]

    units = _units(files, manifests=manifests, imports=imports)

    assert sorted(units) == ["r/packages/web::tool-web", "r::tool"]
    web = units["r/packages/web::tool-web"]
    assert web.members == {"r/packages/web/src/tool/web/main.py", "r/packages/web/src/tool/web/pages.py"}
    assert [e.split(" = ")[0] for e in web.evidence] == ["script serve", "script tool-web"]


MAINFRAME = [
    _file("r/app/cbl/ONL1.cbl", "cobol"),
    _file("r/app/cbl/ONL2.cbl", "cobol"),
    _file("r/app/cbl/BAT1.cbl", "cobol"),
    _file("r/app/cbl/SUB1.cbl", "cobol"),
    _file("r/app/cpy/REC.cpy", "cobol"),
    _file("r/app/bms/MAP1.bms", "bms", "source"),
    _file("r/app/jcl/JOB1.jcl", "jcl", "source"),
    _file("r/app/app-mod/cbl/MOD1.cbl", "cobol"),
    _file("r/app/app-mod/jcl/MODJOB.jcl", "jcl", "source"),
]
PROGRAMS = [
    {"id": "p:ONLY1", "path": "r/app/cbl/ONL1.cbl", "name": "ONLY1", "decorators": ["online", "cics", "map:MAP1"]},
    {"id": "p:ONLY2", "path": "r/app/cbl/ONL2.cbl", "name": "ONLY2", "decorators": ["online", "cics"]},
    {"id": "p:BAT1", "path": "r/app/cbl/BAT1.cbl", "name": "BAT1", "decorators": ["batch"]},
    {"id": "p:SUB1", "path": "r/app/cbl/SUB1.cbl", "name": "SUB1", "decorators": []},
    {"id": "p:MOD1", "path": "r/app/app-mod/cbl/MOD1.cbl", "name": "MOD1", "decorators": ["online", "cics"]},
]


def test_the_core_application_splits_into_online_and_batch_and_a_module_stays_whole():
    units = _units(
        MAINFRAME,
        programs=PROGRAMS,
        screens=[{"id": "s:MAP1", "path": "r/app/bms/MAP1.bms", "name": "MAP1"}],
        job_runs=[("r/app/jcl/JOB1.jcl", "p:BAT1"), ("r/app/app-mod/jcl/MODJOB.jcl", "p:MOD1")],
        program_calls=[("p:ONLY1", "p:SUB1"), ("p:ONLY2", "p:SUB1"), ("p:BAT1", "p:SUB1")],
        imports=[("r/app/cbl/ONL1.cbl", "r/app/cpy/REC.cpy"), ("r/app/cbl/BAT1.cbl", "r/app/cpy/REC.cpy")],
    )

    assert sorted(units) == ["r/app/app-mod", "r/app::batch", "r/app::online"]
    online, batch, module = units["r/app::online"], units["r/app::batch"], units["r/app/app-mod"]
    # The subprogram joins the unit of most of its callers (two online, one batch)
    assert online.nodes == {"p:ONLY1", "p:ONLY2", "p:SUB1", "s:MAP1"} and batch.nodes == {"p:BAT1"}
    assert {"r/app/cbl/ONL1.cbl", "r/app/cpy/REC.cpy", "r/app/bms/MAP1.bms", "r/app/cbl/SUB1.cbl"} <= online.members
    assert batch.members == {"r/app/cbl/BAT1.cbl", "r/app/cpy/REC.cpy", "r/app/jcl/JOB1.jcl"}
    assert module.kind == "module" and module.members == {"r/app/app-mod/cbl/MOD1.cbl", "r/app/app-mod/jcl/MODJOB.jcl"}
    assert online.name == "app Online" and online.module == "app" and module.name == "app-mod"


def test_a_subprogram_with_as_many_batch_as_online_callers_is_online():
    units = _units(MAINFRAME[:5], programs=PROGRAMS[:4], job_runs=[("r/app/jcl/JOB1.jcl", "p:BAT1")], program_calls=[("p:ONLY1", "p:SUB1"), ("p:BAT1", "p:SUB1")])

    assert "p:SUB1" in units["r/app::online"].nodes


def test_without_any_unit_the_repository_is_one():
    files = [_file("r/a.py", "python"), _file("r/b/c.py", "python")]

    units = _units(files)

    assert list(units) == ["r"] and units["r"].kind == "repository" and units["r"].members == {"r/a.py", "r/b/c.py"}


def test_readme_lines_that_name_the_unit_are_kept_as_naming_evidence():
    files = [_file("r/shop/Dockerfile"), _file("r/shop/src/App.java", "java")]
    documents = {"r/README.md": "# Demo\n\n- shop: the storefront for customers\n- other things\n", "r/shop/README.md": "Shop service.\n"}

    units = _units(files, documents=documents)

    assert units["r/shop"].readme_lines == ["Shop service.", "shop: the storefront for customers"]


def test_a_unit_with_a_page_entry_has_web_entries_and_build_output_does_not_count():
    files = [
        _file("r/web/Dockerfile"),
        _file("r/web/src/App.js", "javascript"),
        _file("r/web/public/index.html"),
        _file("r/web/node_modules/lib/index.html"),
        _file("r/web/build/index.html"),
        _file("r/api/Dockerfile"),
        _file("r/api/src/Api.java", "java"),
        _file("r/api/src/main/webapp/WEB-INF/web.xml"),
    ]

    units = _units(files)

    assert units["r/web"].web_entries == ["r/web/public/index.html"]
    assert units["r/api"].web_entries == []  # a servlet descriptor alone serves no pages


def test_server_pages_and_templates_are_web_entries():
    files = [
        _file("r/shop/Dockerfile"),
        _file("r/shop/src/Shop.java", "java"),
        _file("r/shop/src/main/webapp/WEB-INF/pages/cart.jsp"),
        _file("r/shop/src/main/resources/templates/home.html"),
        _file("r/shop/src/main/resources/templates/notes.txt"),
        _file("r/shop/src/test/resources/templates/fixture.html"),
    ]

    assert _units(files)["r/shop"].web_entries == ["r/shop/src/main/resources/templates/home.html", "r/shop/src/main/webapp/WEB-INF/pages/cart.jsp"]


def test_the_web_entries_of_a_nested_unit_are_not_its_parents():
    files = [
        _file("r/pyproject.toml"),
        _file("r/app/main.py", "python"),
        _file("r/ui/Dockerfile"),
        _file("r/ui/src/main.js", "javascript"),
        _file("r/ui/index.html"),
    ]
    manifests = {"r/pyproject.toml": '[project]\nname = "app"\n[project.scripts]\napp = "app.main:run"\n'}

    units = _units(files, manifests=manifests)

    assert units["r/ui"].web_entries == ["r/ui/index.html"]
    assert units["r::app"].web_entries == []


def test_the_first_heading_of_the_units_readme_is_its_readme_title():
    files = [_file("r/shop/Dockerfile"), _file("r/shop/src/App.java", "java")]
    documents = {"r/shop/README.md": "Intro line\n\n# Storefront Service\n\n## Setup\n", "r/README.md": "# Demo Platform\n"}

    units = _units(files, documents=documents)

    assert units["r/shop"].readme_title == "Storefront Service"


def test_a_readme_title_drops_markdown_images_and_keeps_link_text():
    files = [_file("r/shop/Dockerfile"), _file("r/shop/src/App.java", "java")]
    documents = {"r/shop/README.md": "# ![Logo](../img/logo.png) Demo: [Storefront](docs/x.md) **Service**\n"}

    assert _units(files, documents=documents)["r/shop"].readme_title == "Demo: Storefront Service"


# Closed-set naming: each unit's name candidates come from structure and documentation, never from an LLM
NAMING = UnitRules(
    code_subtypes=frozenset({"python", "java", "javascript", "cobol"}),
    generic_words=("Application", "App", "CLI", "Server", "Service", "Backend", "Frontend", "UI", "Batch", "Online", "Extension"),
    title_cut_words=("with", "using"),
    kind_nouns=(("container", "Server"), ("*", "Application")),
)


def _named(files, rules=NAMING, **facts):
    units = detect_units(RepoFacts(repository="r", files=files, **facts), rules)
    return {u.path + (f"::{u.entry}" if u.entry else "") + (f"::{u.kind}" if u.kind in ("online", "batch") else ""): u for u in units}


def _container(folder: str) -> list[dict]:
    return [_file(f"r/{folder}/Dockerfile"), _file(f"r/{folder}/src/App.java", "java")]


def test_the_product_name_is_the_first_part_of_the_root_readme_title():
    units = _named(_container("shop"), documents={"r/README.md": "# Shop Platform - Online Store for Teas\n"})

    assert units["r/shop"].product == "Shop Platform"
    assert _named(_container("shop"))["r/shop"].product == "r"  # no README, no root manifest: the repository name


def test_a_readme_title_naming_the_product_and_the_folder_gives_one_candidate():
    documents = {"r/README.md": "# Shop\n", "r/customer-core/README.md": "# ![Logo](x.png) Shop: Customer Core\n"}
    manifests = {"r/customer-core/package.json": '{"name": "customer-core", "scripts": {"start": "node ."}}'}

    units = _named([*_container("customer-core"), _file("r/customer-core/package.json")], documents=documents, manifests=manifests)

    assert units["r/customer-core"].name_candidates == [("Customer Core", "readme")]


def test_title_parts_drop_product_and_generic_words_and_a_cut_word_keeps_only_the_shorter_variant():
    """The words after a cut word name technology ("with DB2"), which belongs in the technology layer, not in the name."""
    documents = {"r/README.md": "# Shop\n", "r/order-imports/README.md": "# Shop Extension - Order Imports with Queue and Store\n"}

    names = [n for n, _ in _named(_container("order-imports"), documents=documents)["r/order-imports"].name_candidates]

    assert names[0] == "Order Imports" and "Order Imports with Queue and Store" not in names  # "Shop Extension": product and generic


def test_links_to_the_folder_written_as_names_are_candidates_and_prose_links_are_not():
    documents = {
        "r/README.md": "# Shop\n\n- **[Risk Engine](risk-engine)** computes risk.\n- See [the risk documentation](./risk-engine/).\n",
        "r/docs/overview.md": "The [Pending Risk Checks](../risk-engine) run nightly.\n",
    }

    names = [n for n, s in _named(_container("risk-engine"), documents=documents)["r/risk-engine"].name_candidates if s == "docs"]

    assert names == ["Risk Engine", "Pending Risk Checks"]


def test_table_cells_and_bold_terms_ending_in_the_folder_name_are_candidates():
    readme = (
        "# Clinic\n\n| Component | Runtime |\n|---|---|\n| KVS Bridge | Java |\n| Bridge Trigger | Lambda |\n"
        "| Invoked by the flow to start the bridge | x |\n\n**Media Bridge** relays audio.\n"
    )

    names = [n for n, s in _named(_container("bridge"), documents={"r/README.md": readme})["r/bridge"].name_candidates if s == "docs"]

    assert names == ["KVS Bridge", "Media Bridge"]


def test_a_documentation_name_loses_the_punctuation_that_introduces_its_description():
    """A list like "**Media Bridge:** relays audio" writes the separator inside the bold term: the name has no colon."""
    readme = "# Clinic\n\n- **Media Bridge:** relays audio.\n- [Bridge Trigger;](bridge) starts it.\n\n| Part | Notes |\n|---|---|\n| KVS Bridge, | Java |\n"

    names = [n for n, s in _named(_container("bridge"), documents={"r/README.md": readme})["r/bridge"].name_candidates if s == "docs"]

    assert names == ["Media Bridge", "Bridge Trigger", "KVS Bridge"]  # in document order


def test_a_generic_folder_name_takes_no_table_cells():
    readme = "# Clinic\n\n| Part | Notes |\n|---|---|\n| Billing Backend | Java |\n"

    units = _named(_container("backend"), documents={"r/README.md": readme})

    assert units["r/backend"].name_candidates == [("Clinic Backend", "structure")]


def test_the_manifest_name_loses_only_the_whole_product_prefix():
    documents = {"r/README.md": "# Loan Desk\n"}
    manifests = {"r/web/package.json": '{"name": "loan-desk-frontend", "scripts": {"start": "vite"}}', "r/ops/package.json": '{"name": "loan-ops", "scripts": {"start": "node ."}}'}
    files = [*_container("web"), _file("r/web/package.json"), *_container("ops"), _file("r/ops/package.json")]

    units = _named(files, documents=documents, manifests=manifests)

    assert [n for n, s in units["r/web"].name_candidates if s == "manifest"] == ["Loan Desk Frontend"]  # generic: the product in front
    assert [n for n, s in units["r/ops"].name_candidates if s == "manifest"] == ["Loan Ops"]


def test_a_taken_name_is_dropped_and_when_all_are_taken_the_kind_noun_is_added():
    manifests = {"r/spring-admin/package.json": '{"name": "spring-admin", "scripts": {"start": "java"}}'}
    files = [*_container("spring-admin"), _file("r/spring-admin/package.json")]

    units = _named(files, manifests=manifests, reserved={"Spring Admin"})

    assert units["r/spring-admin"].name_candidates == [("Spring Admin Server", "guard")]


def test_documentation_keeps_its_spelling_and_generic_words_take_the_lists_casing():
    documents = {"r/README.md": "# Shop\n", "r/risk-server/README.md": "# Shop: Risk Management server with cache\n"}

    names = [n for n, _ in _named(_container("risk-server"), documents=documents)["r/risk-server"].name_candidates]

    assert names[0] == "Risk Management Server"


def test_mainframe_core_units_are_named_after_the_product_and_the_other_title_parts():
    units = _named(
        MAINFRAME,
        programs=PROGRAMS,
        job_runs=[("r/app/jcl/JOB1.jcl", "p:BAT1")],
        documents={"r/README.md": "# CardShop - Mainframe Card Management\n"},
    )

    assert units["r/app::online"].name_candidates == [
        ("CardShop Online", "mainframe"),
        ("Mainframe Card Management Online", "mainframe"),
        ("CardShop App Online", "structure"),  # "app Online" is only generic words: the product in front
    ]


def test_unit_ids_tell_a_nested_folder_from_a_folder_with_an_underscore():
    from deriva.modules.extraction.deployable_units import Unit, unit_id

    assert unit_id("r", Unit(path="r/a/b", name="b", kind="container")) != unit_id("r", Unit(path="r/a_b", name="a_b", kind="container"))


def test_programs_at_the_repository_root_are_the_core_application():
    units = _units([_file("r/ONL1.cbl", "cobol")], programs=[{"id": "p:ONLY1", "path": "r/ONL1.cbl", "name": "ONLY1", "decorators": ["online"]}])

    assert list(units) == ["r::online"] and units["r::online"].nodes == {"p:ONLY1"}


def test_a_folder_holding_a_unit_folder_is_no_unit_whatever_the_order_they_were_found_in():
    """The folder below is found first (its container file), the folder above second (its manifest); a script replaces the one below."""
    files = [
        _file("r/a/package.json"),
        _file("r/a/index.js", "javascript"),
        _file("r/a/b/Dockerfile"),
        _file("r/a/b/pyproject.toml"),
        _file("r/a/b/main.py", "python"),
    ]
    manifests = {"r/a/package.json": '{"name": "a", "scripts": {"start": "node ."}}', "r/a/b/pyproject.toml": '[project]\nname = "b"\n[project.scripts]\ntool = "main:run"\n'}

    assert list(_units(files, manifests=manifests)) == ["r/a/b::tool"]


def test_a_taken_guard_name_gets_the_product_in_front():
    manifests = {"r/spring-admin/package.json": '{"name": "spring-admin", "scripts": {"start": "java"}}'}
    files = [*_container("spring-admin"), _file("r/spring-admin/package.json")]

    units = _named(files, manifests=manifests, documents={"r/README.md": "# Shop\n"}, reserved={"Spring Admin", "Spring Admin Server"})

    assert units["r/spring-admin"].name_candidates == [("Shop Spring Admin Server", "guard")]


def test_a_generic_name_that_holds_the_product_gets_no_second_product():
    units = _named(_container("backend-server"), documents={"r/README.md": "# Backend Server\n"})

    assert units["r/backend-server"].name_candidates == [("Backend Server", "structure")]


def test_a_unit_of_a_package_listed_only_as_a_development_dependency_is_tooling():
    files = [
        _file("r/pyproject.toml"),
        _file("r/shop/cli.py", "python"),
        _file("r/bench/pyproject.toml"),
        _file("r/bench/run.py", "python"),
    ]
    manifests = {
        "r/pyproject.toml": '[project]\nname = "shop"\n[project.scripts]\nshop = "shop.cli:main"\n[dependency-groups]\ndev = ["shop-bench"]\n',
        "r/bench/pyproject.toml": '[project]\nname = "shop-bench"\n[project.scripts]\nshop-bench = "run:main"\n',
    }

    units = _units(files, manifests=manifests)

    assert {k: u.excluded for k, u in units.items()} == {"r::shop": None, "r/bench::shop-bench": "tooling"}
