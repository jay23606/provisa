# Copyright (c) 2026 Kenneth Stott
# Canary: 4d5379c8-6687-494a-9b74-3f90c624f24c
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""No requirement id is user-facing.

A requirement id (``REQ-1234``) belongs to the people who build the product. It must not be in
anything a user of the product can read: a refusal, an error, a catalog string. Whether an
exception's text reaches a user cannot be told from the text -- a caller may put ``str(exc)``
in a refusal, an API error, a wire error or a replica's last error -- so the rule is over
every string literal of the product outside a log call and a docstring, and over every string
of every UI catalog. Comments, docstrings and log lines keep theirs.

A literal that IS an id and nothing else is a reference, not a message (a setting's
requirement, the requirements tooling's own data).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
ID = re.compile(r"REQ-[A-Z]*\d+")
ONLY_AN_ID = re.compile(r"^REQ-[A-Z]*\d+$")
_LOG_CALLS = {"debug", "info", "warning", "error", "exception", "critical", "log"}


def _docstrings(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.add(id(first.value))
    return found


def _in_log_call(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    while id(node) in parents:
        node = parents[id(node)]
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name in _LOG_CALLS:
                return True
        if isinstance(node, ast.stmt):
            return False
    return False


def literals_with_an_id(path: Path) -> list[tuple[int, str]]:
    """(line, text) of each string literal of ``path`` that holds a requirement id and could be
    read by a user."""
    tree = ast.parse(path.read_text())
    docstrings = _docstrings(tree)
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        text = node.value
        if not ID.search(text) or ONLY_AN_ID.match(text.strip()) or id(node) in docstrings:
            continue
        if _in_log_call(node, parents):
            continue
        found.append((node.lineno, text))
    return found


def _product_files() -> list[Path]:
    return sorted((REPO / "provisa").rglob("*.py"))


def test_no_message_of_the_product_names_a_requirement():
    offending = []
    for path in _product_files():
        name = str(path.relative_to(REPO))
        offending += [f"{name}:{line}: {text[:90]!r}" for line, text in literals_with_an_id(path)]
    assert not offending, "a requirement id in a string a user could read:\n" + "\n".join(offending)


def _strings(value: object, at: str = ""):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield from _strings(inner, f"{at}.{key}" if at else key)
    elif isinstance(value, str):
        yield at, value


def test_no_catalog_string_names_a_requirement():
    catalogs = sorted(
        p
        for p in (REPO / "provisa-ui/src/i18n/locales").rglob("*.json")
        if not p.name.startswith(".")
    )
    assert len(catalogs) > 13
    offending = [
        f"{path.relative_to(REPO)}: {key}"
        for path in catalogs
        for key, text in _strings(json.loads(path.read_text()))
        if ID.search(text)
    ]
    assert not offending, "a requirement id in a UI string:\n" + "\n".join(offending)


def test_a_bare_id_and_a_log_line_are_not_messages(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        '"""Module docstring naming REQ-1."""\n'
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        'SETTING_REQUIREMENT = "REQ-55"\n'
        "def f():\n"
        '    log.warning("fell back (REQ-2): %s", 1)\n'
        '    raise ValueError("no primary key (REQ-3)")\n'
    )
    assert literals_with_an_id(sample) == [(7, "no primary key (REQ-3)")]
