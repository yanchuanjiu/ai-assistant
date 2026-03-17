"""钉钉 API 基础客户端：Token 管理 + 通用请求。"""
import time
import logging
import httpx
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)
DINGTALK_BASE = "https://api.dingtalk.com"
DINGTALK_OAPI = "https://oapi.dingtalk.com"


class DingTalkSettings(BaseSettings):
    dingtalk_client_id: str = ""
    dingtalk_client_secret: str = ""
    dingtalk_agent_id: str = ""
    dingtalk_docs_space_id: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


_settings = DingTalkSettings()
_token_cache: dict = {"token": None, "expires_at": 0}


def get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    resp = httpx.post(
        f"{DINGTALK_BASE}/v1.0/oauth2/accessToken",
        json={
            "appKey": _settings.dingtalk_client_id,
            "appSecret": _settings.dingtalk_client_secret,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["accessToken"]
    _token_cache["expires_at"] = now + data.get("expireIn", 7200)
    return _token_cache["token"]


def dt_get(path: str, params: dict = None, base: str = DINGTALK_BASE) -> dict:
    token = get_access_token()
    resp = httpx.get(
        f"{base}{path}",
        headers={"x-acs-dingtalk-access-token": token},
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def dt_post(path: str, json: dict = None, base: str = DINGTALK_BASE) -> dict:
    token = get_access_token()
    resp = httpx.post(
        f"{base}{path}",
        headers={"x-acs-dingtalk-access-token": token},
        json=json,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
