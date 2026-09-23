"""MongoDB access — raw job postings, agent run/event logs, notification log.

Deliberately schema-less at this layer: each job-board source shapes its
postings differently, and normalizing before storage would mean writing a
schema for data you haven't seen yet (Phase 4).
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from jobpilot_shared.config import settings

_client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongo_url)


def get_db() -> AsyncIOMotorDatabase:
    return _client[settings.mongo_db]


async def ping() -> bool:
    await _client.admin.command("ping")
    return True
