"""Deployment structure: environments (compose, Kubernetes, cloud) and the services they run, matched to deployable units."""

from __future__ import annotations

from deriva.modules.extraction.deployments import DeploymentRules, detect_deployments

RULES = DeploymentRules(cloud_resources=(("AWS::ECS::Service", "container"), ("AWS::Lambda::Function", "function"), ("AWS::S3::Bucket", "managed")))
UNITS = [
    {"id": "unit::r::shop", "path": "r/shop", "name": "shop"},
    {"id": "unit::r::services/billing", "path": "r/services/billing", "name": "billing"},
]
COMPOSE = """
services:
  shop:
    build: ./shop
    depends_on: [db]
  billing:
    image: acme/r-billing:1.2
    environment:
      DB_URL: postgres://db:5432/x
  db:
    image: postgres:15-alpine
"""


def test_compose_services_are_matched_to_units_by_build_context_image_or_name():
    result = detect_deployments("r", {"r/docker-compose.yml": COMPOSE}, UNITS, RULES)

    env = result.primary
    assert (env.kind, env.name, env.file) == ("compose", "Docker Compose", "r/docker-compose.yml")
    by_name = {s.name: s for s in env.services}
    assert by_name["shop"].unit == "unit::r::shop" and by_name["shop"].depends_on == ["db"]
    assert by_name["billing"].unit == "unit::r::services/billing"  # the image's last segment names the unit
    assert by_name["db"].unit is None and by_name["db"].image == "postgres:15-alpine"
    assert by_name["billing"].environment == {"DB_URL": "postgres://db:5432/x"}


def test_the_root_compose_is_the_primary_environment_and_the_others_are_reported():
    files = {
        "r/docker-compose.yml": COMPOSE,
        "r/examples/docker-compose_extra.yml": "services:\n  x:\n    image: nginx\n",
        "r/k8s/shop.yaml": "kind: Deployment\nmetadata:\n  name: shop\nspec:\n  template:\n    spec:\n      containers:\n        - image: acme/shop\n",
    }

    result = detect_deployments("r", files, UNITS, RULES)

    assert result.primary.file == "r/docker-compose.yml"
    assert sorted((e.kind, e.file) for e in result.others) == [("compose", "r/examples/docker-compose_extra.yml"), ("kubernetes", "r/k8s")]


def test_kubernetes_workloads_are_an_environment_when_there_is_no_compose():
    manifest = "kind: Deployment\nmetadata:\n  name: shop\nspec:\n  template:\n    spec:\n      containers:\n        - image: acme/shop:3\n"
    files = {"r/k8s/shop.yaml": manifest + "---\nkind: Service\nmetadata:\n  name: shop\n"}

    env = detect_deployments("r", files, UNITS, RULES).primary

    assert (env.kind, env.name) == ("kubernetes", "Kubernetes")
    assert [(s.name, s.unit, s.image) for s in env.services] == [("shop", "unit::r::shop", "acme/shop:3")]


def test_a_cloud_template_in_a_unit_folder_deploys_that_unit_and_names_its_managed_services():
    template = (
        "Resources:\n  App:\n    Type: AWS::ECS::Service\n    Properties:\n      Cluster: !Ref Cluster\n"
        "  Files:\n    Type: AWS::S3::Bucket\n  Fn:\n    Type: AWS::Lambda::Function\n"
    )

    env = detect_deployments("r", {"r/shop/infra/cloudformation.yaml": template}, UNITS, RULES).primary

    assert (env.kind, env.name) == ("cloud", "AWS ECS")
    assert [(s.name, s.unit, s.kind) for s in env.services] == [("App", "unit::r::shop", "container")]
    assert sorted(env.managed) == ["AWS::Lambda::Function", "AWS::S3::Bucket"]


def test_the_runtime_image_of_a_unit_is_the_last_stage_of_its_dockerfile():
    dockerfile = "FROM maven:3 AS build\nRUN mvn package\nFROM eclipse-temurin:21-jre\nCOPY --from=build x y\n"

    result = detect_deployments("r", {"r/shop/Dockerfile": dockerfile}, UNITS, RULES)

    assert result.base_images == {"unit::r::shop": ["eclipse-temurin:21-jre"]}


