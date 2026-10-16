"""The closed list of technologies: an image, base image, dependency, platform or cloud resource names one canonical system software."""

from __future__ import annotations

from deriva.modules.extraction.technologies import Technology, catalog_from_params, image_name, match_technology

CATALOG = (
    Technology(name="PostgreSQL", kind="database", aliases=("postgres", "postgresql", "bitnami/postgresql", "psycopg2", "asyncpg")),
    Technology(name="Java runtime", kind="runtime", aliases=("openjdk", "eclipse-temurin", "amazoncorretto")),
    Technology(name="Amazon S3", kind="managed service", aliases=("aws::s3::bucket",)),
)


def test_an_image_is_known_by_its_last_path_segment_without_registry_or_tag():
    assert image_name("public.ecr.aws/docker/library/python:3.12-slim") == "python"
    assert image_name("postgres:15-alpine") == "postgres"
    assert image_name("docker.io/bitnami/postgresql@sha256:abc") == "bitnami/postgresql"
    assert image_name("eclipse-temurin:21-jre AS runtime") == "eclipse-temurin"


def test_aliases_name_one_canonical_technology_and_unknown_names_fall_back():
    assert match_technology("postgres", CATALOG).name == "PostgreSQL"
    assert match_technology("PSYCOPG2", CATALOG).name == "PostgreSQL"  # a client library: use of the database
    assert match_technology("bitnami/postgresql", CATALOG).name == "PostgreSQL"
    assert match_technology("AWS::S3::Bucket", CATALOG).kind == "managed service"
    assert match_technology("my-custom-db", CATALOG) is None


def test_the_catalog_is_read_from_the_step_params():
    catalog = catalog_from_params([{"name": "Redis", "kind": "cache", "aliases": ["redis", "redis-py"]}])

    assert catalog == (Technology(name="Redis", kind="cache", aliases=("redis", "redis-py")),)
