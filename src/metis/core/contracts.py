"""P0 contracts. No model/tool execution occurs in this module."""
from __future__ import annotations

from enum import StrEnum
from ipaddress import ip_address
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ChallengeCategory(StrEnum):
    PWN = "pwn"
    REV = "rev"
    WEB = "web"
    CRYPTO = "crypto"
    FORENSICS = "forensics"
    MISC = "misc"


class AllowedEndpoint(BaseModel):
    hostname: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)

    @field_validator("hostname")
    @classmethod
    def validate_host(cls, value: str) -> str:
        if value.strip() != value or any(c in value for c in "/\\@?# "):
            raise ValueError("endpoint must be a host/IP, not a URL")
        if value in {"*", "0.0.0.0", "::"}:
            raise ValueError("wildcard/bind-all address is not permitted")
        return value.lower()


class ScopeGrant(BaseModel):
    granted_by: str = Field(min_length=1)
    challenge_id: str = Field(min_length=1)
    allowed_endpoints: list[AllowedEndpoint] = Field(default_factory=list)
    authorized: Literal[True]

    @model_validator(mode="after")
    def ensure_consistent(self) -> "ScopeGrant":
        return self


class ChallengeManifest(BaseModel):
    schema_version: Literal[1] = 1
    challenge_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_.-]+$")
    title: str = Field(min_length=1)
    description: str
    categories: list[ChallengeCategory] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    scope: ScopeGrant

    @model_validator(mode="after")
    def check_grant(self) -> "ChallengeManifest":
        if self.scope.challenge_id != self.challenge_id:
            raise ValueError("scope grant challenge_id mismatch")
        for p in self.artifacts:
            path = Path(p)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("artifacts must be relative paths without traversal")
        return self


class RunStatus(StrEnum):
    NEW = "new"
    VALIDATED = "validated"
    CLASSIFIED = "classified"
    PLANNING = "planning"
    EXECUTING = "executing"
    OBSERVING = "observing"
    REPLANNING = "replanning"
    VERIFYING = "verifying"
    SOLVED = "solved"
    EXHAUSTED = "exhausted"
    POLICY_DENIED = "policy_denied"
    ERROR = "error"
    CANCELLED = "cancelled"


class RunBudget(BaseModel):
    max_actions: int = Field(default=40, ge=1, le=1000)
    wall_time_seconds: int = Field(default=1200, ge=1)
    per_tool_seconds: int = Field(default=30, ge=1)
    max_parallel_workers: int = Field(default=2, ge=1, le=16)
    max_model_tokens: int = Field(default=100_000, ge=1)
    max_cost_usd: float = Field(default=10.0, ge=0)


class RunEvent(BaseModel):
    schema_version: Literal[1] = 1
    run_id: str
    sequence: int = Field(ge=0)
    status: RunStatus
    detail: dict[str, str] = Field(default_factory=dict)
