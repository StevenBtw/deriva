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


def test_each_project_script_is_a_unit_with_the_files_its_entry_module_imports():
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

    assert sorted(units) == ["r::pkg-app", "r::pkg-cli"]
    assert units["r::pkg-cli"].members == {"r/pkg/cli/main.py", "r/pkg/core/model.py", "r/pkg/core/store.py"}
    assert units["r::pkg-app"].members == {"r/pkg/app/main.py", "r/pkg/core/model.py", "r/pkg/core/store.py"}
    assert units["r::pkg-cli"].name == "pkg-cli" and units["r::pkg-cli"].kind == "script"


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
