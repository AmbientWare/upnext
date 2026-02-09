"""API routes."""

from fastapi import APIRouter
from shared.schemas import (
    ApiInfo,
    ApiOverview,
    ApisListResponse,
    ApiTrendHour,
    ApiTrendsResponse,
)

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
from server.routes.apis.apis_utils import build_docs_url, parse_api_request_event

APIS_PREFIX = "/apis"

router = APIRouter(tags=["apis"])
router.include_router(api_stream_router, prefix=APIS_PREFIX)
router.include_router(api_root_router, prefix=APIS_PREFIX)

__all__ = [
    "APIS_PREFIX",
    "ApiInfo",
    "ApiOverview",
    "ApiTrendHour",
    "ApiTrendsResponse",
    "ApisListResponse",
    "build_docs_url",
    "parse_api_request_event",
    "api_root_router",
    "api_stream_router",
    "get_api",
    "get_api_trends",
    "get_endpoint",
    "list_api_request_events",
    "list_apis",
    "list_endpoints",
    "router",
    "stream_api",
    "stream_api_request_events",
    "stream_api_trends",
    "stream_apis",
]
