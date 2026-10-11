"""Reusable HTTP clients, owned and closed by the backend event loop."""
import asyncio
from contextlib import asynccontextmanager
from weakref import WeakKeyDictionary

import httpx

_clients = WeakKeyDictionary()


@asynccontextmanager
async def market_http_client(timeout: float = 10.0):
    clients = _clients.setdefault(asyncio.get_running_loop(), {})
    client = clients.get(timeout)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        clients[timeout] = client
    yield client


async def close_market_http_clients():
    clients = _clients.pop(asyncio.get_running_loop(), {})
    await asyncio.gather(*(client.aclose() for client in clients.values()))
