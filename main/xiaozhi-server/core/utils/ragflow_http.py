"""RAGFlow HTTP connection reuse for the server event loop."""

import asyncio
import weakref

import httpx


class RagflowHttpClientPool:
    """Keep one bounded HTTP client per event loop and recover stale sockets once."""

    def __init__(self):
        self._clients = weakref.WeakKeyDictionary()

    def _get_client(self):
        loop = asyncio.get_running_loop()
        client = self._clients.get(loop)
        reused = client is not None and not client.is_closed
        if not reused:
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(5.0, connect=3.0),
                verify=False,
                trust_env=False,
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=20,
                    keepalive_expiry=30.0,
                ),
            )
            self._clients[loop] = client
        return loop, client, reused

    async def post(self, url, *, json, headers):
        """POST with keep-alive and retry one failed transport connection once."""
        for attempt in range(2):
            _, client, reused = self._get_client()
            try:
                response = await client.post(url, json=json, headers=headers)
                return response, reused, attempt
            except (httpx.ConnectError, httpx.RemoteProtocolError):
                if attempt == 1:
                    raise

    async def close_all(self):
        clients = list(self._clients.values())
        self._clients.clear()
        if clients:
            await asyncio.gather(
                *(client.aclose() for client in clients if not client.is_closed),
                return_exceptions=True,
            )


ragflow_http_client_pool = RagflowHttpClientPool()
