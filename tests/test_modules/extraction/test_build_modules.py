"""Build modules from structure: a folder with a build manifest and code of its own; an aggregator manifest that lists
at least two modules is a parent system. Names come from the manifest (else the folder), with the repository's name
dropped from the front."""

from __future__ import annotations

from deriva.modules.extraction.build_modules import ModuleRules, behaviour_per_file, declares_entry, detect_modules, feature_areas, module_id, usage_role

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
    # Both are "Web": the full manifest names tell them apart
    assert (modules["ShopApp/web"].name, modules["ShopApp/packages/web"].name) == ("Web", "Shop App Web")


QUALITY = ModuleRules(
    manifests=RULES.manifests,
    code_subtypes=RULES.code_subtypes,
    iac_dependencies=("aws-cdk-lib", "aws-cdk", "cdktf", "@cdktf/*", "pulumi", "@pulumi/*", "serverless"),
    test_dependencies=("cypress", "jest", "mocha", "@playwright/test", "junit*", "pytest*"),
)


def test_an_infrastructure_as_code_module_and_a_test_only_module_are_no_components():
    files = [
        _f("r/infra/package.json", "json", "build"),
        _f("r/infra/app.ts", "javascript"),
        _f("r/e2e/package.json", "json", "build"),
        _f("r/e2e/spec.js", "javascript"),
        _f("r/web/package.json", "json", "build"),
        _f("r/web/app.js", "javascript"),
    ]
    manifests = {
        "r/infra/package.json": '{"name": "shop-infra", "dependencies": {"aws-cdk-lib": "2", "constructs": "10"}, "devDependencies": {"typescript": "5"}}',
        "r/e2e/package.json": '{"name": "shop-e2e", "dependencies": {"cypress": "9"}}',
        "r/web/package.json": '{"name": "shop-web", "dependencies": {"react": "18"}, "devDependencies": {"jest": "29"}}',
    }

    modules = _by_path(detect_modules("r", files, manifests, QUALITY))

    assert (modules["r/infra"].excluded, modules["r/e2e"].excluded, modules["r/web"].excluded) == ("infrastructure-as-code", "test-only", None)


def test_a_module_takes_its_folder_name_where_the_folder_says_more_and_collisions_keep_the_full_name():
    """A manifest named just "client" in risk-management-client is the Risk Management Client; two manifests that share
    a name: the one whose folder carries that name keeps it in full, the other takes its folder."""
    files = [
        _f("deriva/packages/deriva-studio/pyproject.toml", "toml", "build"),
        _f("deriva/packages/deriva-studio/app.py", "python"),
        _f("deriva/studio/package.json", "json", "build"),
        _f("deriva/studio/main.js", "javascript"),
        _f("deriva/risk-management-client/package.json", "json", "build"),
        _f("deriva/risk-management-client/c.js", "javascript"),
    ]
    manifests = {
        "deriva/packages/deriva-studio/pyproject.toml": '[project]\nname = "deriva-studio"\n',
        "deriva/studio/package.json": '{"name": "deriva-studio"}',
        "deriva/risk-management-client/package.json": '{"name": "client"}',
    }

    modules = _by_path(detect_modules("deriva", files, manifests, RULES))

    assert modules["deriva/risk-management-client"].name == "Risk Management Client"
    assert (modules["deriva/packages/deriva-studio"].name, modules["deriva/studio"].name) == ("Deriva Studio", "Studio")


def test_a_module_named_with_a_test_word_holds_tests():
    rules = ModuleRules(manifests=RULES.manifests, code_subtypes=RULES.code_subtypes, test_words=("test", "tests", "e2e"))
    files = [
        _f("r/rest-integration-test/pom.xml", "xml", "build"),
        _f("r/rest-integration-test/T.java"),
        _f("r/latest/pom.xml", "xml", "build"),
        _f("r/latest/L.java"),  # "latest" holds no test word: the words are compared whole
        _f("r/probe/pom.xml", "xml", "build"),
        _f("r/probe/P.java"),
    ]
    manifests = {
        "r/rest-integration-test/pom.xml": "<project><artifactId>rest-it</artifactId></project>",
        "r/latest/pom.xml": "<project><artifactId>latest</artifactId></project>",
        "r/probe/pom.xml": "<project><artifactId>probe-tests</artifactId></project>",  # the manifest name holds one
    }

    modules = _by_path(detect_modules("r", files, manifests, rules))

    assert {p: m.excluded for p, m in modules.items()} == {"r/rest-integration-test": "test-only", "r/latest": None, "r/probe": "test-only"}


