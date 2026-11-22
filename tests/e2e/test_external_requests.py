"""E2E: a page's request outside the UI server is aborted, recorded and fails the test (Issue #377)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import fail_on_external, is_local

pytestmark = pytest.mark.e2e

EXTERNAL = "https://example.com/ddviz-e2e"


def test_a_request_outside_the_server_is_aborted_and_recorded(
    app_page: Page, external_requests: list[str]
) -> None:
    """A ``fetch`` of an external URL fails in the page and is recorded; the server's own requests are not."""
    outcome = app_page.evaluate(
        "url => fetch(url).then(() => 'loaded', () => 'failed')", EXTERNAL
    )
    assert outcome == "failed"
    assert external_requests == [EXTERNAL]
    # The detection itself is what fails the test at its end.
    with pytest.raises(pytest.fail.Exception, match=EXTERNAL):
        fail_on_external(external_requests)
    external_requests.clear()


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://127.0.0.1:8123/api/plot", True),
        ("data:image/png;base64,AAAA", True),
        ("blob:http://127.0.0.1:8123/0b6f", True),
        ("https://cdn.plot.ly/world_110m.json", False),
        ("http://localhost:8123/", False),
        ("https://127.0.0.1:8123/", False),
    ],
)
def test_only_the_ui_server_data_and_blob_are_local(url: str, local: bool) -> None:
    """The UI server on 127.0.0.1 and ``data:``/``blob:`` pass; any other host or scheme is external."""
    assert is_local(url) is local
