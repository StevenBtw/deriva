"""The docs site (docs.deriva.dev): built with Zensical from docs/, published by .github/workflows/docs.yml."""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def config() -> dict:
    return tomllib.loads((ROOT / "zensical.toml").read_text(encoding="utf-8"))["project"]


def nav_files(nav) -> list[str]:
    """Every Markdown file the nav names, in order (nested sections included)."""
    files = []
    for entry in nav:
        values = entry.values() if isinstance(entry, dict) else [entry]
        for value in values:
            files.extend(nav_files(value) if isinstance(value, list) else [value])
    return files


def test_every_docs_page_is_in_the_nav():
    pages = {p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md")}
    assert pages == set(nav_files(config()["nav"]))


def test_the_published_urls_stay():
    files = nav_files(config()["nav"])
    for page in ("index.md", "archimate.md", "benchmarks.md", "optimization.md", "architecture.md"):
        assert page in files
    assert config().get("use_directory_urls", True) is True


def test_the_site_is_docs_deriva_dev():
    assert config()["site_url"] == "https://docs.deriva.dev/"


def test_the_footer_has_no_made_with_line():
    assert config()["extra"]["generator"] is False


def test_the_look_comes_from_the_generated_template_and_one_own_stylesheet():
    assert config()["extra_css"] == ["stylesheets/extra.css", "stylesheets/deriva.css"]
    for f in ("stylesheets/extra.css", "stylesheets/deriva.css", "assets/logo.svg", "assets/logo-light.svg", "assets/favicon.svg"):
        assert (DOCS / f).is_file(), f
    assert "logo-light.svg" in (DOCS / "stylesheets/deriva.css").read_text(encoding="utf-8")
    assert "<rect" not in (DOCS / "assets/logo.svg").read_text(encoding="utf-8")


def test_docs_hold_only_published_content():
    for path in DOCS.rglob("*"):
        if path.is_file():
            assert path.suffix in {".md", ".css", ".svg", ".png", ".woff2", ".txt"}, path
            assert not any(part.startswith(".") or part == "superpowers" for part in path.relative_to(DOCS).parts), path


def test_docs_pages_have_no_em_or_en_dashes():
    for page in DOCS.rglob("*.md"):
        text = page.read_text(encoding="utf-8")
        assert chr(0x2014) not in text and chr(0x2013) not in text, page  # em and en dash


def test_the_nav_is_the_agreed_tree():
    assert nav_files(config()["nav"]) == [
        "index.md",
        "get-started.md",
        "studio.md",
        "cli.md",
        "configuration.md",
        "data.md",
        "how-tos.md",
        "troubleshooting.md",
        "archimate.md",
        "architecture.md",
        "benchmarks.md",
        "optimization.md",
        "contributing.md",
        "changelog.md",
    ]
    sections = [next(iter(entry)) for entry in config()["nav"]]
    assert sections == ["Overview", "Get started", "Use Deriva", "Understand", "Tune", "Contribute", "Changelog"]


def test_contributing_and_changelog_are_included_not_copied():
    assert (DOCS / "contributing.md").read_text(encoding="utf-8").strip() == '--8<-- "CONTRIBUTING.md"'
    assert (DOCS / "changelog.md").read_text(encoding="utf-8").strip() == '--8<-- "CHANGELOG.md"'


@pytest.mark.parametrize("source", ["CONTRIBUTING.md", "CHANGELOG.md"])
def test_included_files_link_by_web_address(source):
    """The docs include these files whole; a repository-relative link would break on docs.deriva.dev."""
    text = (ROOT / source).read_text(encoding="utf-8")
    relative = [href for href in re.findall(r"\]\(([^)\s]+)\)", text) if not re.match(r"(https?:|mailto:|#)", href)]
    assert relative == [], relative


PACKAGE_READMES = ["packages/README-deriva-cli.md", "packages/deriva-studio/README.md", "packages/deriva-dev/README.md"]


def links_to_the_docs(text: str) -> bool:
    """Whether ``text`` has a link (bare or Markdown) that starts with the docs site's address."""
    return re.search(r"(?:^|[\s(<])https://docs\.deriva\.dev/", text, re.MULTILINE) is not None


def test_readme_keeps_one_install_line_and_points_to_the_docs():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert text.count("uv tool install") == 1
    assert links_to_the_docs(text)
    for moved in ("## Set Up an LLM", "## Configuration", "## CLI (Headless Mode)", "## Troubleshooting"):
        assert moved not in text


@pytest.mark.parametrize("readme", PACKAGE_READMES)
def test_package_readmes_keep_one_install_line_and_point_to_the_docs(readme):
    text = (ROOT / readme).read_text(encoding="utf-8")
    assert text.count("uv tool install") == 1
    assert links_to_the_docs(text)
    assert "constraints.txt" not in text


WORKFLOWS = ROOT / ".github/workflows"
SOURCES = (
    "docs/**",
    "zensical.toml",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "uv.lock",
    ".github/workflows/docs.yml",
)


def test_docs_publish_on_main_and_by_hand():
    wf = (WORKFLOWS / "docs.yml").read_text(encoding="utf-8")
    assert re.search(r"push:\s*\n\s+branches: \[main\]", wf)
    assert "workflow_dispatch" in wf and "tags:" not in wf
    assert "zensical build --strict" in wf


def test_paths_filter_covers_every_source():
    wf = (WORKFLOWS / "docs.yml").read_text(encoding="utf-8")
    for source in SOURCES:
        assert f'"{source}"' in wf, source


def test_docs_actions_are_pinned_by_commit():
    wf = (WORKFLOWS / "docs.yml").read_text(encoding="utf-8")
    uses = re.findall(r"uses: (\S+)", wf)
    assert uses and all(re.search(r"@[0-9a-f]{40}$", u) for u in uses), uses


def test_pull_requests_build_the_docs_strictly():
    assert "zensical build --strict" in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def test_editing_a_prompt_in_the_studio_has_one_home():
    pages = sorted(p.name for p in DOCS.rglob("*.md") if "Save as new version" in p.read_text(encoding="utf-8"))
    assert pages == ["how-tos.md"]


def test_the_light_logo_swap_works_in_every_browser():
    """`content: url()` on an <img> is not supported everywhere; the light mark is a background instead."""
    css = (DOCS / "stylesheets/deriva.css").read_text(encoding="utf-8")
    assert "content: url(" not in css
    assert 'background-image: url("../assets/logo-light.svg")' in css


def test_fonts_are_self_hosted():
    """docs.deriva.dev loads nothing from Google Fonts: the theme loads no font, extra.css serves them."""
    theme = config()["theme"]
    assert theme.get("font") is False
    css = (DOCS / "stylesheets/extra.css").read_text(encoding="utf-8")
    assert "fonts.googleapis" not in css
    refs = re.findall(r'url\("fonts/([^"]+)"\)', css)
    assert refs, "extra.css serves the fonts itself"
    for ref in refs:
        assert (DOCS / "stylesheets/fonts" / ref).is_file(), ref
    assert any((DOCS / "stylesheets/fonts").glob("OFL-*.txt")), "font licences ship with the fonts"
