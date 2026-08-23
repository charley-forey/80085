"""One URL, three representations, chosen by what the caller says it wants.

The failure that matters here is cross-serving: handing a browser the ANSI
response, or handing an agent the HTML page. Both are silent, and both make
the site useless to exactly the audience it was built for.
"""

from __future__ import annotations

import pytest

from boobs_api.main import _representation

CHROME = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,*/*;q=0.8"


def pick(path: str = "/", accept: str = "", agent: str = "", fmt: str | None = None) -> str | None:
    return _representation(path, accept, agent, fmt)


def test_a_browser_gets_the_page() -> None:
    assert pick(accept=CHROME, agent="Mozilla/5.0 (Windows NT 10.0) Chrome/141") == "/p/home.html"


@pytest.mark.parametrize("agent", ["curl/8.4.0", "Wget/1.21.4", "HTTPie/3.2.2", "CURL/7.0"])
def test_a_shell_gets_ansi(agent: str) -> None:
    assert pick(accept="*/*", agent=agent) == "/index.ansi"
    assert pick(path="/install", accept="*/*", agent=agent) == "/install.ansi"


@pytest.mark.parametrize(
    "agent",
    [
        "ClaudeBot/1.0",
        "Claude-User/1.0",
        "GPTBot/1.2",
        "ChatGPT-User/1.0",
        "PerplexityBot/1.0",
        "Google-Extended",
        "CCBot/2.0",
        "cohere-ai",
        "Meta-ExternalAgent/1.0",
    ],
)
def test_a_crawler_gets_markdown_even_when_it_asks_for_html(agent: str) -> None:
    # The user-agent check deliberately precedes the Accept check: a crawler
    # that advertises text/html must not be handed the HTML page.
    assert pick(accept=CHROME, agent=agent) == "/index.md"


def test_accept_headers_are_honoured() -> None:
    assert pick(accept="text/markdown") == "/index.md"
    assert pick(accept="text/plain") == "/index.txt"


def test_format_query_overrides_everything() -> None:
    assert pick(accept=CHROME, agent="Chrome", fmt="md") == "/index.md"
    assert pick(accept=CHROME, agent="curl/8.4.0", fmt="txt") == "/index.txt"
    # Terminal mode on the site fetches exactly this.
    assert pick(path="/install", fmt="txt") == "/install.txt"


def test_an_unknown_format_is_ignored_rather_than_trusted() -> None:
    assert pick(accept=CHROME, fmt="../../etc/passwd") == "/p/home.html"


def test_only_negotiable_paths_are_rewritten() -> None:
    for path in ["/llms.txt", "/agents.md", "/v1/health", "/.well-known/mcp.json"]:
        assert pick(path=path, accept="text/plain", agent="curl/8.4.0") is None


def test_a_bare_request_gets_the_page() -> None:
    assert pick() == "/p/home.html"


def test_the_page_never_lives_where_a_static_host_would_claim_it() -> None:
    """The regression that made curl 80085.ai return HTML in production.

    A static host answers "/" from index.html during its filesystem step,
    before any rewrite runs. Serving the page from a path no request names
    keeps "/" unclaimed so negotiation actually happens.
    """
    for served in [pick(accept=CHROME), pick(path="/install", accept=CHROME)]:
        assert served is not None
        assert served.startswith("/p/"), served
