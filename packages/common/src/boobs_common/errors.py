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
    """The artifact ran and did not work. This is evidence about the Experience."""


class SandboxTimeout(ExecutionFailed):
    pass


class RuntimeUnavailable(EightyKError):
    """This worker could not run the artifact. It says nothing about the artifact.

    Deliberately **not** a subclass of `ExecutionFailed`, because the whole
    point is that the two must not be handled alike. A failed pull, a daemon
    that is not there, a filter that cannot be installed -- none of these are
    the Experience's fault, and recording them as failed runs lowers the
    confidence of a solution that is perfectly good.

    That was not hypothetical. A dev worker on a laptop joined the production
    queue, failed every `docker pull` with a Windows NT status, and wrote those
    failures into the evidence of whatever it happened to claim. Because the
    queue uses `FOR UPDATE SKIP LOCKED`, a worker that fails fast wins *more*
    jobs than a healthy one that takes time to run containers -- so a broken
    worker poisons the corpus faster than a working one can prove it right.

    A worker that raises this should report nothing at all and let the lease
    expire: `leases.reclaim_expired` requeues the job for someone who can run
    it, and gives up after MAX_ATTEMPTS.
    """
