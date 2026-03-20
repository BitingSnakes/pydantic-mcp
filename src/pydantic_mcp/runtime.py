from __future__ import annotations

import logging

from fastmcp import FastMCP

from .constants import SERVER_INSTRUCTIONS, SERVER_NAME, SERVER_VERSION
from .helpers import ErrorHistory, RegistryCache
from .settings import load_server_settings

SERVER_SETTINGS = load_server_settings()
logger = logging.getLogger(__name__)

mcp = FastMCP(
    SERVER_NAME,
    instructions=SERVER_INSTRUCTIONS,
    version=SERVER_VERSION,
    website_url="https://github.com/BitingSnakes/pydantic-mcp",
    mask_error_details=SERVER_SETTINGS.mask_error_details,
    strict_input_validation=SERVER_SETTINGS.strict_input_validation,
)

REGISTRY = RegistryCache(SERVER_SETTINGS)
ERROR_HISTORY = ErrorHistory(SERVER_SETTINGS.record_error_history_limit)
