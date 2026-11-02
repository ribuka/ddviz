"""Tests of the notices shipped next to the exe, read byte for byte."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parents[1] / "packaging"

# SHA-256 of LICENSE.txt in the nupkg of Microsoft.Web.WebView2 1.0.3856.49
# (LF line breaks, as it is there).
_SDK_LICENSE_SHA256 = "0af8f1b807512aae39c2ac1aa4d0cae65cabecb6fd554b8439a5162a0d6eca55"


@pytest.mark.parametrize("name", ["LICENSE-WebView2-SDK.txt", "NOTICE.txt"])
def test_the_notices_break_lines_with_crlf(name: str) -> None:
    """Every line break is CRLF, for Notepad on Server 2016."""
    data = (PACKAGING / name).read_bytes()
    assert data
    assert data.count(b"\n") == data.count(b"\r\n")
    assert data.count(b"\r") == data.count(b"\r\n")


def test_the_notice_is_ascii() -> None:
    """NOTICE.txt has ASCII characters only."""
    (PACKAGING / "NOTICE.txt").read_bytes().decode("ascii")


def test_the_sdk_license_is_the_one_in_the_nupkg() -> None:
    """LICENSE-WebView2-SDK.txt differs from the nupkg's only in its line breaks."""
    data = (PACKAGING / "LICENSE-WebView2-SDK.txt").read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest() == _SDK_LICENSE_SHA256
