import os

# Set before main.py is imported. Fake values: tests never reach Sarvam.
os.environ["APP_PASSWORD"] = "test-password"
os.environ["SARVAM_API_KEY"] = "sk_test_not_a_real_key"

import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Every test gets its own empty database file, never the real one."""
    import store
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "returns.db"))
