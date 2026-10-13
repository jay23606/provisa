# Copyright (c) 2026 Kenneth Stott
#
# This source code is licensed under the Business Source License 1.1
"""REQ-2010: a named demo's own tour names only what the demo has. Every step's target is an
object of the demo's config or one of its example queries, every page it opens is one the step's
capability opens, and every step has its words in every language the UI speaks."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import sqlglot
import yaml

from provisa.core import demo

_REPO = Path(__file__).resolve().parents[2]
_NAMED = _REPO / "demo" / "named"
_LOCALES = _REPO / "provisa-ui" / "src" / "i18n" / "locales"
_TARGETS = ("source", "relationship", "example", "sql", "term", "role")

TOURS = sorted(_NAMED.glob("*/tour.yaml"))


def _route_capabilities() -> dict[str, str]:
    """path -> the capability its <Route> gate in App.tsx names (as tourRouteCapabilities.test.ts
    reads it for the product tour)."""
    source = (_REPO / "provisa-ui" / "src" / "App.tsx").read_text()
    out: dict[str, str] = {}
    for block in source.split("path=")[1:]:
        path = re.match(r'"([^"]+)"', block)
        cap = re.search(r'capability=\{?"([a-z_]+)"', block)
        if path and cap:
            out[path.group(1)] = cap.group(1)
    # The Admin surfaces are a `[path, capability]` table rather than JSX routes.
    for m in re.finditer(r'\["(/admin/[^"]+)",\s*"([a-z_]+)"\]', source):
        out[m.group(1)] = m.group(2)
    return out


def _relations(config: dict) -> set[str]:
    """The ``"domain"."name"`` each table and view of the demo is read by in SQL."""
    from provisa.core.config_loader import views_as_tables

    tables = views_as_tables(json.loads(json.dumps(config)))["tables"]
    return {f"{t['domain_id']}.{t.get('alias') or t['table']}" for t in tables}


def test_there_is_a_demo_tour_to_check():
    assert [p.parent.name for p in TOURS] == ["weblogs"]


@pytest.mark.parametrize("path", TOURS, ids=[p.parent.name for p in TOURS])
def test_every_step_names_what_the_demo_has(path):
    home = path.parent
    config = yaml.safe_load((home / "config.yaml").read_text())
    steps = yaml.safe_load(path.read_text())["steps"]
    sources = {s["id"] for s in config["sources"]}
    aliases = {r["alias"] for r in config["relationships"] if r.get("alias")}
    examples = {q.stem for q in (home / "queries").glob("*.graphql")}
    roles = {r["id"] for r in config["roles"]} | {"all"}
    terms = {t["name"] for t in config.get("glossary_terms", [])}
    relations = _relations(config)
    gates = _route_capabilities()
    keys = [s["key"] for s in steps]
    assert len(keys) == len(set(keys)), keys
    assert "route" in steps[0], "the first step names the page the tour opens on"
    page = None
    for step in steps:
        page = step.get("route", page)
        named = [k for k in _TARGETS if k in step]
        assert len(named) == 1, f"{step['key']}: names {named}, not one target"
        assert set(step) <= {"key", "route", "capability", *_TARGETS}, step
        if "route" in step:
            assert gates.get(step["route"]) == step["capability"], step
        else:
            assert "capability" not in step, step
        if "source" in step:
            assert step["source"] in sources, step
        if "relationship" in step:
            assert step["relationship"] in aliases, step
        if "example" in step:
            assert step["example"] in examples, step
        if "term" in step:
            assert step["term"] in terms, step
        if "role" in step:
            assert step["role"] in roles, step
            # Picked in the SQL explorer's run-as picker, which is on that page alone.
            assert page == "/sql", f"{step['key']}: a role is picked on /sql, not {page}"
        if "sql" in step:
            read = {
                f"{t.db}.{t.name}"
                for t in sqlglot.parse_one(step["sql"], read="postgres").find_all(sqlglot.exp.Table)
            }
            assert read and read <= relations, f"{step['key']}: reads {read - relations}"


@pytest.mark.parametrize("path", TOURS, ids=[p.parent.name for p in TOURS])
def test_every_step_has_its_words_in_every_language(path):
    keys = [s["key"] for s in yaml.safe_load(path.read_text())["steps"]]
    for locale in sorted(p for p in _LOCALES.iterdir() if p.is_dir()):
        words = json.loads((locale / "tour.json").read_text())["tour"]
        for key in keys:
            step = words["steps"].get(key)
            assert step and step["title"] and step["description"], f"{locale.name}: {key}"
        menu = words["demos"][path.parent.name]
        assert menu["title"] and menu["summary"], locale.name


def test_the_setup_status_carries_the_started_demo_s_tour(monkeypatch):
    monkeypatch.setenv(demo.NAMED_DEMO_DIR_ENV, str(_NAMED / "weblogs"))
    steps = demo.demo_tour()
    assert steps[0] == {
        "key": "weblogsSources",
        "route": "/sources",
        "capability": "source_registration",
        "source": "shop_access",
    }


def test_no_named_demo_has_no_tour(tmp_path, monkeypatch):
    monkeypatch.delenv(demo.NAMED_DEMO_DIR_ENV, raising=False)
    assert demo.demo_tour() == []
    monkeypatch.setenv(demo.NAMED_DEMO_DIR_ENV, str(tmp_path))
    assert demo.demo_tour() == []
