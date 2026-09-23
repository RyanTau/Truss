"""Small Streamable HTTP MCP client; no execution retries on uncertain outcomes."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit

import aiohttp


class MCPError(Exception):
    """An MCP transport or tool failure."""


def validate_url(value: str, websocket: bool = False) -> str:
    parsed = urlsplit(value)
    allowed = ("ws", "wss") if websocket else ("http", "https")
    if parsed.scheme not in allowed or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Use a valid endpoint URL without embedded credentials or fragments")
    return value.rstrip("/")


def decode_rpc(data: dict, expected_id: int):
    if not isinstance(data, dict) or data.get("id") != expected_id:
        raise MCPError("MCP response did not match request")
    if "error" in data:
        raise MCPError("MCP rejected the request")
    if "result" not in data:
        raise MCPError("MCP response is missing its result")
    return data["result"]


def tool_succeeded(result: dict) -> bool:
    if not isinstance(result, dict) or result.get("isError"):
        return False
    values = []
    if isinstance(result.get("structuredContent"), dict):
        values.append(result["structuredContent"])
    for item in result.get("content", []):
        if item.get("type") == "text":
            try:
                values.append(json.loads(item["text"]))
            except (ValueError, KeyError):
                # Unstructured acknowledgement is allowed by MCP.
                pass
    for value in values:
        if isinstance(value, dict):
            if value.get("error") or value.get("success") is False or value.get("response_type") == "error":
                return False
            if isinstance(value.get("data"), dict) and value["data"].get("failed"):
                return False
    return True


class MCPClient:
    def __init__(self, session: aiohttp.ClientSession, url: str, token: str):
        self.session = session
        self.url = validate_url(url)
        self.token = token
        self.session_id = None
        self.protocol = "2025-03-26"
        self.counter = 0
        self.lock = asyncio.Lock()

    async def _post(self, payload: dict):
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": self.protocol}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        async with self.session.post(self.url, json=payload, headers=headers, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status not in (200, 202, 204):
                raise MCPError(f"MCP HTTP {response.status}; check URL, token, and exposed entities")
            if response.headers.get("Mcp-Session-Id"):
                self.session_id = response.headers["Mcp-Session-Id"]
            if "id" not in payload:
                return None
            if response.content_type == "text/event-stream":
                lines = []
                size = 0
                async for line in response.content:
                    size += len(line)
                    if size > 2_000_000:
                        raise MCPError("MCP response too large")
                    decoded = line.decode().rstrip("\r\n")
                    if decoded.startswith("data:"):
                        lines.append(decoded[5:].lstrip())
                    elif not decoded and lines:
                        message = json.loads("\n".join(lines))
                        lines = []
                        if message.get("id") == payload["id"]:
                            return decode_rpc(message, payload["id"])
                raise MCPError("MCP stream ended without a response")
            return decode_rpc(await response.json(), payload["id"])

    async def request(self, method: str, params: dict):
        async with self.lock:
            self.counter += 1
            return await self._post({"jsonrpc": "2.0", "id": self.counter, "method": method, "params": params})

    async def initialize(self):
        result = await self.request("initialize", {"protocolVersion": self.protocol, "capabilities": {}, "clientInfo": {"name": "truss", "version": "0.1.7"}})
        self.protocol = result.get("protocolVersion", self.protocol)
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def list_tools(self):
        tools, params = [], {}
        for _ in range(20):
            result = await self.request("tools/list", params)
            tools.extend(result.get("tools", []))
            if not result.get("nextCursor"):
                return tools
            params = {"cursor": result["nextCursor"]}
        raise MCPError("Too many MCP tool pages")

    async def call(self, name: str, arguments: dict):
        result = await self.request("tools/call", {"name": name, "arguments": arguments})
        if not tool_succeeded(result):
            raise MCPError("Home Assistant reported that the action failed")
        return result
