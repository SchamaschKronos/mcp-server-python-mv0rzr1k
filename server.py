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

    if dimension not in ("MRY", "MRQ", "ARY", "ARQ"):
    return {
        "error": "Dimension must be MRY, MRQ, ARY or ARQ"
    }

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

@mcp.tool()
def sharadar_tickers(
    ticker: str = "",
    name: str = "",
    cik: str = "",
    limit: int = 100,
) -> dict:
    """Search Sharadar TICKERS reference data.

    Returns historical company identifiers including permaticker.
    """
    import re

    ticker = ticker.strip().upper()
    name = name.strip()
    cik = cik.strip()

    if not any((ticker, name, cik)):
        return {"error": "Provide ticker, name or cik"}

    if ticker and not re.fullmatch(r"[A-Z0-9.^-]{1,20}", ticker):
        return {"error": "Invalid ticker"}

    if cik and not re.fullmatch(r"[0-9]{1,10}", cik):
        return {"error": "Invalid CIK"}

    if not 1 <= limit <= 100:
        return {"error": "Limit must be between 1 and 100"}

    api_key = os.environ.get("SHARADAR_API_KEY")
    if not api_key:
        return {"error": "Sharadar API key is not configured"}

    params = {
        "format": "json",
        "limit": limit,
        "api_key": api_key,
    }

    if ticker:
        params["ticker"] = ticker
    if name:
        params["name"] = name
    if cik:
        params["secfilings"] = cik

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                "https://api.sharadar.com/v1.0/data/tickers",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

        return {
            "source": "Sharadar TICKERS",
            "data": data,
        }

    except httpx.HTTPStatusError as exc:
        return {
            "error": "Sharadar TICKERS request failed",
            "status_code": exc.response.status_code,
        }

    except (httpx.RequestError, ValueError):
        return {"error": "Unable to retrieve TICKERS data"}


@mcp.tool()
def sharadar_prices(
    ticker: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 100,
) -> dict:
    """Retrieve historical daily stock prices from Sharadar.

    Args:
        ticker: US stock symbol, e.g. AAPL or MSFT.
        start_date: Optional start date in YYYY-MM-DD format.
        end_date: Optional end date in YYYY-MM-DD format.
        limit: Maximum number of daily observations, 1 to 1000.
    """
    import re
    from datetime import date

    ticker = ticker.strip().upper()

    if not re.fullmatch(r"[A-Z0-9.^-]{1,20}", ticker):
        return {"error": "Invalid ticker symbol"}

    if not 1 <= limit <= 1000:
        return {"error": "Limit must be between 1 and 1000"}

    for value in (start_date, end_date):
        if value:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    return {"error": "Dates must use YYYY-MM-DD"}
            except ValueError:
                return {"error": "Dates must use YYYY-MM-DD"}

    if start_date and end_date and start_date > end_date:
        return {"error": "Start date must not exceed end date"}

    api_key = os.environ.get("SHARADAR_API_KEY")
    if not api_key:
        return {"error": "Sharadar API key is not configured"}

    url = "https://api.sharadar.com/v1.0/data/prices"

    params = {
        "ticker": ticker,
        "format": "json",
        "sort": "date.desc",
        "limit": limit,
        "api_key": api_key,
    }

    if start_date:
        params["date.gte"] = start_date

    if end_date:
        params["date.lte"] = end_date

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        return {
            "ticker": ticker,
            "start_date": start_date or None,
            "end_date": end_date or None,
            "source": "Sharadar",
            "data": data,
        }

    except httpx.HTTPStatusError as exc:
        return {
            "error": "Sharadar prices request failed",
            "status_code": exc.response.status_code,
        }
    except (httpx.RequestError, ValueError):
        return {"error": "Unable to retrieve Sharadar prices"}

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
