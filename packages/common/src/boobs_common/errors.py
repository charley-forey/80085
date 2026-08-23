"""Domain errors. Transport layers map these to status codes; nothing below
the API layer imports HTTP."""

from __future__ import annotations


class EightyKError(Exception):
    """Base for every error this system raises deliberately."""


class NotFound(EightyKError):
    pass


class Forbidden(EightyKError):
    """Authenticated, but policy or tenancy denies the action."""


class Unauthorized(EightyKError):
    pass


class ValidationError(EightyKError):
    pass


class Conflict(EightyKError):
    pass


class ExecutionFailed(EightyKError):
    pass


class SandboxTimeout(ExecutionFailed):
    pass
