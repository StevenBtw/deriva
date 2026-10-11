"""What this installation is: home folder, workspace, version, optional features."""

from __future__ import annotations

from importlib.metadata import version

from deriva.services import about


def test_version_is_the_installed_distribution_version():
    assert about.version() == version(about.DISTRIBUTION)
