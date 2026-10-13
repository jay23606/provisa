#!/usr/bin/env python3
# Copyright (c) 2026 Kenneth Stott
# Canary: 5b1e7c94-2d3f-4a86-9c07-e4f8a1d6b320
#
# This source code is licensed under the Business Source License 1.1
"""The feature layer above the requirements (docs/arch/features.yaml).

A feature is what a customer can do, told in a few short paragraphs, one concept each. Each
requirement's ``feature`` names the one paragraph it serves, so a paragraph's requirements are its
trace. A paragraph's id is also its anchor in docs/features.md, so it is kebab case: in attr_list
a dot would start a class.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, field_validator, model_validator

FEATURES_YAML = Path("docs/arch/features.yaml")
_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class Visibility(str, Enum):
    feature = "feature"  # perceived by users
    quality = "quality"  # non-functional, customer-facing
    internal = "internal"  # never in a published document or release asset


class Audience(str, Enum):
    consumer = "consumer"
    modeler = "modeler"
    admin = "admin"
    operator = "operator"


class Paragraph(BaseModel):
    id: str
    text: str

    @field_validator("id")
    @classmethod
    def kebab(cls, v: str) -> str:
        if not _KEBAB.match(v):
            raise ValueError(f"paragraph id must be kebab case, got {v!r}")
        return v


class Feature(BaseModel):
    id: str
    name: str
    section: str
    visibility: Visibility
    audience: Optional[Audience] = None
    paragraphs: list[Paragraph]

    @field_validator("id")
    @classmethod
    def kebab(cls, v: str) -> str:
        if not _KEBAB.match(v):
            raise ValueError(f"feature id must be kebab case, got {v!r}")
        return v

    @model_validator(mode="after")
    def shape(self) -> Feature:
        if (self.visibility == Visibility.internal) != (self.audience is None):
            raise ValueError(f"{self.id}: an internal feature has no audience; any other has one")
        if not self.paragraphs:
            raise ValueError(f"{self.id}: a feature has at least one paragraph")
        for p in self.paragraphs:
            if not p.id.startswith(f"{self.id}-"):
                raise ValueError(f"{self.id}: paragraph id {p.id!r} must start with '{self.id}-'")
        return self

    @property
    def published(self) -> bool:
        return self.visibility != Visibility.internal


class FeaturesFile(BaseModel):
    features: list[Feature]

    @model_validator(mode="after")
    def unique_ids(self) -> FeaturesFile:
        seen: set[str] = set()
        for f in self.features:
            for i in (f.id, *(p.id for p in f.paragraphs)):
                if i in seen:
                    raise ValueError(f"duplicate feature or paragraph id: {i!r}")
                seen.add(i)
        return self

    @classmethod
    def load(cls, path: Path = FEATURES_YAML) -> FeaturesFile:
        return cls(features=yaml.safe_load(path.read_text()))

    def paragraph_owner(self) -> dict[str, Feature]:
        """Each paragraph id -> the feature it belongs to."""
        return {p.id: f for f in self.features for p in f.paragraphs}


#: Requirement statuses that leave a feature still in development.
_OPEN = frozenset({"proposed", "accepted", "in-progress"})


def feature_status(paragraph_ids: set[str], requirements: list) -> str:
    """A feature is Available when none of the requirements its paragraphs carry is still open,
    else In development."""
    open_ = any(r.feature in paragraph_ids and r.status.value in _OPEN for r in requirements)
    return "In development" if open_ else "Available"
