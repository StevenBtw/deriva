"""Technologies from structure: items from manifests, build and container files; closed classification; nodes and edges."""

from __future__ import annotations

import json

import pytest

from deriva.modules.extraction import technology_candidates as tc
from deriva.modules.extraction.base import generate_file_node_id

POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <dependencies>
    <dependency><groupId>org.acme</groupId><artifactId>acme-store-driver</artifactId></dependency>
    <dependency><groupId>org.acme</groupId><artifactId>acme-test-kit</artifactId><scope>test</scope></dependency>
    <dependency><groupId>org.acme</groupId><artifactId>${acme.artifact}</artifactId></dependency>
  </dependencies>
  <build><plugins><plugin><groupId>org.acme</groupId><artifactId>acme-deploy-plugin</artifactId></plugin></plugins></build>
  <profiles><profile><id>server-alpha</id></profile></profiles>
</project>"""

GRADLE = """dependencies {
    implementation 'org.acme:acme-store-driver:1.0'
    api("org.acme:acme-queue-client:2.0")
    testImplementation 'org.acme:acme-test-kit:1.0'
}"""

COMPOSE = """services:
  web:
    build: .
  queue:
    image: acme/queue:3
    environment:
      QUEUE_USER: admin
      QUEUE_PASSWORD: secret
"""

K8S = """apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - name: api
          image: acme/api:4
