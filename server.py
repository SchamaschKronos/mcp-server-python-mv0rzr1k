
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
    limit: int = 1000,
) -> dict:
    """Retrieve historical financial statements from Sharadar.

    Args:
        ticker: Historical Sharadar stock symbol, e.g. DELL1.
        dimension: MRY, MRQ, ARY or ARQ.
        limit: Maximum observations to retrieve, 1 to 5000.
               Results are fetched in pages of up to 500.
    """
    import re

    ticker = ticker.strip().upper()
    dimension = dimension.strip().upper()

    if not re.fullmatch(r"[A-Z0-9.^-]{1,20}", ticker):
        return {"error": "Invalid ticker symbol"}

    if dimension not in ("MRY", "MRQ", "ARY", "ARQ"):
        return {
            "error": "Dimension must be MRY, MRQ, ARY or ARQ"
        }

    if not 1 <= limit <= 5000:
        return {"error": "Limit must be between 1 and 5000"}

    api_key = os.environ.get("SHARADAR_API_KEY")
    if not api_key:
        return {"error": "Sharadar API key is not configured"}

    url = "https://api.sharadar.com/v1.0/data/fundamentals"

    params = {
        "ticker": ticker,
        "dimension": dimension,
        "format": "json",
        "sort": "date.desc",
        "api_key": api_key,
    }

    records = []
    page_size = 500

    try:
        with httpx.Client(timeout=30.0) as client:
            while len(records) < limit:
                remaining = limit - len(records)
                params["limit"] = min(page_size, remaining)
                params["skip"] = len(records)

                response = client.get(url, params=params)
                response.raise_for_status()
                page = response.json()

                if not isinstance(page, dict):
                    return {
                        "error": "Unexpected Sharadar response",
                        "records_retrieved": len(records),
                        "complete": False,
                    }

                rows = page.get("data")
                if not isinstance(rows, list):
                    return {
                        "error": "Invalid Sharadar data structure",
                        "records_retrieved": len(records),
                        "complete": False,
                    }

                records.extend(rows)

                if len(rows) < params["limit"]:
                    break

        return {
            "ticker": ticker,
            "dimension": dimension,
            "source": "Sharadar",
            "data": {
                "count": len(records),
                "data": records,
            },
            "complete": len(records) < limit,
            "limit_reached": len(records) >= limit,
        }

    except httpx.HTTPStatusError as exc:
        return {
            "error": "Sharadar request failed",
            "status_code": exc.response.status_code,
            "records_retrieved": len(records),
            "complete": False,
        }
    except (httpx.RequestError, ValueError):
        return {
            "error": "Unable to retrieve Sharadar data",
            "records_retrieved": len(records),
            "complete": False,
        }


@mcp.tool()
def sharadar_tickers(
    ticker: str = "",
    name: str = "",
    cik: str = "",
    limit: int = 100,
    permaticker: str = "",
) -> dict:
    """Search Sharadar TICKERS reference data.

    Supports historical ticker, issuer name, CIK and permaticker.
    Name and CIK searches are filtered locally using the
    fundamentals security master.

    Returns matching historical identifiers and search completeness.
    """
    import re

    ticker = ticker.strip().upper()
    name = name.strip()
    cik = cik.strip()
    permaticker = permaticker.strip()

    if not any((ticker, name, cik, permaticker)):
        return {
            "error": "Provide ticker, name, cik or permaticker"
        }

    if ticker and not re.fullmatch(r"[A-Z0-9.^-]{1,20}", ticker):
        return {"error": "Invalid ticker"}

    if cik and not re.fullmatch(r"[0-9]{1,10}", cik):
        return {"error": "Invalid CIK"}

    if permaticker and not re.fullmatch(r"[0-9]+", permaticker):
        return {"error": "Invalid permaticker"}

    if not 1 <= limit <= 100:
        return {"error": "Limit must be between 1 and 100"}

    api_key = os.environ.get("SHARADAR_API_KEY")
    if not api_key:
        return {"error": "Sharadar API key is not configured"}

    params = {
        "format": "json",
        "table": "fundamentals",
        "api_key": api_key,
    }

    if ticker:
        params["ticker"] = ticker

    if permaticker:
        params["permaticker"] = permaticker

    url = "https://api.sharadar.com/v1.0/data/tickers"

    matches = []
    scanned = 0
    page_size = 1000
    max_pages = 50
    exhausted = False

    try:
        with httpx.Client(timeout=30.0) as client:
            for page_number in range(max_pages):
                params["limit"] = page_size
                params["skip"] = page_number * page_size

                response = client.get(url, params=params)
                response.raise_for_status()
                page = response.json()

                if not isinstance(page, dict):
                    return {
                        "error": "Unexpected TICKERS response",
                        "records_scanned": scanned,
                        "complete": False,
                    }

                rows = page.get("data")
                if not isinstance(rows, list):
                    return {
                        "error": "Invalid TICKERS data structure",
                        "records_scanned": scanned,
                        "complete": False,
                    }

                scanned += len(rows)

                for row in rows:
                    if not isinstance(row, dict):
                        continue

                    if name:
                        issuer = str(row.get("name") or "")
                        if name.casefold() not in issuer.casefold():
                            continue

                    if cik:
                        sec_url = str(row.get("secfilings") or "")
                        found = re.search(
                            r"(?:CIK=|/data/)([0-9]{1,10})(?:[^0-9]|$)",
                            sec_url,
                            flags=re.IGNORECASE,
                        )
                        if not found:
                            continue

                        if int(found.group(1)) != int(cik):
                            continue

                    matches.append(row)

                if len(rows) < page_size:
                    exhausted = True
                    break

        return {
            "source": "Sharadar TICKERS",
            "data": {
                "count": min(len(matches), limit),
                "data": matches[:limit],
            },
            "records_scanned": scanned,
            "total_matches_found": len(matches),
            "complete": exhausted,
            "results_truncated": len(matches) > limit,
            "cik_verification": (
                "Matched against SEC filings URL"
                if cik else "Not requested"
            ),
        }

    except httpx.HTTPStatusError as exc:
        return {
            "error": "Sharadar TICKERS request failed",
            "status_code": exc.response.status_code,
            "records_scanned": scanned,
            "complete": False,
        }

    except (httpx.RequestError, ValueError):
        return {
            "error": "Unable to retrieve TICKERS data",
            "records_scanned": scanned,
            "complete": False,
        }


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
