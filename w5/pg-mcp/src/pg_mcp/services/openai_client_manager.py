"""OpenAI client manager for shared client instances.

This module provides a singleton-style manager for OpenAI client to avoid
creating multiple connections that can trigger rate limits with APIs like
Zhipu AI which have strict concurrency limits.
"""

import asyncio
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

if TYPE_CHECKING:
    from pg_mcp.config.settings import OpenAIConfig


class OpenAIClientManager:
    """Singleton manager for shared OpenAI client instances.

    This class ensures that all services using the same API configuration
    share a single AsyncOpenAI client instance, preventing multiple concurrent
    connections that can trigger rate limits.

    Usage:
        >>> manager = OpenAIClientManager.get_instance(config)
        >>> client = manager.get_client()
        >>> # Use client for API calls...
    """

    _instance: "OpenAIClientManager | None" = None
    _clients: dict[str, AsyncOpenAI] = {}

    def __new__(cls, *args, **kwargs):
        # Prevent multiple instances of the manager itself
        if cls._instance is None:
            cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self) -> None:
        """Initialize the manager (only called once due to __new__)."""
        self._config = None
        self._lock = asyncio.Lock()

    def configure(self, config: "OpenAIConfig") -> None:
        """Configure the manager with OpenAI settings.

        Args:
            config: OpenAI configuration.
        """
        self._config = config

    @classmethod
    def get_instance(cls) -> "OpenAIClientManager":
        """Get the singleton instance of the manager.

        Returns:
            OpenAIClientManager: The singleton manager instance.
        """
        if cls._instance is None:
            cls._instance = cls.__new__(cls)
        return cls._instance

    def get_client(self) -> AsyncOpenAI:
        """Get or create a shared AsyncOpenAI client.

        Returns:
            AsyncOpenAI: Shared client instance for the current config.
        """
        if self._config is None:
            raise RuntimeError("OpenAIClientManager not configured. Call configure() first.")

        # Create a cache key based on config
        cache_key = f"{self._config.api_key.get_secret_value()}:{self._config.base_url}:{self._config.model}"

        # Return cached client if exists
        if cache_key in self._clients:
            return self._clients[cache_key]

        # Create new client instance
        client = AsyncOpenAI(
            api_key=self._config.api_key.get_secret_value(),
            base_url=self._config.base_url,
            timeout=self._config.timeout,
            # Limit max connections to avoid hitting rate limits
            max_retries=2,
        )

        self._clients[cache_key] = client
        return client

    async def close_all(self) -> None:
        """Close all cached clients.

        This should be called during application shutdown.
        """
        async with self._lock:
            for client in self._clients.values():
                await client.close()
            self._clients.clear()

    @classmethod
    async def reset(cls) -> None:
        """Reset the singleton and close all clients.

        Useful for testing or when config changes.
        """
        if cls._instance is not None:
            await cls._instance.close_all()
            cls._instance = None
            cls._clients.clear()
