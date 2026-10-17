"""Build modules from structure: a folder with a build manifest and code of its own; an aggregator manifest that lists
at least two modules is a parent system. Names come from the manifest (else the folder), with the repository's name
dropped from the front."""

from __future__ import annotations

from deriva.modules.extraction.build_modules import ModuleRules, detect_modules, module_id

RULES = ModuleRules(
    manifests=("pom.xml", "package.json", "pyproject.toml", "build.gradle", "build.gradle.kts", "settings.gradle"), code_subtypes=frozenset({"java", "python", "javascript"})
)


def _f(path: str, subtype: str = "java", file_type: str = "source") -> dict:
    return {"path": path, "name": path.rsplit("/", 1)[-1], "file_type": file_type, "subtype": subtype}


def _by_path(modules) -> dict:
    return {m.path: m for m in modules}


def test_a_maven_aggregator_is_a_system_over_the_modules_it_lists():
    pom = "<project><artifactId>shop-parent</artifactId><packaging>pom</packaging><modules><module>orders</module><module>billing</module></modules></project>"
    child = "<project><parent><artifactId>shop-parent</artifactId></parent><artifactId>shop-{0}</artifactId></project>"
    files = [
        _f("r/pom.xml", "xml", "build"),
        _f("r/orders/pom.xml", "xml", "build"),
        _f("r/orders/src/Order.java"),
        _f("r/billing/pom.xml", "xml", "build"),
        _f("r/billing/src/Bill.java"),
    ]
    manifests = {"r/pom.xml": pom, "r/orders/pom.xml": child.format("orders"), "r/billing/pom.xml": child.format("billing")}

    modules = _by_path(detect_modules("r", files, manifests, RULES))

    assert set(modules) == {"r", "r/orders", "r/billing"}
    assert modules["r"].system and not modules["r"].module  # lists two modules, no code of its own
    assert (modules["r/orders"].module, modules["r/orders"].parent, modules["r/orders"].files) == (True, "r", ["r/orders/pom.xml", "r/orders/src/Order.java"])
    # The project's own artifactId, not the parent's; the repository name is no part of it (here none matches)
    assert modules["r/orders"].name == "Shop Orders" and modules["r"].name == "R"  # the root: the repository name


def test_a_manifest_folder_without_code_of_its_own_is_no_module_and_nested_modules_get_their_parent():
    files = [
        _f("r/app/package.json", "json", "build"),
        _f("r/app/index.js", "javascript"),
        _f("r/app/plugins/audit/package.json", "json", "build"),
        _f("r/app/plugins/audit/hook.js", "javascript"),
        _f("r/docs/package.json", "json", "build"),
        _f("r/docs/readme.md", "markdown", "docs"),
    ]
    manifests = {"r/app/package.json": '{"name": "app"}', "r/app/plugins/audit/package.json": '{"name": "r-audit-hook"}', "r/docs/package.json": '{"name": "docs"}'}

    modules = _by_path(detect_modules("r", files, manifests, RULES))

    assert set(modules) == {"r/app", "r/app/plugins/audit"}  # docs has no code of its own
    assert modules["r/app/plugins/audit"].parent == "r/app" and modules["r/app"].parent is None
    assert modules["r/app"].files == ["r/app/index.js", "r/app/package.json"]  # the nested module's files are its own
    assert modules["r/app/plugins/audit"].name == "Audit Hook"  # the repository name "r" dropped from the front


def test_workspaces_and_includes_name_their_members_by_folder_or_glob():
    files = [
        _f("r/package.json", "json", "build"),
        _f("r/packages/core/package.json", "json", "build"),
        _f("r/packages/core/a.js", "javascript"),
        _f("r/packages/ui/package.json", "json", "build"),
        _f("r/packages/ui/b.js", "javascript"),
        _f("r/py/pyproject.toml", "toml", "build"),
        _f("r/py/libs/one/pyproject.toml", "toml", "build"),
        _f("r/py/libs/one/x.py", "python"),
        _f("r/py/libs/two/pyproject.toml", "toml", "build"),
        _f("r/py/libs/two/y.py", "python"),
        _f("r/gr/settings.gradle", "gradle", "build"),
        _f("r/gr/api/build.gradle", "gradle", "build"),
        _f("r/gr/api/A.java"),
        _f("r/gr/impl/build.gradle", "gradle", "build"),
        _f("r/gr/impl/B.java"),
    ]
    manifests = {
        "r/package.json": '{"name": "mono", "workspaces": ["packages/*"]}',
        "r/packages/core/package.json": '{"name": "@mono/core"}',
        "r/packages/ui/package.json": '{"name": "@mono/ui"}',
        "r/py/pyproject.toml": '[project]\nname = "py-root"\n[tool.uv.workspace]\nmembers = ["libs/*"]\n',
        "r/py/libs/one/pyproject.toml": '[project]\nname = "one"\n',
        "r/py/libs/two/pyproject.toml": '[project]\nname = "two"\n',
        "r/gr/settings.gradle": "rootProject.name = 'gr'\ninclude 'api', ':impl'\n",
        "r/gr/api/build.gradle": "",
        "r/gr/impl/build.gradle": "",
    }

    modules = _by_path(detect_modules("r", files, manifests, RULES))

    assert all(modules[p].system for p in ("r", "r/py", "r/gr"))
    assert modules["r/packages/core"].parent == "r" and modules["r/py/libs/two"].parent == "r/py" and modules["r/gr/impl"].parent == "r/gr"
    assert modules["r/packages/core"].name == "Core"  # a scope (@mono/) is no part of the name
    assert modules["r/gr/api"].name == "Api"  # no name in the build file: the folder


def test_an_aggregator_listing_one_module_is_no_system():
    files = [_f("r/pom.xml", "xml", "build"), _f("r/only/pom.xml", "xml", "build"), _f("r/only/src/A.java")]
    manifests = {
        "r/pom.xml": "<project><artifactId>p</artifactId><modules><module>only</module></modules></project>",
        "r/only/pom.xml": "<project><artifactId>only</artifactId></project>",
    }

    modules = _by_path(detect_modules("r", files, manifests, RULES))

    assert set(modules) == {"r/only"} and modules["r/only"].parent is None


def test_module_ids_follow_the_unit_ids():
    assert module_id("r", "r/libs/audit-hook") == "module::r::libs/audit-hook"
    assert module_id("r", "r") == "module::r::r"


def test_the_root_takes_the_repository_name_and_colliding_names_their_paths():
    """A root aggregator is named after what it holds, the repository (its artifactId is often just "parent")."""
    files = [
        _f("ShopApp/pom.xml", "xml", "build"),
        _f("ShopApp/web/package.json", "json", "build"),
        _f("ShopApp/web/a.js", "javascript"),
        _f("ShopApp/packages/web/package.json", "json", "build"),
        _f("ShopApp/packages/web/b.js", "javascript"),
    ]
    manifests = {
        "ShopApp/pom.xml": "<project><artifactId>parent</artifactId><modules><module>web</module><module>packages/web</module></modules></project>",
        "ShopApp/web/package.json": '{"name": "web"}',
        "ShopApp/packages/web/package.json": '{"name": "shop-app-web"}',
    }

    modules = _by_path(detect_modules("ShopApp", files, manifests, RULES))

    assert modules["ShopApp"].name == "Shop App"
    # Both are "Web": each takes the words of its path below the repository instead
    assert (modules["ShopApp/web"].name, modules["ShopApp/packages/web"].name) == ("Web", "Packages Web")
