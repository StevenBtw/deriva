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


def test_compose_services_carry_their_published_and_container_ports():
    compose = 'services:\n  shop:\n    build: ./shop\n    ports: ["8080:80", "9000"]\n  db:\n    image: postgres\n    ports:\n      - "127.0.0.1:5432:5432"\n'

    env = detect_deployments("r", {"r/docker-compose.yml": compose}, UNITS, RULES).primary

    assert {s.name: s.ports for s in env.services} == {"shop": [80, 8080, 9000], "db": [5432]}


QUALIFIED = DeploymentRules(
    cloud_resources=(("AWS::ECS::Service", "container"), ("AWS::RDS::DBInstance", "managed"), ("AWS::ElasticLoadBalancingV2::LoadBalancer", "managed")),
    cloud_qualifiers=(("AWS::ElasticLoadBalancingV2::LoadBalancer", "Type", "application"), ("AWS::RDS::DBInstance", "Engine", "")),
)
CDK = {
    "r/infra/lib/services.ts": {
        "shopService": {"Type": "AWS::ECS::Service", "Properties": {}, "Names": ["shopService", "shop"], "Environment": "AWS ECS Fargate"},
        "otherService": {"Type": "AWS::ECS::Service", "Properties": {}, "Names": ["otherService", "other"], "Environment": "AWS ECS Fargate"},
        "Db": {"Type": "AWS::RDS::DBInstance", "Properties": {"Engine": "postgres"}, "Names": ["Db"]},
    }
}


def test_cdk_containers_are_matched_to_units_by_name_and_the_cloud_comes_before_compose():
    result = detect_deployments("r", {"r/docker-compose.yml": COMPOSE}, UNITS, QUALIFIED, cdk=CDK)

    env = result.primary
    assert (env.kind, env.name, env.file) == ("cloud", "AWS ECS Fargate", "r/infra/lib")  # the name the construct table gives
    assert [(s.name, s.unit) for s in env.services] == [("otherService", None), ("shopService", "unit::r::shop")]  # no unit named other
    assert env.managed == ["AWS::RDS::DBInstance::postgres"]  # the engine qualifies the managed service
    assert [e.kind for e in result.others] == ["compose"]


def test_cloudformation_resources_are_qualified_by_their_property_or_its_default():
    template = (
        "Resources:\n  App:\n    Type: AWS::ECS::Service\n  Lb:\n    Type: AWS::ElasticLoadBalancingV2::LoadBalancer\n"
        "  Db:\n    Type: AWS::RDS::DBInstance\n    Properties:\n      Engine: !Ref EngineParameter\n"
    )

    env = detect_deployments("r", {"r/shop/infra/cloudformation.yaml": template}, UNITS, QUALIFIED).primary

    # A load balancer without a Type is an application one; an engine that is no literal (a !Ref) qualifies nothing
    assert env.managed == ["AWS::ElasticLoadBalancingV2::LoadBalancer::application", "AWS::RDS::DBInstance::engineparameter"]


def test_a_qualified_managed_service_takes_its_qualified_name_else_the_plain_one():
    from deriva.modules.extraction.deployments import technology_layer
    from deriva.modules.extraction.technologies import catalog_from_params

    catalog = catalog_from_params(
        [
            {"name": "Amazon RDS", "kind": "managed service", "aliases": ["aws::rds::dbinstance"]},
            {"name": "Amazon RDS for PostgreSQL", "kind": "managed service", "aliases": ["aws::rds::dbinstance::postgres"]},
        ]
    )
    other = {"r/infra/lib/db.ts": {"Db": {"Type": "AWS::RDS::DBInstance", "Properties": {"Engine": "oracle"}, "Names": ["Db"]}}}

    qualified = technology_layer("r", {}, UNITS, QUALIFIED, catalog, {}, cdk={**CDK})
    plain = technology_layer("r", {}, UNITS, QUALIFIED, catalog, {}, cdk={"r/infra/lib/services.ts": CDK["r/infra/lib/services.ts"], **other})

    assert [s.name for s in qualified.software] == ["Amazon RDS for PostgreSQL"]
    assert [s.name for s in plain.software] == ["Amazon RDS", "Amazon RDS for PostgreSQL"]


def test_a_driver_detected_engine_is_the_managed_service_of_that_engine_in_the_same_environment():
    from deriva.modules.extraction.deployments import technology_layer
    from deriva.modules.extraction.technologies import catalog_from_params

    catalog = catalog_from_params(
        [
            {"name": "PostgreSQL", "kind": "database", "aliases": ["postgres", "psycopg2"]},
            {"name": "Amazon RDS for PostgreSQL", "kind": "managed service", "aliases": ["aws::rds::dbinstance::postgres"]},
        ]
    )
    files = {"r/shop/requirements.txt": "psycopg2==2.9\n"}

    layer = technology_layer("r", files, UNITS, QUALIFIED, catalog, {}, cdk=CDK)

    [rds] = layer.software
    assert rds.name == "Amazon RDS for PostgreSQL"
    assert rds.serves == ["unit::r::shop"]  # the driver's use moves to the managed service
    assert sorted(rds.evidence) == ["cloud template", "dependency of unit::r::shop"]


