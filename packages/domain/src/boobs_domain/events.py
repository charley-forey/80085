"""Execution event vocabulary (spec section 20).

The event stream is append-only and is the source from which derived
Experience metadata can be regenerated.
"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    EXECUTION_STARTED = "execution.started"
    COMMAND_STARTED = "command.started"
    COMMAND_COMPLETED = "command.completed"
    COMMAND_FAILED = "command.failed"
    FILE_CREATED = "file.created"
    FILE_MODIFIED = "file.modified"
    TEST_STARTED = "test.started"
    TEST_COMPLETED = "test.completed"
    ARTIFACT_CREATED = "artifact.created"
    EXECUTION_COMPLETED = "execution.completed"
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_COMPLETED = "verification.completed"
