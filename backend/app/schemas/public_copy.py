from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel


PublicDestinationSourceKind = Literal[
    "internal_link_intent",
    "draft_related_page",
]


class PublicDestinationCopy(SQLModel):
    """Revision-owned customer copy for one exact related-page destination."""

    source_kind: PublicDestinationSourceKind
    source_record_id: int = Field(gt=0)
    target_planned_page_id: int = Field(gt=0)
    target_generated_page_id: int = Field(gt=0)
    label: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    description: str = Field(min_length=1)
    ruleset_key: str = Field(min_length=1)
    ruleset_version: str = Field(min_length=1)
    ruleset_hash: str = Field(min_length=64, max_length=64)
