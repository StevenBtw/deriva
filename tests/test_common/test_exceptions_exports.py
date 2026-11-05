"""The run and configuration exceptions are part of the module's exports."""

from deriva.common import exceptions


def test_the_new_exceptions_are_exported():
    assert {"NoModelConfigured", "RunStopped"} <= set(exceptions.__all__)
