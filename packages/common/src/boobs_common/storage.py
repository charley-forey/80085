"""S3-compatible object storage for execution outputs and logs.

Execution rows stay small and queryable; the bytes an execution produced live
here under a key derived from the execution id. MinIO locally, any S3 API in
production -- nothing above this module knows which.
"""

from __future__ import annotations

import json
from typing import Any

import aioboto3

from boobs_common.config import settings


def _client() -> Any:
    config = settings()
    return aioboto3.Session().client(
        "s3",
        endpoint_url=config.s3_endpoint_url or None,
        aws_access_key_id=config.s3_access_key_id,
        aws_secret_access_key=config.s3_secret_access_key,
        region_name=config.s3_region,
    )


async def ensure_bucket() -> None:
    bucket = settings().s3_bucket
    async with _client() as s3:
        try:
            await s3.head_bucket(Bucket=bucket)
        except Exception:  # noqa: BLE001 - any failure means "try to create it"
            await s3.create_bucket(Bucket=bucket)


async def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    async with _client() as s3:
        await s3.put_object(
            Bucket=settings().s3_bucket, Key=key, Body=data, ContentType=content_type
        )
    return key


async def put_json(key: str, document: dict[str, Any]) -> str:
    return await put_bytes(key, json.dumps(document).encode(), "application/json")


async def get_bytes(key: str) -> bytes:
    async with _client() as s3:
        response = await s3.get_object(Bucket=settings().s3_bucket, Key=key)
        return bytes(await response["Body"].read())


async def get_json(key: str) -> dict[str, Any]:
    return dict(json.loads(await get_bytes(key)))


async def healthy() -> bool:
    try:
        async with _client() as s3:
            await s3.head_bucket(Bucket=settings().s3_bucket)
        return True
    except Exception:  # noqa: BLE001 - readiness probe reports, never raises
        return False


def output_key(execution_id: str) -> str:
    return f"executions/{execution_id}/outputs.json"


def logs_key(execution_id: str) -> str:
    return f"executions/{execution_id}/logs.json"