def test_gradle_dependencies_in_map_form_count_and_a_dotted_folder_is_named_by_its_last_part():
    rules = ModuleRules(manifests=RULES.manifests, code_subtypes=RULES.code_subtypes, test_dependencies=("junit*",))
    gradle = "dependencies {\n    testCompile 'junit:junit:4.12'\n    compile group: 'com.google.guava', name: 'guava', version: '19.0'\n}\n"
    files = [
        _f("r/commons/build.gradle", "gradle", "build"),
        _f("r/commons/src/C.java"),
        _f("r/svc/tools.acme.shop.entities/pom.xml", "xml", "build"),
        _f("r/svc/tools.acme.shop.entities/E.java"),
    ]
    manifests = {"r/commons/build.gradle": gradle, "r/svc/tools.acme.shop.entities/pom.xml": "<project><artifactId>entities</artifactId></project>"}

    modules = _by_path(detect_modules("r", files, manifests, rules))

    assert modules["r/commons"].excluded is None  # guava is no test framework
    assert modules["r/svc/tools.acme.shop.entities"].name == "Entities"  # not "Tools Acme Shop Entities"


def test_a_package_the_repository_lists_only_as_a_development_dependency_is_tooling():
    files = [
        _f("r/pyproject.toml", "toml", "build"),
        _f("r/app/main.py", "python"),
        _f("r/packages/bench/pyproject.toml", "toml", "build"),
        _f("r/packages/bench/run.py", "python"),
        _f("r/packages/web/pyproject.toml", "toml", "build"),
        _f("r/packages/web/serve.py", "python"),
        _f("r/ui/package.json", "json", "build"),
        _f("r/ui/app.js", "javascript"),
        _f("r/ui-kit/package.json", "json", "build"),
        _f("r/ui-kit/kit.js", "javascript"),
        _f("r/fixtures/pom.xml", "xml", "build"),
        _f("r/fixtures/Data.java"),
        _f("r/core/pom.xml", "xml", "build"),
        _f("r/core/Core.java"),
    ]
    manifests = {
        # A dependency group (dev) is development only; an optional extra installs with the package, so it is a runtime use
        "r/pyproject.toml": '[project]\nname = "shop"\ndependencies = ["requests"]\n[project.optional-dependencies]\nweb = ["shop-web"]\n'
        '[dependency-groups]\ndev = ["Shop_Bench>=1", "pytest", "shop-web"]\n',
        "r/packages/bench/pyproject.toml": '[project]\nname = "shop-bench"\n',
        "r/packages/web/pyproject.toml": '[project]\nname = "shop-web"\n',
        "r/ui/package.json": '{"name": "shop-ui", "dependencies": {"react": "18"}, "devDependencies": {"shop-ui-kit": "1"}}',
        "r/ui-kit/package.json": '{"name": "shop-ui-kit"}',
        "r/fixtures/pom.xml": "<project><artifactId>fixtures</artifactId></project>",
        "r/core/pom.xml": "<project><artifactId>core</artifactId><dependencies><dependency><artifactId>fixtures</artifactId><scope>test</scope></dependency>"
        "</dependencies><dependencyManagement><dependencies><dependency><artifactId>fixtures</artifactId></dependency></dependencies></dependencyManagement></project>",
    }

    modules = _by_path(detect_modules("r", files, manifests, RULES))

    assert {p: m.excluded for p, m in modules.items() if m.excluded} == {"r/packages/bench": "tooling", "r/ui-kit": "tooling", "r/fixtures": "tooling"}
    assert modules["r/packages/web"].module and modules["r/core"].module


def test_an_aggregator_stays_a_system_when_one_of_its_members_is_tooling():
    files = [
        _f("r/pyproject.toml", "toml", "build"),
        _f("r/app/main.py", "python"),
        _f("r/packages/bench/pyproject.toml", "toml", "build"),
        _f("r/packages/bench/run.py", "python"),
        _f("r/packages/web/pyproject.toml", "toml", "build"),
        _f("r/packages/web/serve.py", "python"),
    ]
    manifests = {
        "r/pyproject.toml": '[project]\nname = "shop"\n[tool.uv.workspace]\nmembers = ["packages/*"]\n[dependency-groups]\ndev = ["shop-bench"]\n',
        "r/packages/bench/pyproject.toml": '[project]\nname = "shop-bench"\n',
        "r/packages/web/pyproject.toml": '[project]\nname = "shop-web"\n',
    }

    modules = _by_path(detect_modules("r", files, manifests, RULES))

    # The tooling package still counts as a listed member; only the product package is the system's member
    assert modules["r"].system and modules["r"].members == ["r/packages/web"]
    assert modules["r/packages/bench"].excluded == "tooling"


