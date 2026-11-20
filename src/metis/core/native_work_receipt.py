"""Strict parser and outcome mapper for one native work receipt."""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from metis.core.study_token_admission import TokenLaunchOutcome

MAX_NATIVE_WORK_RECEIPT_BYTES = 256


class NativeWorkReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    cap: int = Field(ge=1, le=10_000_000)
    charged: int = Field(ge=0, le=10_000_000)
    reason: Literal["shutdown", "cap_denied", "unsupported_graph", "server_error"]


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate receipt field")
        result[key] = value
    return result


def parse_native_work_receipt(
    raw: bytes,
    *,
    nonce: str,
    cap: int,
    exit_status: int,
    generated: int | None,
    minimum_completed_work: int | None = None,
    maximum_completed_work: int | None = None,
) -> TokenLaunchOutcome:
    """Validate receipt bytes and bind them to the exact process and completion."""
    invalid = TokenLaunchOutcome(status="receipt_invalid", exit_status=exit_status)
    if (len(raw) > MAX_NATIVE_WORK_RECEIPT_BYTES or raw.count(b"\n") != 1
            or not raw.endswith(b"\n")):
        return invalid
    try:
        record = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_fields)
        receipt = NativeWorkReceipt.model_validate(record)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, ValidationError):
        return invalid
    if (receipt.nonce != nonce or receipt.cap != cap or receipt.charged > receipt.cap):
        return invalid

    if receipt.reason == "shutdown" and exit_status == 0:
        if generated is None:
            # A valid process receipt is still useful when the HTTP request did
            # not complete. Preserve the measured work while refusing success.
            return TokenLaunchOutcome(
                status="request_incomplete", exit_status=exit_status,
                observed_work=receipt.charged,
            )
        if (minimum_completed_work is not None
                and receipt.charged < minimum_completed_work):
            return invalid
        if (maximum_completed_work is not None
                and receipt.charged > maximum_completed_work):
            return invalid
        return TokenLaunchOutcome(
            status="completed", exit_status=exit_status, observed_work=receipt.charged,
        )
    if receipt.reason == "cap_denied" and exit_status == 75 and generated is None:
        return TokenLaunchOutcome(status="cap_denied", exit_status=exit_status,
                                  observed_work=receipt.charged)
    if receipt.reason == "unsupported_graph" and exit_status == 75 and generated is None:
        return TokenLaunchOutcome(status="unsupported_graph", exit_status=exit_status,
                                  observed_work=receipt.charged)
    if (receipt.reason == "server_error" and 1 <= exit_status <= 255
            and exit_status not in (74, 75) and generated is None):
        return TokenLaunchOutcome(status="server_error", exit_status=exit_status,
                                  observed_work=receipt.charged)
    return invalid
