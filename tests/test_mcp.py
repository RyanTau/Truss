import json
import unittest
import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from support import integration

mcp = integration("mcp")


class MCPTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.use_sse = False
        self.fail = False

        async def endpoint(request):
            self.assertEqual(request.headers["Authorization"], "Bearer test-token")
            payload = await request.json()
            self.calls.append(payload)
            if "id" not in payload:
                return web.Response(status=202)
            if payload["method"] == "initialize":
                result = {"protocolVersion": "2025-03-26", "serverInfo": {"name": "test", "version": "1"}, "capabilities": {}}
            elif payload["method"] == "tools/list":
                result = {"tools": [{"name": "HassTurnOn"}]}
            else:
                result = {"content": [{"type": "text", "text": json.dumps({"response_type": "error" if self.fail else "action_done"})}]}
            body = {"jsonrpc": "2.0", "id": payload["id"], "result": result}
            if self.use_sse:
                return web.Response(text='event: message\ndata: ' + json.dumps(body) + '\n\n', content_type="text/event-stream")
            return web.json_response(body)

        app = web.Application()
        app.router.add_post("/api/mcp", endpoint)
        self.server = TestServer(app)
        await self.server.start_server()
        self.session = aiohttp.ClientSession()
        self.client = mcp.MCPClient(self.session, str(self.server.make_url("/api/mcp")), "test-token")

    async def asyncTearDown(self):
        await self.session.close()
        await self.server.close()

    async def test_json_handshake_discovery_and_execution(self):
        await self.client.initialize()
        self.assertEqual((await self.client.list_tools())[0]["name"], "HassTurnOn")
        await self.client.call("HassTurnOn", {"name": "light.kitchen"})
        self.assertEqual([c["method"] for c in self.calls], ["initialize", "notifications/initialized", "tools/list", "tools/call"])

    async def test_sse_transport(self):
        self.use_sse = True
        await self.client.initialize()
        self.assertEqual(len(await self.client.list_tools()), 1)

    async def test_intent_error_is_not_success_or_retried(self):
        self.fail = True
        with self.assertRaises(mcp.MCPError):
            await self.client.call("HassTurnOn", {"name": "light.kitchen"})
        self.assertEqual(len(self.calls), 1)

    async def test_tool_level_error(self):
        self.assertFalse(mcp.tool_succeeded({"isError": True}))
        self.assertFalse(mcp.tool_succeeded({"structuredContent": {"success": False}}))
        self.assertFalse(mcp.tool_succeeded({"content": [{"type": "text", "text": '{"data":{"failed":[{"name":"Kitchen"}]}}'}]}))

    async def test_wrong_response_id_rejected(self):
        with self.assertRaises(mcp.MCPError):
            mcp.decode_rpc({"id": 10, "result": {}}, 9)


class URLTests(unittest.TestCase):
    def test_no_embedded_credentials_or_wrong_schemes(self):
        for url in ("file:///secret", "http://user:password@host", "localhost:8123", "https://host/#secret"):
            with self.assertRaises(ValueError):
                mcp.validate_url(url)
