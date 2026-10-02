"""P12 Task 6 (CLI side): `rla tui` wires the provider router into the TUI.

Agent C owns `src/rla/tui/*` (`RlaApp`'s `router`/`available_models` params and
`tui.connect_router`); this module owns the `cli.tui` half. The wiring must
therefore work both before and after that side lands: the locked names are
used when present and skipped gracefully when absent. Everything here runs
against fakes -- no live server, no model, no terminal.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from rla.cli import _tui_available_models, app
from rla.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        structured_model="ollama/qwen3:4b",
        answer_model="gemini/gemini-2.5-flash",
    )


@pytest.fixture
def runner(monkeypatch, settings):
    monkeypatch.setattr("rla.cli.get_settings", lambda: settings)
    return CliRunner()


class FakeRouter:
    """Stands in for ProviderRouter: only the observer slot matters here."""

    def __init__(self):
        self.on_fallback = None


class FakePipeline:
    def run(self, title, question, result):
        async def _gen():
            return
            yield  # pragma: no cover - never iterated, only handed over

        return _gen()


class FakeCache:
    def close(self):
        pass


class FakeState:
    """Stands in for a routing-aware PipelineState (has `role_models`)."""

    created: list[FakeState] = []

    def __init__(self, title="", question="", **kw):
        self.title = title
        self.question = question
        self.role_models: dict[str, str] = {}
        FakeState.created.append(self)


@pytest.fixture
def fake_build(monkeypatch):
    """Point `cli.tui` at fakes; return the router it will receive."""
    import rla.cli as cli

    router = FakeRouter()

    def _build(settings):
        return FakePipeline(), FakeCache(), object(), router

    monkeypatch.setattr(cli, "_build_pipeline", _build)
    monkeypatch.setattr("rla.tui.state.PipelineState", FakeState)
    FakeState.created.clear()
    return router


@pytest.fixture
def hooked_tui(monkeypatch):
    """Install a fake `connect_router` on the `rla.tui` package; record calls."""
    calls: list[tuple] = []

    def _hook(state, router):
        calls.append((state, router))

    monkeypatch.setattr("rla.tui.connect_router", _hook, raising=False)
    return calls


def _new_style_app(seen):
    class FakeApp:
        def __init__(self, state, events, available_models=(), router=None):
            seen["state"] = state
            seen["events"] = events
            seen["available_models"] = available_models
            seen["router"] = router
            seen["kwargs"] = {
                "available_models": available_models,
                "router": router,
            }

        def run(self):
            seen["ran"] = True

    return FakeApp


# -- available models ----------------------------------------------------------


def test_available_models_lists_roles_then_fallbacks_deduplicated(settings):
    assert _tui_available_models(settings) == (
        "ollama/qwen3:4b",
        "gemini/gemini-2.5-flash",
    )


def test_available_models_canonicalises_bare_ids(tmp_path):
    s = Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        structured_model="ollama/qwen3:4b",
        answer_model="gemini-2.5-flash",
        fallback_models="openrouter/llama-3:free, gemini-2.5-flash",
    )
    assert _tui_available_models(s) == (
        "ollama/qwen3:4b",
        "gemini/gemini-2.5-flash",
        "openrouter/llama-3:free",
    )


# -- cli wiring ----------------------------------------------------------------


def test_tui_seeds_role_models_from_settings(runner, monkeypatch, fake_build, hooked_tui):
    import rla.tui.app as tui_app

    seen: dict = {}
    monkeypatch.setattr(tui_app, "RlaApp", _new_style_app(seen))

    result = runner.invoke(app, ["tui", "--title", "T"])
    assert result.exit_code == 0, result.output
    (state,) = FakeState.created
    assert state.role_models == {
        "structured": "ollama/qwen3:4b",
        "answer": "gemini/gemini-2.5-flash",
    }


def test_tui_seeds_role_models_after_cli_overrides(runner, monkeypatch, fake_build, hooked_tui):
    import rla.tui.app as tui_app

    seen: dict = {}
    monkeypatch.setattr(tui_app, "RlaApp", _new_style_app(seen))

    result = runner.invoke(
        app, ["tui", "--title", "T", "--structured-model", "gemini-2.5-flash"]
    )
    assert result.exit_code == 0, result.output
    (state,) = FakeState.created
    assert state.role_models["structured"] == "gemini/gemini-2.5-flash"


def test_tui_passes_router_and_available_models_to_app(
    runner, monkeypatch, fake_build, hooked_tui
):
    import rla.tui.app as tui_app

    seen: dict = {}
    monkeypatch.setattr(tui_app, "RlaApp", _new_style_app(seen))

    result = runner.invoke(app, ["tui", "--title", "T"])
    assert result.exit_code == 0, result.output
    assert seen.get("ran") is True
    assert seen["router"] is fake_build
    assert seen["available_models"] == (
        "ollama/qwen3:4b",
        "gemini/gemini-2.5-flash",
    )
    assert hasattr(seen["events"], "__aiter__"), "the app needs an async iterator"


def test_tui_registers_the_fallback_observer(runner, monkeypatch, fake_build, hooked_tui):
    import rla.tui.app as tui_app

    seen: dict = {}
    monkeypatch.setattr(tui_app, "RlaApp", _new_style_app(seen))

    result = runner.invoke(app, ["tui", "--title", "T"])
    assert result.exit_code == 0, result.output
    (state,) = FakeState.created
    assert hooked_tui == [(state, fake_build)]


def test_tui_skips_all_wiring_when_router_is_none(runner, monkeypatch, hooked_tui):
    """Degrade mode: no router means no seeding, no app kwargs, no observer."""
    import rla.cli as cli
    import rla.tui.app as tui_app

    def _build(settings):
        return FakePipeline(), FakeCache(), object(), None

    monkeypatch.setattr(cli, "_build_pipeline", _build)
    monkeypatch.setattr("rla.tui.state.PipelineState", FakeState)
    FakeState.created.clear()

    seen: dict = {}
    monkeypatch.setattr(tui_app, "RlaApp", _new_style_app(seen))

    result = runner.invoke(app, ["tui", "--title", "T"])
    assert result.exit_code == 0, result.output
    (state,) = FakeState.created
    assert state.role_models == {}
    assert seen["router"] is None
    assert seen["available_models"] == ()
    assert hooked_tui == []


def test_tui_runs_when_the_tui_side_has_no_routing_names(runner, monkeypatch, settings):
    """Back-compat: old `RlaApp(state, events)` and no `connect_router` still run.

    Uses the real (routing-unaware) `PipelineState` and an old-signature app,
    proving the wiring degrades instead of raising TypeError/AttributeError.
    """
    import rla.cli as cli
    import rla.tui as tui_pkg
    import rla.tui.app as tui_app

    # Simulate the pre-C `rla.tui.app`: the integrated tree HAS `connect_router`,
    # so hide it for this test and exercise the CLI's getattr-based degrade path.
    monkeypatch.delattr(tui_pkg, "connect_router", raising=False)
    monkeypatch.delattr(tui_app, "connect_router", raising=False)

    router = FakeRouter()
    monkeypatch.setattr(
        cli, "_build_pipeline", lambda s: (FakePipeline(), FakeCache(), object(), router)
    )

    seen: dict = {}

    class OldApp:
        def __init__(self, state, events):
            seen["state"] = state
            seen["events"] = events

        def run(self):
            seen["ran"] = True

    monkeypatch.setattr(tui_app, "RlaApp", OldApp)

    result = runner.invoke(app, ["tui", "--title", "T"])
    assert result.exit_code == 0, result.output
    assert seen.get("ran") is True
    assert getattr(seen["state"], "title", "") == "T"
