import pytest

from govlab.runner import Runner


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Regenerated games normally wait a few seconds before the next attempt."""
    monkeypatch.setattr(Runner, "retry_delay", 0.0)


@pytest.fixture(autouse=True)
def runs_in_tmp(monkeypatch, tmp_path):
    """Nothing a test does may land in the repository's runs/ directory."""
    monkeypatch.setenv("GOVLAB_RUNS", str(tmp_path / "runs"))
