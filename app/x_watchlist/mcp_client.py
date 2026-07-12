from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.x_watchlist.schemas import FATAL_SESSION_REASON_CODES, RETRYABLE_REASON_CODES


class MCPClientError(Exception):
    def __init__(self, reason_code: str, message: str, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.reason_code = reason_code
        self.payload = payload or {}


class MCPFatalSessionError(MCPClientError):
    """Global session/auth failure — terminate the run."""


class MCPRetryableError(MCPClientError):
    """Transient failure — limited retry allowed."""


@dataclass
class XNewsMCPSettings:
    node_command: str = "node"
    server_script: str = r"C:\Users\90556\.codex\tools\x-news-mcp\dist\index.js"
    profile_dir: str = r"C:\Users\90556\.codex-x-news-agent"
    chrome_path: str = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    timeout_ms: str = "30000"
    max_page_load_retries: int = 1
    max_rate_limit_retries: int = 0

    @classmethod
    def from_env(cls) -> XNewsMCPSettings:
        return cls(
            node_command=os.environ.get("X_MCP_NODE", "node"),
            server_script=os.environ.get(
                "X_MCP_SERVER_SCRIPT",
                r"C:\Users\90556\.codex\tools\x-news-mcp\dist\index.js",
            ),
            profile_dir=os.environ.get("X_AGENT_PROFILE_DIR", r"C:\Users\90556\.codex-x-news-agent"),
            chrome_path=os.environ.get(
                "X_AGENT_CHROME_PATH",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            ),
            timeout_ms=os.environ.get("X_AGENT_TIMEOUT_MS", "30000"),
        )


@dataclass
class XNewsMCPClient:
    settings: XNewsMCPSettings = field(default_factory=XNewsMCPSettings.from_env)
    _stack: AsyncExitStack | None = field(default=None, repr=False)
    _session: ClientSession | None = field(default=None, repr=False)

    async def __aenter__(self) -> XNewsMCPClient:
        self._stack = AsyncExitStack()
        params = StdioServerParameters(
            command=self.settings.node_command,
            args=[self.settings.server_script],
            env={
                "X_AGENT_PROFILE_DIR": self.settings.profile_dir,
                "X_AGENT_CHROME_PATH": self.settings.chrome_path,
                "X_AGENT_TIMEOUT_MS": self.settings.timeout_ms,
            },
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("MCP session is not open")
        result = await self._session.call_tool(name, arguments)
        structured: dict[str, Any] | None = None
        if result.structuredContent and isinstance(result.structuredContent, dict):
            structured = result.structuredContent
        elif result.content:
            for block in result.content:
                text = getattr(block, "text", None)
                if not text:
                    continue
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        structured = parsed
                        break
                except json.JSONDecodeError:
                    continue

        if structured is None:
            raise MCPClientError("unexpected_browser_error", f"Tool {name} returned no structured content")

        if structured.get("error"):
            reason_code = str(structured.get("reason_code", "unexpected_browser_error"))
            reason = str(structured.get("reason", "Unknown MCP tool error"))
            self._raise_for_reason(reason_code, reason, structured)

        if result.isError:
            reason_code = str(structured.get("reason_code", "unexpected_browser_error"))
            reason = str(structured.get("reason", "Unknown MCP tool error"))
            self._raise_for_reason(reason_code, reason, structured)

        return structured

    def _raise_for_reason(self, reason_code: str, reason: str, payload: dict[str, Any]) -> None:
        if reason_code in FATAL_SESSION_REASON_CODES:
            raise MCPFatalSessionError(reason_code, reason, payload)
        if reason_code in RETRYABLE_REASON_CODES:
            raise MCPRetryableError(reason_code, reason, payload)
        raise MCPClientError(reason_code, reason, payload)

    async def session_status(self) -> dict[str, Any]:
        return await self._call_tool("x_session_status", {"response_format": "json"})

    async def profile_posts(
        self,
        handle: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        clean_handle = handle.lstrip("@")
        attempts = 0
        max_attempts = 1 + self.settings.max_page_load_retries + self.settings.max_rate_limit_retries
        last_error: Exception | None = None

        while attempts < max_attempts:
            attempts += 1
            try:
                return await self._call_tool(
                    "x_profile_posts",
                    {
                        "handle": clean_handle,
                        "limit": min(max(limit, 1), 20),
                        "offset": max(offset, 0),
                        "response_format": "json",
                    },
                )
            except MCPRetryableError as exc:
                last_error = exc
                if exc.reason_code == "x_rate_limited" and attempts > self.settings.max_rate_limit_retries:
                    raise
                if exc.reason_code == "x_page_load_failed" and attempts > self.settings.max_page_load_retries:
                    raise
                await asyncio.sleep(2 * attempts)
        if last_error:
            raise last_error
        raise MCPClientError("unexpected_browser_error", "profile_posts failed without error detail")


def default_server_exists() -> bool:
    settings = XNewsMCPSettings.from_env()
    return Path(settings.server_script).exists()
