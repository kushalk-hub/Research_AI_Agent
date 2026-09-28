"""P7 CLI gate: `rla tui` starts the app on the pipeline's event stream.

The real terminal is not testable, so the app's `run()` is replaced with a
capture. What matters for the gate is that the command is wired to the same
`Pipeline.run` stream as `rla run` and hands it to `RlaApp`; driving the app
itself is `test_p7_tui_app.py`.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from rla.cli import app
from rla.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        gemini_api_key="",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        figures_dir=tmp_path / "figures",
        cache_db=tmp_path / "cache.db",
    )


@pytest.fixture
def runner(monkeypatch, settings):
    monkeypatch.setattr("rla.cli.get_settings", lambda: settings)
    return CliRunner()


def test_tui_passes_the_pipeline_stream_to_the_app(runner, monkeypatch, settings):
    """The app must receive the generator, not a list, or nothing is live."""
    import rla.cli as cli

    seen: dict[str, object] = {}

    class FakeApp:
        def __init__(self, state, events):
            seen["state"] = state
            seen["events"] = events

        def run(self):
            seen["ran"] = True

    class FakePipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, title, question, result):
            async def _gen():
                from rla.events import Phase, event

                yield event(Phase.SEARCH, "searching")

            return _gen()

    monkeypatch.setattr(cli, "RlaApp", FakeApp, raising=False)
    monkeypatch.setattr(cli, "Pipeline", FakePipeline)

    # Import is inside the command, so patch the source module too.
    import rla.tui.app as tui_app

    monkeypatch.setattr(tui_app, "RlaApp", FakeApp)

    result = runner.invoke(app, ["tui", "--title", "graph RL"])

    assert result.exit_code == 0, result.output
    assert seen.get("ran") is True
    assert "graph RL" in getattr(seen["state"], "title", "")
    assert hasattr(seen["events"], "__aiter__"), "the app needs an async iterator"
    settings.cache_db.parent.mkdir(parents=True, exist_ok=True)


def test_tui_warns_when_no_api_key_is_configured(runner, monkeypatch):
    import rla.tui.app as tui_app

    class FakeApp:
        def __init__(self, state, events):
            pass

        def run(self):
            pass

    monkeypatch.setattr(tui_app, "RlaApp", FakeApp)

    result = runner.invoke(app, ["tui", "--title", "graph RL"])

    assert result.exit_code == 0, result.output
    assert "GEMINI_API_KEY" in result.output


def test_tui_is_not_still_a_placeholder(runner):
    """A command left unbuilt would print 'not implemented' and exit 0."""
    result = runner.invoke(app, ["tui", "--help"])
    assert result.exit_code == 0
    assert "not implemented" not in result.output
    assert "live terminal UI" in result.output


def test_run_still_streams_events(runner, monkeypatch, settings):
    """The headless path must keep working alongside the TUI."""
    import rla.cli as cli

    class FakePipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, title, question, result):
            from rla.events import Phase, event

            async def _gen():
                yield event(Phase.SEARCH, "searching")
                yield event(Phase.DONE, "Pipeline finished", kind="ok")

            return _gen()

    monkeypatch.setattr(cli, "Pipeline", FakePipeline)

    result = runner.invoke(app, ["run", "--title", "graph RL", "--jsonl"])

    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.strip().startswith("{")]
    assert len(lines) == 2
    assert json.loads(lines[-1])["phase"] == "done"