def test_manifest_dependencies_are_read_per_manifest_kind():
    from deriva.modules.extraction.deployments import manifest_dependencies

    pom = "<project><dependencies><dependency>\n<groupId>com.h2database</groupId>\n<artifactId>h2</artifactId>\n</dependency></dependencies></project>"
    assert manifest_dependencies("r/a/pom.xml", pom) == ["h2"]
    assert manifest_dependencies("r/a/package.json", '{"dependencies": {"pg": "^8"}, "devDependencies": {"jest": "1"}}') == ["jest", "pg"]
    assert manifest_dependencies("r/a/pyproject.toml", '[project]\ndependencies = ["duckdb>=1.0", "Redis[hiredis]"]\n') == ["duckdb", "redis"]
    assert manifest_dependencies("r/a/requirements.txt", "# db\npsycopg2-binary==2.9\n-r base.txt\nuvicorn[standard]\n") == ["psycopg2-binary", "uvicorn"]
    assert manifest_dependencies("r/a/build.gradle", "implementation 'org.postgresql:postgresql:42.7.1'\n") == ["postgresql"]
    assert manifest_dependencies("r/a/README.md", "x") == []


def test_a_units_own_dockerfile_decides_its_runtime_over_nested_ones():
    files = {"r/shop/Dockerfile": "FROM eclipse-temurin:21\n", "r/shop/examples/lb/Dockerfile": "FROM nginx\n"}

    assert detect_deployments("r", files, UNITS, RULES).base_images == {"unit::r::shop": ["eclipse-temurin:21"]}


def test_a_project_built_image_resolves_through_its_build_command_and_from_chain():
    from deriva.modules.extraction.deployments import built_images, resolve_image

    files = {
        "r/tools/build.sh": 'docker buildx build --platform ${P} -t "${registry}shop-base" ../base/ --push\ndocker build -t "$REPO:latest" "$DIR"\n',
        "r/ci.yml": "steps:\n  - docker build -t app -f docker/App.Dockerfile .\n",
        "r/base/Dockerfile": "FROM tomcat:10-jdk11\n",
        "r/shop/Dockerfile": "FROM acme/shop-base:latest\n",
    }

    built = built_images("r", files, ("*.sh", "*.yml"))

    assert built == {"shop-base": "r/base/Dockerfile", "app": "r/docker/App.Dockerfile"}
    assert resolve_image("acme/shop-base:latest", built, files) == "tomcat"  # matched on the last path segment
    assert resolve_image("postgres:15", built, files) == "postgres"


def test_content_markers_name_the_files_that_use_a_subsystem():
    from deriva.modules.extraction.deployments import content_markers

    sources = {"r/app/a.cbl": "  EXEC CICS SEND MAP\n", "r/app/b.cbl": "EXEC SQL SELECT 1 END-EXEC", "r/app/c.cbl": "MOVE A TO B"}

    assert content_markers(sources, ((r"EXEC\s+CICS", "cics"), (r"EXEC\s+SQL", "db2"))) == {"cics": ["r/app/a.cbl"], "db2": ["r/app/b.cbl"]}


CATALOG_ENTRIES = [
    {"name": "PostgreSQL", "kind": "database", "aliases": ["postgres", "psycopg2"]},
    {"name": "Java runtime", "kind": "runtime", "aliases": ["eclipse-temurin"]},
    {"name": "Python runtime", "kind": "runtime", "aliases": ["python"]},
    {"name": "CICS", "kind": "transaction monitor", "aliases": ["cics"]},
]


def _layer(files, sources=None, units=UNITS):
    from deriva.modules.extraction.deployments import technology_layer
    from deriva.modules.extraction.technologies import catalog_from_params

    rules = DeploymentRules(
        cloud_resources=RULES.cloud_resources,
        markers=((r"EXEC\s+CICS", "cics"),),
        manifest_runtimes=(("pyproject.toml", "python"),),
    )
    return technology_layer("r", files, units, rules, catalog_from_params(CATALOG_ENTRIES), sources or {})


