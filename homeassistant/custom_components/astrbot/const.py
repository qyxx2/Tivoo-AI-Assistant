"""Constants for the AstrBot Conversation Agent integration."""

from datetime import timedelta

DOMAIN = "astrbot"

CONF_BASE_URL = "base_url"
CONF_API_KEY = "api_key"
CONF_API_KEY_ID = "api_key_id"

API_KEY_USERNAME_PREFIX = "api_key:"
SESSION_STORE_KEY = "astrbot_session"
SESSION_STORE_VERSION = 1
SESSION_DATA_VERSION = 1
SESSION_TTL = timedelta(hours=24)
