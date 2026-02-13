"""API routes."""

from fastapi import APIRouter
from shared.contracts import ApiInfo, ApiOverview, ApiTrendHour, ApiTrendsResponse

from server.routes.apis.apis_root import (
    api_root_router,
    get_api,
    get_api_trends,
    get_endpoint,
    list_apis,
    list_endpoints,
)
from server.routes.apis.apis_stream import (
    api_stream_router,
    list_api_request_events,
    stream_api,
    stream_api_request_events,
    stream_api_trends,
    stream_apis,
)

APIS_PREFIX = "/apis"

router = APIRouter(tags=["apis"])
router.include_router(api_stream_router, prefix=APIS_PREFIX)
router.include_router(api_root_router, prefix=APIS_PREFIX)

__all__ = [
    "ApiInfo",
    "ApiOverview",
    "ApiTrendHour",
    "ApiTrendsResponse",
    "get_api",
    "get_api_trends",
    "get_endpoint",
    "list_api_request_events",
    "list_apis",
    "list_endpoints",
    "router",
    "stream_api",
    "stream_api_request_events",
    "stream_apis",
    "stream_api_trends",
]
