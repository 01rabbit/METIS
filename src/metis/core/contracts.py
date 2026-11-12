"""P0 contracts. No model/tool execution occurs in this module."""
from __future__ import annotations

import re
from enum import StrEnum
from ipaddress import ip_address
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ChallengeCategory(StrEnum):
    PWN = "pwn"
    REV = "rev"
    WEB = "web"
    CRYPTO = "crypto"
    FORENSICS = "forensics"
    MISC = "misc"


class AllowedEndpoint(Contract):
    hostname: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)

    @field_validator("hostname")
    @classmethod
    def validate_host(cls, value: str) -> str:
        try:
            address = ip_address(value)
        except ValueError:
            hostname = value.lower()
            labels = hostname.split(".")
            if len(hostname) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            ):
                raise ValueError("endpoint must be an exact ASCII hostname or IP") from None
            if re.fullmatch(r"[0-9.]+", hostname):
                raise ValueError("ambiguous numeric hostname")
            return hostname
        if address.is_unspecified or address.is_multicast or "%" in value:
            raise ValueError("unspecified, multicast or scoped address is not permitted")
        return str(address)


class ScopeGrant(Contract):
    granted_by: str = Field(min_length=1)
    challenge_id: str = Field(min_length=1)
    allowed_endpoints: list[AllowedEndpoint] = Field(default_factory=list)
    authorized: Literal[True]

    @field_validator("authorized", mode="before")
    @classmethod
    def explicit_boolean(cls, value: object) -> object:
        if value is not True:
            raise ValueError("authorization must be the explicit boolean true")
        return value

class ChallengeManifest(Contract):
    schema_version: Literal[1] = 1
    challenge_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_.-]+$")
    title: str = Field(min_length=1)
    description: str
    categories: list[ChallengeCategory] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    scope: ScopeGrant

    @model_validator(mode="after")
    def check_grant(self) -> ChallengeManifest:
        if self.scope.challenge_id != self.challenge_id:
            raise ValueError("scope grant challenge_id mismatch")
        for p in self.artifacts:
            path = PurePosixPath(p)
            windows = PureWindowsPath(p)
            if (
                not p or p == "." or "\x00" in p or "\\" in p
                or path.is_absolute() or windows.drive or ".." in path.parts
            ):
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


class RunBudget(Contract):
    max_actions: int = Field(default=40, ge=1, le=1000)
    wall_time_seconds: int = Field(default=1200, ge=1)
    per_tool_seconds: int = Field(default=30, ge=1)
    max_parallel_workers: int = Field(default=2, ge=1, le=16)
    max_model_tokens: int = Field(default=100_000, ge=1)
    max_cost_usd: float = Field(default=10.0, ge=0)


class RunEvent(Contract):
    schema_version: Literal[1] = 1
    run_id: str
    sequence: int = Field(ge=0)
    status: RunStatus
    detail: dict[str, str] = Field(default_factory=dict)
