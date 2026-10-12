"""What this installation is: home folder, workspace, version, optional features."""

from __future__ import annotations

import platform
from importlib.metadata import version

from deriva.services import about


def test_version_is_the_installed_distribution_version():
    assert about.version() == version(about.DISTRIBUTION)


def test_environment_reports_the_os_and_python_version():
    environment = about.environment()

    assert environment["python"] == platform.python_version()
    assert environment["os"] in {"Windows", "macOS", "Linux", platform.system()}