def test_an_engine_that_runs_in_the_environment_itself_stays_separate():
    from deriva.modules.extraction.deployments import technology_layer
    from deriva.modules.extraction.technologies import catalog_from_params

    catalog = catalog_from_params([{"name": "PostgreSQL", "kind": "database", "aliases": ["postgres"]}])

    layer = technology_layer("r", {"r/docker-compose.yml": COMPOSE}, UNITS, QUALIFIED, catalog, {})

    assert [s.name for s in layer.software] == ["PostgreSQL"]  # no managed service of the engine: nothing to merge into


def test_the_environment_folder_is_the_common_leading_part_of_its_files():
    """r/team-a/k8s and r/team-b/k8s share only r: a later equal folder name is no common folder."""
    manifest = "kind: Deployment\nmetadata:\n  name: {0}\nspec:\n  template:\n    spec:\n      containers:\n        - image: acme/{0}\n"
    files = {"r/team-a/k8s/shop.yaml": manifest.format("shop"), "r/team-b/k8s/billing.yaml": manifest.format("billing")}
    template = "Resources:\n  App:\n    Type: AWS::ECS::Service\n"

    assert detect_deployments("r", files, UNITS, RULES).primary.file == "r"
    cloud = detect_deployments("r", {"r/a/infra/t.yaml": template, "r/b/infra/t.yaml": template}, UNITS, RULES).primary
    assert cloud.file == "r"


def test_a_registry_variable_before_the_image_name_is_dropped_with_its_slash():
    from deriva.modules.extraction.deployments import built_images

    files = {"r/build.sh": 'docker build -t "${REGISTRY}/shop-base:1" ./base\ndocker build -t "$REGISTRY/app" .\n'}

    assert built_images("r", files, ("*.sh",)) == {"shop-base": "r/base/Dockerfile", "app": "r/Dockerfile"}


def test_a_build_context_that_several_units_share_is_matched_by_name_or_not_at_all():
    units = [{"id": "unit::r::api", "path": "r/app", "name": "api"}, {"id": "unit::r::worker", "path": "r/app", "name": "worker"}]
    compose = "services:\n  worker:\n    build: ./app\n  jobs:\n    build: ./app\n"

    env = detect_deployments("r", {"r/docker-compose.yml": compose}, units, RULES).primary

    assert {s.name: s.unit for s in env.services} == {"worker": "unit::r::worker", "jobs": None}


def test_managed_resources_without_a_container_still_make_a_cloud_environment():
    """A serverless template (functions and managed services, no container) is a cloud environment of its own;
    an environment that runs services comes first."""
    template = "Resources:\n  Fn:\n    Type: AWS::Lambda::Function\n  Files:\n    Type: AWS::S3::Bucket\n"

    alone = detect_deployments("r", {"r/infra/template.yaml": template}, UNITS, RULES)
    assert (alone.primary.kind, alone.primary.services, alone.primary.managed) == ("cloud", [], ["AWS::Lambda::Function", "AWS::S3::Bucket"])

    with_compose = detect_deployments("r", {"r/infra/template.yaml": template, "r/docker-compose.yml": COMPOSE}, UNITS, RULES)
    assert with_compose.primary.kind == "compose" and [e.kind for e in with_compose.others] == ["cloud"]


def test_a_final_stage_built_on_an_earlier_stage_takes_that_stages_base_image():
    dockerfile = "FROM python:3.12-slim AS base\nRUN pip install x\nFROM base AS runtime\nCOPY . /app\n"
    chained = "FROM node:20 AS deps\nFROM deps AS build\nFROM build\n"

    result = detect_deployments("r", {"r/shop/Dockerfile": dockerfile, "r/services/billing/Dockerfile": chained}, UNITS, RULES)

    assert result.base_images == {"unit::r::shop": ["python:3.12-slim"], "unit::r::services/billing": ["node:20"]}


def test_a_bracketed_ipv6_host_is_no_port():
    compose = 'services:\n  db:\n    image: postgres\n    ports: ["[2001:1:2::1]:5432:80", "[::1]:9000:9000/tcp"]\n'

    env = detect_deployments("r", {"r/docker-compose.yml": compose}, UNITS, RULES).primary

    assert env.services[0].ports == [80, 5432, 9000]


def test_secret_values_are_not_kept_but_hosts_are():
    """Passwords, keys and tokens never reach the graph; a URL keeps its host (cooperation reads it) without its password."""
    compose = (
        "services:\n  shop:\n    build: ./shop\n    environment:\n"
        "      DB_PASSWORD: s3cret\n      API_KEY: abc123\n      DB_URL: postgres://app:pw@db:5432/x\n"
        "      TOKEN_URL: http://auth:8080/token\n      CLIENT_SECRET: ${CLIENT_SECRET}\n      MODE: prod\n"
    )

    (shop,) = detect_deployments("r", {"r/docker-compose.yml": compose}, UNITS, RULES).primary.services

    assert shop.environment == {
        "DB_PASSWORD": "***",
        "API_KEY": "***",
        "DB_URL": "postgres://app:***@db:5432/x",
        "TOKEN_URL": "http://auth:8080/token",
        "CLIENT_SECRET": "${CLIENT_SECRET}",  # a reference, no value
        "MODE": "prod",
    }
