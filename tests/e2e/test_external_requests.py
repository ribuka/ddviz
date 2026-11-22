"""E2E: a page's request outside the UI server is aborted, recorded and fails the test (Issue #377)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import fail_on_external, is_local

pytestmark = pytest.mark.e2e

# A host that never resolves (RFC 2606): a request let through would fail
# with another error than the abort, and reaches nobody.
EXTERNAL = "https://ddviz-e2e.invalid/api/plot"
#: How an aborted request fails (``route.abort()``).
ABORTED = "net::ERR_FAILED"


def fetch_external(page: Page) -> tuple[str, list[str]]:
    """Fetch `EXTERNAL` in the page; return the outcome and how the requests that failed failed."""
    failures: list[str] = []
    page.on("requestfailed", lambda request: failures.append(request.failure))
    outcome = page.evaluate("url => fetch(url).then(() => 'loaded', () => 'failed')", EXTERNAL)
    return outcome, failures


def test_a_request_outside_the_server_is_aborted_and_recorded(
    app_page: Page, external_requests: list[str]
) -> None:
    """A ``fetch`` of an external URL is aborted and recorded; the server's own requests are not."""
    assert fetch_external(app_page) == ("failed", [ABORTED])
    assert external_requests == [EXTERNAL]
    # The detection itself is what fails the test at its end.
    with pytest.raises(pytest.fail.Exception, match=EXTERNAL):
        fail_on_external(external_requests)
    external_requests.clear()


def test_a_page_route_that_continues_still_aborts_and_records(
    app_page: Page, external_requests: list[str]
) -> None:
    """A test's ``page.route`` runs before the context's: its ``route.continue_()`` aborts an external URL, which is recorded once."""
    app_page.route("**/api/plot", lambda route: route.continue_())
    assert fetch_external(app_page) == ("failed", [ABORTED])
    assert external_requests == [EXTERNAL]
    external_requests.clear()


def test_a_page_route_that_fetches_still_aborts_and_records(
    app_page: Page, external_requests: list[str]
) -> None:
    """A ``route.fetch()`` of an external URL in a test's route sends nothing: the request is aborted and recorded."""
    app_page.route("**/api/plot", lambda route: route.fulfill(response=route.fetch()))
    assert fetch_external(app_page) == ("failed", [ABORTED])
    assert external_requests == [EXTERNAL]
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