def test_an_aggregator_whose_listed_modules_are_all_excluded_is_no_system():
    files = [
        _f("r/pom.xml", "xml", "build"),
        _f("r/e2e/pom.xml", "xml", "build"),
        _f("r/e2e/Flow.java"),
        _f("r/fixtures/pom.xml", "xml", "build"),
        _f("r/fixtures/Data.java"),
    ]
    manifests = {
        "r/pom.xml": "<project><artifactId>shop</artifactId><modules><module>e2e</module><module>fixtures</module></modules>"
        "<dependencies><dependency><artifactId>fixtures</artifactId><scope>test</scope></dependency></dependencies></project>",
        "r/e2e/pom.xml": "<project><artifactId>shop-e2e</artifactId></project>",
        "r/fixtures/pom.xml": "<project><artifactId>fixtures</artifactId></project>",
    }
    rules = ModuleRules(manifests=RULES.manifests, code_subtypes=RULES.code_subtypes, test_words=("e2e",))

    modules = _by_path(detect_modules("r", files, manifests, rules))

    assert not modules.get("r") or not modules["r"].system
    assert (modules["r/e2e"].excluded, modules["r/fixtures"].excluded) == ("test-only", "tooling")


def test_a_module_no_unit_builds_is_a_component_by_who_uses_it():
    # Two or more units: a shared library, a component only with behaviour (more than one non-accessor method per file)
    assert usage_role(users=3, behaviour=3.2, entry=False, min_behaviour=1) is None
    assert usage_role(users=5, behaviour=0.9, entry=False, min_behaviour=1) == "data-only library"
    # One unit: part of that unit
    assert usage_role(users=1, behaviour=9.0, entry=True, min_behaviour=1) == "part of one unit"
    # No unit: a standalone program, a component only with a declared entry point
    assert usage_role(users=0, behaviour=0.5, entry=True, min_behaviour=1) is None
    assert usage_role(users=0, behaviour=4.0, entry=False, min_behaviour=1) == "no entry point"


def test_a_manifest_declares_an_entry_point_by_its_ecosystems_convention():
    assert declares_entry("r/c/package.json", '{"name": "client", "main": "index.js"}')
    assert declares_entry("r/c/package.json", '{"name": "tool", "bin": {"tool": "cli.js"}}')
    assert declares_entry("r/c/package.json", '{"name": "web", "scripts": {"start": "node server.js"}}')
    assert not declares_entry("r/c/package.json", '{"name": "lib", "scripts": {"test": "jest"}}')
    assert declares_entry("r/c/pom.xml", "<project><build><plugins><plugin><configuration><mainClass>a.Main</mainClass></configuration></plugin></plugins></build></project>")
    assert declares_entry("r/c/pom.xml", "<project><packaging>war</packaging></project>")
    assert not declares_entry("r/c/pom.xml", "<project><artifactId>entities</artifactId></project>")
    assert declares_entry("r/c/pyproject.toml", '[project]\nname = "t"\n[project.scripts]\nt = "t:main"\n')
    assert not declares_entry("r/c/pyproject.toml", '[project]\nname = "t"\n')


def test_behaviour_counts_the_non_accessor_methods_per_code_file():
    methods = [("a/Order.java", "getId"), ("a/Order.java", "setId"), ("a/Order.java", "isPaid"), ("a/Order.java", "Order"), ("a/Order.java", "toString"),
               ("a/Pricing.java", "price"), ("a/Pricing.java", "discount"), ("a/Pricing.java", "__init__")]  # fmt: skip

    assert behaviour_per_file(["a/Order.java", "a/Pricing.java"], methods) == 1.5  # Order: its constructor; Pricing: two
    assert behaviour_per_file([], methods) == 0.0


def test_a_unit_splits_into_feature_packages_that_each_hold_a_route_and_a_data_entity():
    base = "r/src/main/java/org/acme/clinic"
    code = [f"{base}/Application.java", f"{base}/owner/Owner.java", f"{base}/owner/OwnerController.java", f"{base}/owner/PetValidator.java",
            f"{base}/vet/Vet.java", f"{base}/vet/VetController.java", f"{base}/system/WelcomeController.java", f"{base}/model/Person.java"]  # fmt: skip
    routes = {f"{base}/owner/OwnerController.java", f"{base}/vet/VetController.java", f"{base}/system/WelcomeController.java"}
    entities = {f"{base}/owner/Owner.java", f"{base}/vet/Vet.java", f"{base}/model/Person.java"}

    # system/ has a route but no entity, model/ an entity but no route: neither is a feature package
    assert feature_areas(code, routes, entities) == [f"{base}/owner", f"{base}/vet"]


def test_layered_packages_and_a_single_feature_are_no_split():
    base = "r/src/main/java/org/acme/shop"
    layered = [f"{base}/rest/OrderResource.java", f"{base}/servlet/IndexServlet.java", f"{base}/domain/Order.java"]
    single = [f"{base}/order/Order.java", f"{base}/order/OrderController.java", f"{base}/util/Text.java"]

    assert feature_areas(layered, {f"{base}/rest/OrderResource.java", f"{base}/servlet/IndexServlet.java"}, {f"{base}/domain/Order.java"}) == []
    assert feature_areas(single, {f"{base}/order/OrderController.java"}, {f"{base}/order/Order.java"}) == []
