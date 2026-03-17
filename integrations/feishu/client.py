"""飞书 API 基础客户端：Token 管理 + 通用请求。"""
import time
import logging
import httpx
from functools import lru_cache
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)
FEISHU_BASE = "https://open.feishu.cn/open-apis"


class FeishuSettings(BaseSettings):
    feishu_app_id: str = ""
    feishu_app_secret: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


_settings = FeishuSettings()
_token_cache: dict = {"token": None, "expires_at": 0}


def get_tenant_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    resp = httpx.post(
        f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": _settings.feishu_app_id, "app_secret": _settings.feishu_app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = now + data.get("expire", 7200)
    return _token_cache["token"]


def feishu_get(path: str, params: dict = None) -> dict:
    token = get_tenant_access_token()
    resp = httpx.get(
        f"{FEISHU_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def feishu_delete(path: str, json: dict = None) -> dict:
    token = get_tenant_access_token()
    resp = httpx.request(
        "DELETE",
        f"{FEISHU_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=json,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def feishu_post(path: str, json: dict = None, data: dict = None) -> dict:
    token = get_tenant_access_token()
    resp = httpx.post(
        f"{FEISHU_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=json,
        data=data,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