"""


@pytest.mark.parametrize(
    "path, file_type, subtype, content, expected",
    [
        (
            "pom.xml",
            "build",
            "maven",
            POM,
            [("acme-store-driver", "maven library, group org.acme"), ("acme-deploy-plugin", "maven build plugin, group org.acme"), ("server-alpha", "maven build profile")],
        ),
        ("build.gradle", "build", "gradle", GRADLE, [("acme-store-driver", "gradle library, group org.acme"), ("acme-queue-client", "gradle library, group org.acme")]),
        (
            "package.json",
            "dependency",
            "javascript",
            json.dumps({"dependencies": {"alpha-client": "^1"}, "devDependencies": {"beta-tool": "^2"}}),
            [("alpha-client", "npm library")],
        ),
        (
            "requirements.txt",
            "dependency",
            "python",
            "# pinned\nalpha-client==1.2\nbeta[extra]>=2 ; python_version>'3'\n-r other.txt\n",
            [("alpha-client", "python library"), ("beta", "python library")],
        ),
        ("pyproject.toml", "dependency", "python", '[project]\ndependencies = ["alpha-client>=1", "beta"]\n', [("alpha-client", "python library"), ("beta", "python library")]),
        ("setup.py", "dependency", "python", 'setup(install_requires=["alpha-client>=1", "beta"])', [("alpha-client", "python library"), ("beta", "python library")]),
        # Extras hold a "]" inside the list; the requirements after them still count
        ("setup.py", "dependency", "python", 'setup(install_requires=["alpha-client[extra]>=1", "beta"])', [("alpha-client", "python library"), ("beta", "python library")]),
        (
            "go.mod",
            "dependency",
            "golang",
            "module example.org/app\nrequire example.org/alpha v1.0.0\nrequire (\n\texample.org/beta v2.0.0\n)\n",
            [("example.org/alpha", "go module"), ("example.org/beta", "go module")],
        ),
        ("composer.json", "dependency", "php", json.dumps({"require": {"php": ">=8", "ext-json": "*", "acme/alpha": "^1"}}), [("acme/alpha", "php library")]),
        ("Gemfile", "dependency", "ruby", "source 'https://rubygems.org'\ngem 'alpha-client'\ngem \"beta\", '~> 2'\n", [("alpha-client", "ruby gem"), ("beta", "ruby gem")]),
        (
            "Cargo.toml",
            "dependency",
            "rust",
            '[package]\nname = "app"\n[dependencies]\nalpha = "1"\nbeta = { version = "2" }\n[dev-dependencies]\ngamma = "1"\n',
            [("alpha", "rust crate"), ("beta", "rust crate")],
        ),
        (
            "Dockerfile",
            "infra",
            "docker",
            "FROM acme/base:1 AS build\nRUN make\nFROM build\nFROM acme/runtime:2\n",
            [("acme/base:1", "container image"), ("acme/runtime:2", "container image")],
        ),
        (
            "docker-compose.yml",
            "infra",
            "docker-compose",
            COMPOSE,
            [("queue", "compose service, image acme/queue:3, environment QUEUE_PASSWORD QUEUE_USER"), ("web", "compose service, built from the repository")],
        ),
        ("k8s/deploy.yaml", "infra", "kubernetes", K8S, [("acme/api:4", "container image")]),
        (".env", "config", "env", "ALPHA_URL=http://alpha\n# comment\nexport BETA_TOKEN=secret\n", [("ALPHA_URL", "environment variable"), ("BETA_TOKEN", "environment variable")]),
        ("README.txt", "docs", "text", "anything", []),
    ],
)
def test_the_items_a_file_declares(path, file_type, subtype, content, expected):
    assert tc.items_from_file(path, content, file_type, subtype) == expected


def test_a_config_file_of_a_container_subtype_is_not_a_container_file():
    assert tc.items_from_file(".dockerignore", "FROM acme/base:1\n", "config", "docker") == []


def test_unparsable_files_declare_nothing():
    assert tc.items_from_file("pom.xml", "<project>", "build", "maven") == []
    assert tc.items_from_file("package.json", "{", "dependency", "javascript") == []
    assert tc.items_from_file("docker-compose.yml", "services: [", "infra", "docker-compose") == []


PLATFORMS = [
    {"file_type": "dependency", "subtype": "javascript", "name": "Runtime Js", "category": "platform"},
    {"file_type": "infra", "subtype": "docker-compose", "name": "Container Platform", "category": "infrastructure"},
]


def _file(path, content, file_type="dependency", subtype="javascript"):
    return {"path": path, "file_type": file_type, "subtype": subtype, "content": content}


def _package(*names):
    return json.dumps({"dependencies": dict.fromkeys(names, "1")})


class TestCollect:
    def test_an_item_is_collected_once_with_every_file_that_declares_it(self):
        collected = tc.collect([_file("a/package.json", _package("alpha-client")), _file("b/package.json", _package("alpha-client"))], PLATFORMS)

        assert list(collected.items) == ["npm library::alpha-client"]
        assert collected.declared["npm library::alpha-client"] == {"a/package.json", "b/package.json"}

    def test_file_types_imply_the_configured_platforms(self):
        collected = tc.collect([_file("package.json", _package()), _file("docker-compose.yml", "services: {}", "infra", "docker-compose")], PLATFORMS)

        assert collected.platforms == {("Runtime Js", "platform"): {"package.json"}, ("Container Platform", "infrastructure"): {"docker-compose.yml"}}


class TestPromptAndLabels:
    BATCH = [
        tc.TechnologyItem("npm library::alpha-client", "alpha-client", "npm library"),
        tc.TechnologyItem("compose service::queue", "queue", "compose service, image acme/queue:3"),
    ]

    def test_the_prompt_lists_every_item_with_its_kind(self):
        prompt = tc.build_classification_prompt("Classify every item.", self.BATCH)

        assert prompt == 'Classify every item.\n\nItems:\n1. "alpha-client" (npm library)\n2. "queue" (compose service, image acme/queue:3)\n'

    def test_an_answer_names_an_item_by_its_text_or_its_whole_line(self):
        content = json.dumps(
            {
                "items": [
                    {"item": "Alpha-Client", "category": "none", "system": ""},
                    {"item": '"queue" (compose service, image acme/queue:3)', "category": "system_software", "system": "Queue Broker"},
                ]
            }
        )

        labels, issues = tc.parse_labels(content, self.BATCH)

        assert labels == {
            "npm library::alpha-client": {"category": "none", "system": ""},
            "compose service::queue": {"category": "system_software", "system": "Queue Broker"},
        }
        assert issues == {"unmatched": [], "duplicates": [], "missing": []}

    def test_answer_issues_are_reported(self):
        content = json.dumps(
            {
                "items": [
                    {"item": "alpha-client", "category": "none", "system": ""},
                    {"item": "alpha-client", "category": "service", "system": "Other"},
                    {"item": "unknown", "category": "none", "system": ""},
                ]
            }
        )

        labels, issues = tc.parse_labels(content, self.BATCH)

        assert labels == {"npm library::alpha-client": {"category": "none", "system": ""}}
        assert issues == {"unmatched": ["unknown"], "duplicates": ["alpha-client"], "missing": ["queue"]}

    def test_an_unknown_category_is_an_error(self):
        with pytest.raises(ValueError):
            tc.parse_labels(json.dumps({"items": [{"item": "alpha-client", "category": "framework", "system": ""}]}), self.BATCH)


class TestNodesAndEdges:
    FILES = [_file("a/package.json", _package("alpha-client", "gamma")), _file("b/package.json", _package("beta-client"))]
    LABELS = {
        "npm library::alpha-client": {"category": "system_software", "system": "Store Alpha"},
        "npm library::beta-client": {"category": "service", "system": "Store Alpha"},
        "npm library::gamma": {"category": "none", "system": ""},
    }

    def _run(self, existing=None):
        collected = tc.collect(self.FILES, PLATFORMS)
        return tc.technology_nodes_and_edges(self.LABELS, collected, "r", confidence=0.9, existing=existing or {})

    def test_a_node_per_platform_and_per_named_system(self):
        nodes, _ = self._run()

        by_id = {n["node_id"]: n["properties"] for n in nodes}
        assert set(by_id) == {"tech::r::runtimejs", "tech::r::storealpha"}
        store = by_id["tech::r::storealpha"]
        # Category: most frequent answer, ties by name; confidence from params; no description or version
        assert (store["techName"], store["techCategory"], store["confidence"], store["description"], store["version"]) == ("Store Alpha", "service", 0.9, "", None)
        assert store["originSource"] == "a/package.json"
        assert by_id["tech::r::runtimejs"]["techCategory"] == "platform"
        # A platform comes from structure alone; a system from an LLM label
        assert {n["node_id"]: n["method"] for n in nodes} == {"tech::r::runtimejs": "structural", "tech::r::storealpha": "llm"}

    def test_a_technology_id_is_the_canonical_name_key(self):
        assert tc.technology_node_id("r", "Store Alpha") == tc.technology_node_id("r", "store_alpha") == "tech::r::storealpha"

    def test_every_declaring_file_configures_its_system_and_platform(self):
        _, edges = self._run()

        pairs = sorted((e["from_node_id"], e["to_node_id"], e["properties"]["route"]) for e in edges)
        a, b = generate_file_node_id("r", "a/package.json"), generate_file_node_id("r", "b/package.json")
        assert pairs == [
            (a, "tech::r::runtimejs", "structural"),
            (a, "tech::r::storealpha", "llm"),
            (b, "tech::r::runtimejs", "structural"),
            (b, "tech::r::storealpha", "llm"),
        ]
        assert {e["relationship_type"] for e in edges} == {"CONFIGURES"}

    def test_a_system_that_exists_before_the_step_gets_edges_but_no_new_node(self):
        nodes, edges = self._run(existing={"storealpha": "tech::r::store_alpha"})

        assert "tech::r::storealpha" not in {n["node_id"] for n in nodes}
        assert {e["to_node_id"] for e in edges if e["properties"]["route"] == "llm"} == {"tech::r::store_alpha"}
