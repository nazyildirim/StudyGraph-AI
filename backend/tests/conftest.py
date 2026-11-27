"""Shared pytest configuration.

Contains no autouse fixtures so existing stateless tests remain unaffected.
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "postgres: integration tests requiring a verified local PostgreSQL test database",
    )
