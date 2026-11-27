"""Tests verifying lazy config/database initialization and env-free imports."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from pydantic import ValidationError
import pytest

from app.core.config import ConfigurationError, Settings, get_settings
from app.database import get_db, reset_db_state

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_app_imports_and_health_works_without_env_or_db(tmp_path: Path) -> None:
    """Importing app.main, config, and database must not require .env or DB."""
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(BACKEND_DIR),
    }
    script = (
        "from fastapi.testclient import TestClient\n"
        "import app.core.config as config_module\n"
        "import app.database as db_module\n"
        "from app.main import app as fastapi_app\n"
        "assert db_module._engine is None\n"
        "assert config_module.get_settings.cache_info().currsize == 0\n"
        "client = TestClient(fastapi_app)\n"
        "resp = client.get('/api/v1/health')\n"
        "assert resp.status_code == 200, resp.text\n"
        "assert resp.json() == {'status': 'ok'}\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"Subprocess failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_settings_defaults_and_lazy_required_checks() -> None:
    settings = Settings(_env_file=None)
    assert settings.access_token_expire_minutes == 30
    assert settings.jwt_leeway_seconds == 0
    assert settings.argon2_time_cost == 3
    assert settings.argon2_memory_cost == 65536
    assert settings.argon2_parallelism == 4

    with pytest.raises(ConfigurationError):
        settings.require_database_url()

    with pytest.raises(ConfigurationError):
        settings.require_jwt_secret_key()


def test_settings_empty_strings_treated_as_unset() -> None:
    settings = Settings(_env_file=None, database_url="   ", jwt_secret_key="")
    with pytest.raises(ConfigurationError):
        settings.require_database_url()
    with pytest.raises(ConfigurationError):
        settings.require_jwt_secret_key()


def test_settings_jwt_secret_minimum_32_bytes() -> None:
    short = Settings(_env_file=None, jwt_secret_key="a" * 31)
    with pytest.raises(ConfigurationError):
        short.require_jwt_secret_key()

    exact = Settings(_env_file=None, jwt_secret_key="a" * 32)
    assert exact.require_jwt_secret_key() == "a" * 32


@pytest.mark.parametrize(
    ("kwargs",),
    [
        ({"access_token_expire_minutes": 4},),
        ({"access_token_expire_minutes": 61},),
        ({"jwt_leeway_seconds": -1},),
        ({"jwt_leeway_seconds": 31},),
        ({"argon2_time_cost": 1},),
        ({"argon2_memory_cost": 19455},),
        ({"argon2_parallelism": 0},),
    ],
)
def test_settings_enforces_security_bounds(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


def test_get_db_raises_configuration_error_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    reset_db_state()
    try:
        gen = get_db()
        with pytest.raises(ConfigurationError):
            next(gen)
    finally:
        get_settings.cache_clear()
        reset_db_state()
