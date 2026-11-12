"""ksnctf URL identity and strict official JSON verdict contract."""
from __future__ import annotations

import re
import urllib.parse

from pydantic import BaseModel, ConfigDict

from metis.core.ctf_http import origin

OFFICIAL_ORIGIN = "https://ksnctf.sweetduet.info"


def problem_id(url: str) -> int:
    parsed = urllib.parse.urlsplit(url)
    match = re.fullmatch(r"/problem/([1-9][0-9]{0,6})/?", parsed.path)
    if match is None or parsed.query or int(match[1]) > 1_000_000:
        raise ValueError("ksnctf requires a /problem/ID URL without query parameters")
    return int(match[1])


def is_official_problem(url: str) -> bool:
    if origin(url) != OFFICIAL_ORIGIN:
        return False
    try:
        problem_id(url)
    except ValueError:
        return False
    return True


class KsnctfVerdict(BaseModel):
    # The server may return update metadata, but only a JSON boolean is a verdict.
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)
    result: bool
