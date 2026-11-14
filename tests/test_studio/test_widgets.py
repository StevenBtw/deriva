"""The widgets' front-end code, served from the installed packages."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("name", ["anywidget-graph", "anywidget-archimate"])
def test_widget_module_and_styles_are_served(client, name):
    js = client.get(f"/widgets/{name}/index.js")
    css = client.get(f"/widgets/{name}/styles.css")

    assert js.status_code == 200
    assert js.headers["content-type"].startswith("text/javascript")
    assert "render" in js.text
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")


@pytest.mark.parametrize(
    ("name", "traits"),
    [("anywidget-graph", ["show_layout_menu", "show_view_toggle"]), ("anywidget-archimate", ["show_details"])],
)
def test_the_served_widgets_read_the_traits_the_studio_sets(client, name, traits):
    # The studio hides these controls itself; a widget build that ignores the traits would show them again
    js = client.get(f"/widgets/{name}/index.js").text

    for trait in traits:
        assert trait in js, f"{name} does not read {trait}"


def test_unknown_widget_is_404(client):
    assert client.get("/widgets/other/index.js").status_code == 404
