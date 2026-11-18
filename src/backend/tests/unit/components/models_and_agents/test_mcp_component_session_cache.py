"""Each chat discovers its own MCP tools while repeated steps reuse that chat's cache."""

import asyncio
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool
from lfx.components.models_and_agents.mcp_component import MCPToolsComponent
from lfx.services.shared_component_cache.service import SharedComponentCacheService


@pytest.fixture
def discovery(monkeypatch):
    cache = SharedComponentCacheService()
    monkeypatch.setattr(
        "lfx.custom.custom_component.component_with_cache.get_shared_component_cache_service", lambda: cache
    )
    # Exercise the supported standalone path; only external discovery is replaced.
    monkeypatch.setitem(sys.modules, "langflow.api.v2.mcp", None)
    clients = {}
    calls = []

    def component(session_id, server="server-one", *, user="owner", ttl=30):
        result = MCPToolsComponent(
            _session_id=session_id,
            _user_id=user,
            mcp_server={"name": server, "config": {"url": f"https://example.com/{server}"}},
            use_cache=True,
            headers=[],
        )
        result.TOOL_TTL_SECS = ttl
        clients[id(result.streamable_http_client)] = result
        return result

    async def fetch(**kwargs):
        client = clients[id(kwargs["mcp_streamable_http_client"])]
        identity = (client.user_id, client.graph.session_id, kwargs["server_name"])
        calls.append(identity)
        await asyncio.sleep(0)

        async def invoke() -> tuple:
            return identity

        tool = StructuredTool.from_function(coroutine=invoke, name="identify", description="Identify discovery context")
        return "Streamable_HTTP", [tool], {tool.name: tool}

    monkeypatch.setattr("lfx.components.models_and_agents.mcp_component.update_tools", fetch)
    return component, calls


@pytest.mark.parametrize("ttl", [0, 30])
async def test_new_session_discovers_tools_and_reuses_only_its_own_cache(discovery, ttl):
    component, calls = discovery
    a = component("A", ttl=ttl)
    b = component("B", ttl=ttl)

    for current, session in [(a, "A"), (a, "A"), (b, "B"), (b, "B"), (component("A", ttl=ttl), "A")]:
        tools = await current._get_tools()
        assert await tools[0].coroutine() == ("owner", session, "server-one")

    assert calls == [("owner", "A", "server-one"), ("owner", "B", "server-one")]


async def test_multiple_servers_remain_separate_in_each_session(discovery):
    component, calls = discovery
    for _ in range(2):
        for session in ("A", "B"):
            for server in ("server-one", "server-two"):
                tools = await component(session, server)._get_tools()
                assert await tools[0].coroutine() == ("owner", session, server)

    assert calls == [("owner", session, server) for session in ("A", "B") for server in ("server-one", "server-two")]


async def test_changing_session_on_existing_component_misses_both_caches(discovery):
    component, calls = discovery
    current = component("A")
    for session in ("A", "B", "A"):
        current._session_id = session
        tools = await current._get_tools()
        assert await tools[0].coroutine() == ("owner", session, "server-one")

    assert calls == [("owner", "A", "server-one"), ("owner", "B", "server-one")]


@pytest.mark.parametrize("session_id", [None, ""])
async def test_missing_session_does_not_reuse_tool_lists(discovery, session_id):
    component, calls = discovery
    first = component(session_id)
    second = component(session_id)
    for current in (first, first, second):
        await current._get_tools()

    assert len(calls) == 3
    assert first._ttl_tool_cache == {}
    assert second._ttl_tool_cache == {}


async def test_same_session_id_remains_scoped_to_user(discovery):
    component, calls = discovery
    for owner in ("owner-one", "owner-two", "owner-one"):
        tools = await component("A", user=owner)._get_tools()
        assert await tools[0].coroutine() == (owner, "A", "server-one")

    assert calls == [("owner-one", "A", "server-one"), ("owner-two", "A", "server-one")]


async def test_concurrent_sessions_keep_their_own_tools(discovery):
    component, calls = discovery
    a = component("A")
    b = component("B")
    await asyncio.gather(a._get_tools(), b._get_tools())
    for session in ("A", "B"):
        tools = await component(session)._get_tools()
        assert await tools[0].coroutine() == ("owner", session, "server-one")

    assert len(calls) == 2


async def test_invocation_copy_uses_current_graph_session(discovery):
    component, calls = discovery
    source = component("old-session")
    source._vertex = SimpleNamespace(graph=SimpleNamespace(session_id="A", user_id="owner", context={}))
    tools = await source._get_tools()
    invocation = deepcopy(source)

    assert await invocation._get_tools() is tools
    assert calls == [("owner", "A", "server-one")]