def test_the_environment_composes_what_runs_in_it_and_software_serves_the_units_that_use_it():
    files = {
        "r/docker-compose.yml": COMPOSE,
        "r/shop/Dockerfile": "FROM eclipse-temurin:21\n",
        "r/services/billing/requirements.txt": "psycopg2==2.9\nflask\n",
    }

    layer = _layer(files)

    assert layer.environment.name == "Docker Compose"
    assert layer.deployed == ["unit::r::services/billing", "unit::r::shop"]
    software = {s.name: s for s in layer.software}
    assert sorted(software) == ["Java runtime", "PostgreSQL"]  # flask is a library: not on the list, not software
    pg = software["PostgreSQL"]
    assert (pg.kind, pg.listed, pg.in_environment) == ("database", True, True)
    # shop depends on db; billing names db in a connection variable and declares the driver
    assert pg.serves == ["unit::r::services/billing", "unit::r::shop"]
    assert software["Java runtime"].serves == ["unit::r::shop"] and software["Java runtime"].in_environment


def test_an_image_off_the_list_is_kept_as_fallback_software():
    layer = _layer({"r/docker-compose.yml": "services:\n  cache:\n    image: acme/keyvalue:2\n  shop:\n    build: ./shop\n    depends_on: [cache]\n"})

    [fallback] = layer.software
    assert (fallback.name, fallback.listed, fallback.in_environment, fallback.serves) == ("acme/keyvalue", False, True, ["unit::r::shop"])


def test_mainframe_subsystems_without_another_environment_make_a_mainframe_environment():
    layer = _layer({}, sources={"r/shop/cbl/a.cbl": "EXEC CICS RETURN END-EXEC"})

    assert (layer.environment.kind, layer.environment.name) == ("mainframe", "Mainframe")
    assert [(s.name, s.unit) for s in layer.environment.services] == [("shop", "unit::r::shop")]
    [cics] = layer.software
    assert (cics.name, cics.in_environment, cics.serves) == ("CICS", True, ["unit::r::shop"])


def test_without_an_environment_a_unit_gets_the_runtime_its_manifest_implies():
    layer = _layer({"r/shop/pyproject.toml": "[project]\nname = 'shop'\ndependencies = ['psycopg2']\n"})

    assert layer.environment is None
    software = {s.name: s for s in layer.software}
    assert software["Python runtime"].serves == ["unit::r::shop"] and not software["Python runtime"].in_environment
    assert software["PostgreSQL"].serves == ["unit::r::shop"]


def test_units_that_share_a_folder_all_use_its_manifest():
    units = [{"id": "unit::r::app", "path": "r", "name": "app"}, {"id": "unit::r::cli", "path": "r", "name": "cli"}]

    layer = _layer({"r/pyproject.toml": "[project]\nname = 'r'\ndependencies = ['psycopg2']\n"}, units=units)

    assert {s.name: s.serves for s in layer.software} == {"PostgreSQL": ["unit::r::app", "unit::r::cli"], "Python runtime": ["unit::r::app", "unit::r::cli"]}


def test_units_that_share_a_folder_are_told_apart_by_their_members():
    units = [
        {"id": "unit::r::online", "path": "r/app", "name": "online", "members": ["r/app/cbl/a.cbl"]},
        {"id": "unit::r::batch", "path": "r/app", "name": "batch", "members": ["r/app/cbl/b.cbl"]},
    ]

    layer = _layer({}, sources={"r/app/cbl/a.cbl": "EXEC CICS RETURN", "r/app/cbl/b.cbl": "MOVE A TO B"}, units=units)

    assert [s.unit for s in layer.environment.services] == ["unit::r::online"]
    assert layer.software[0].serves == ["unit::r::online"]


def test_a_unit_outside_the_environment_is_served_by_its_own_runtime_without_composition():
    files = {
        "r/docker-compose.yml": "services:\n  shop:\n    build: ./shop\n",
        "r/services/billing/Dockerfile": "FROM eclipse-temurin:21\n",
        "r/services/billing/requirements.txt": "psycopg2\n",  # only the runtime counts outside the environment
    }

    layer = _layer(files)

    assert layer.deployed == ["unit::r::shop"]
    [java] = layer.software
    assert (java.name, java.in_environment, java.serves) == ("Java runtime", False, ["unit::r::services/billing"])
