from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send
import hmac
import os
import httpx

MCP_API_TOKEN = os.environ.get("MCP_API_TOKEN")
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

mcp = FastMCP(
    "my-mcp-server",
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(RENDER_EXTERNAL_HOSTNAME),
        allowed_hosts=[RENDER_EXTERNAL_HOSTNAME] if RENDER_EXTERNAL_HOSTNAME else [],
    ),
)


# Add tools below. The docstring is surfaced to LLMs as the tool description.
# Type hints define the JSON schema for parameters.
@mcp.tool()
def hello(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"


@mcp.tool()
def sharadar_fundamentals(
    ticker: str,
    dimension: str = "MRY",
    limit: int = 10,
) -> dict:
    """Retrieve historical financial statements from Sharadar.

    Args:
        ticker: US stock symbol, e.g. AAPL or MSFT.
        dimension: MRY for annual, MRQ for quarterly.
        limit: Maximum number of observations, 1 to 20.
    """
    import re

    ticker = ticker.strip().upper()
    dimension = dimension.upper()

    if not re.fullmatch(r"[A-Z0-9.^-]{1,20}", ticker):
        return {"error": "Invalid ticker symbol"}

    if dimension not in ("MRY", "MRQ"):
        return {"error": "Dimension must be MRY or MRQ"}

    if not 1 <= limit <= 20:
        return {"error": "Limit must be between 1 and 20"}

    api_key = os.environ.get("SHARADAR_API_KEY")
    if not api_key:
        return {"error": "Sharadar API key is not configured"}

    
    url = "https://api.sharadar.com/v1.0/data/fundamentals"

    params = {
        "ticker": ticker,
        "dimension": dimension,
        "format": "json",
        "sort": "calendardate.desc",
        "limit": limit,
        "api_key": api_key,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                url,
                params=params,
            )
            response.raise_for_status()
            data = response.json()

        return {
            "ticker": ticker,
            "dimension": dimension,
            "source": "Sharadar",
            "data": data,
        }

    except httpx.HTTPStatusError as exc:
        return {
            "error": "Sharadar request failed",
            "status_code": exc.response.status_code,
        }
    except (httpx.RequestError, ValueError):
        return {"error": "Unable to retrieve Sharadar data"}

# custom_route bypasses auth — use only for public endpoints
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


# Simple bearer token auth. For multi-user or production setups,
# consider upgrading to the MCP SDK's built-in OAuth 2.1 support.
class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope["path"] == "/health":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()
        # constant-time comparison to prevent timing side-channel attacks
        if hmac.compare_digest(auth, f"Bearer {MCP_API_TOKEN}"):
            await self.app(scope, receive, send)
            return

        response = JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32001, "message": "Unauthorized"},
                "id": None,
            },
            status_code=401,
        )
        await response(scope, receive, send)


def create_app():
    app = mcp.streamable_http_app()
    # When no token is set (local dev), auth is disabled entirely
    if MCP_API_TOKEN:
        app.add_middleware(BearerAuthMiddleware)
    return app


if __name__ == "__main__":
    import uvicorn

    if not MCP_API_TOKEN:
        print(
            "WARNING: MCP_API_TOKEN is not set."
            " The server is running without authentication."
        )

    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(create_app(), host="0.0.0.0", port=port)
