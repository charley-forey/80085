"""E2B builds the template on its own machines, so it needs registry credentials.

The artifact registry is authenticated. `from_image` accepts a username and
password precisely so a private image can be pulled, and without them a pull of
any non-public artifact fails inside E2B's builder -- somewhere the operator
cannot see. These are read from the environment for the same reason the E2B key
is: a credential in source is a credential in every clone.
"""

from __future__ import annotations

import pytest

from boobs_common.errors import ExecutionFailed
from boobs_execution.e2b_runtime import (
    REGISTRY_PASSWORD_ENV,
    REGISTRY_USER_ENV,
    registry_credentials,
)


def test_no_credentials_means_a_public_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REGISTRY_USER_ENV, raising=False)
    monkeypatch.delenv(REGISTRY_PASSWORD_ENV, raising=False)
    assert registry_credentials() == (None, None)


def test_both_are_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REGISTRY_USER_ENV, "80085")
    monkeypatch.setenv(REGISTRY_PASSWORD_ENV, "shibboleth")
    assert registry_credentials() == ("80085", "shibboleth")


@pytest.mark.parametrize("present", [REGISTRY_USER_ENV, REGISTRY_PASSWORD_ENV])
def test_half_a_credential_is_refused_loudly(monkeypatch: pytest.MonkeyPatch, present: str) -> None:
    """The failure this prevents happens inside E2B's builder, not here.

    A username with no password authenticates as nobody, and the resulting 401
    surfaces as a template build failure with no obvious cause. Refusing at the
    boundary names the actual problem.
    """
    monkeypatch.delenv(REGISTRY_USER_ENV, raising=False)
    monkeypatch.delenv(REGISTRY_PASSWORD_ENV, raising=False)
    monkeypatch.setenv(present, "half")
    with pytest.raises(ExecutionFailed, match="half a credential"):
        registry_credentials()


def test_blank_is_treated_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A platform that sets an unset variable to "" must not look configured."""
    monkeypatch.setenv(REGISTRY_USER_ENV, "   ")
    monkeypatch.setenv(REGISTRY_PASSWORD_ENV, "")
    assert registry_credentials() == (None, None)
