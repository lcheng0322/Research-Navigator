"""
Centralized Redis cache client.

This module initializes a single, reusable asynchronous Redis client instance
for the entire application to use for caching purposes.

The client is configured using the REDIS_URL from the application settings.
"""
import redis.asyncio as aioredis
from .config import settings

# Initialize the asynchronous Redis client from the URL in settings
# The 'decode_responses=True' argument ensures that data read from Redis is automatically
# decoded from bytes to UTF-8 strings, which is convenient for most use cases.
redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

async def close_redis_connection():
    """
    Gracefully closes the Redis client connection.
    To be called during application shutdown.
    """
    await redis_client.close()
