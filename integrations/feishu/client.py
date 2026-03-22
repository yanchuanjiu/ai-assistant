"""飞书 API 基础客户端：Token 管理 + 通用请求。"""
import os
import re
import time
import logging
import threading
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
_user_token_cache: dict = {"token": None, "expires_at": 0}
_user_token_refresh_lock = threading.Lock()


class UserTokenNotConfiguredError(RuntimeError):
    """用户 token 未配置（区别于 token 已配置但续期失败）。"""


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


def _update_env_user_token(token: str, refresh_token: str, expires_at: float,
                           refresh_expires_at: float = 0):
    """将新 user token 写回 .env 文件。"""
    env_path = ".env"
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()

        def replace_or_append(text, key, value):
            pattern = rf"^{key}=.*$"
            replacement = f"{key}={value}"
            if re.search(pattern, text, re.MULTILINE):
                return re.sub(pattern, replacement, text, flags=re.MULTILINE)
            return text + f"\n{key}={value}"

        content = replace_or_append(content, "FEISHU_USER_ACCESS_TOKEN", token)
        content = replace_or_append(content, "FEISHU_USER_REFRESH_TOKEN", refresh_token)
        content = replace_or_append(content, "FEISHU_USER_TOKEN_EXPIRES_AT", int(expires_at))
        if refresh_expires_at > 0:
            content = replace_or_append(content, "FEISHU_USER_REFRESH_EXPIRES_AT",
                                        int(refresh_expires_at))

        with open(env_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        logger.warning(f"[user_token] 写回 .env 失败: {e}")


def get_user_access_token() -> str:
    """读取 .env 中 FEISHU_USER_ACCESS_TOKEN，过期则用 FEISHU_USER_REFRESH_TOKEN 自动续期。
    续期后将新 token 写回 .env 文件以持久化。
    线程安全：使用 _user_token_refresh_lock 防止并发续期导致 refresh_token 失效。
    """
    now = time.time()
    # 快速路径：缓存未过期，直接返回
    if _user_token_cache["token"] and now < _user_token_cache["expires_at"] - 60:
        return _user_token_cache["token"]

    token = os.getenv("FEISHU_USER_ACCESS_TOKEN", "")
    expires_at = float(os.getenv("FEISHU_USER_TOKEN_EXPIRES_AT", "0"))
    refresh_token = os.getenv("FEISHU_USER_REFRESH_TOKEN", "")

    if not token and not refresh_token:
        raise UserTokenNotConfiguredError(
            "FEISHU_USER_ACCESS_TOKEN / FEISHU_USER_REFRESH_TOKEN 未配置。"
            "请在 .env 中设置，或调用 feishu_oauth_setup 重新授权。"
        )

    # 手动配置 token 但未设置过期时间时，视为从现在起 2 小时有效
    if token and expires_at == 0:
        expires_at = now + 7100
        os.environ["FEISHU_USER_TOKEN_EXPIRES_AT"] = str(int(expires_at))

    if token and now < expires_at - 60:
        _user_token_cache["token"] = token
        _user_token_cache["expires_at"] = expires_at
        return token

    if not refresh_token:
        raise UserTokenNotConfiguredError(
            "FEISHU_USER_REFRESH_TOKEN 未配置，无法续期 user access token。"
            "请在 .env 中设置 FEISHU_USER_REFRESH_TOKEN，或调用 feishu_oauth_setup 重新授权。"
        )

    # 需要续期，加锁防止并发续期（race condition：多线程同时使用同一 refresh_token 导致后续均失败）
    with _user_token_refresh_lock:
        # 双重检查：持有锁后其他线程可能已完成续期
        now = time.time()
        if _user_token_cache["token"] and now < _user_token_cache["expires_at"] - 60:
            return _user_token_cache["token"]

        # 重新从 os.environ 读取（其他线程可能已更新）
        token = os.getenv("FEISHU_USER_ACCESS_TOKEN", "")
        expires_at = float(os.getenv("FEISHU_USER_TOKEN_EXPIRES_AT", "0"))
        refresh_token = os.getenv("FEISHU_USER_REFRESH_TOKEN", "")

        if token and now < expires_at - 60:
            _user_token_cache["token"] = token
            _user_token_cache["expires_at"] = expires_at
            return token

        # 检查 refresh_token 是否已过期
        refresh_expires_at = float(os.getenv("FEISHU_USER_REFRESH_EXPIRES_AT", "0"))
        if refresh_expires_at > 0 and now > refresh_expires_at:
            raise RuntimeError(
                "FEISHU_USER_REFRESH_TOKEN 已过期（30天有效期已到），需要重新 OAuth 授权。\n"
                "请调用 feishu_oauth_setup(action=\"get_auth_url\") 重新授权。"
            )

        # 先获取 app_access_token（OIDC 刷新接口同样需要 app_access_token 作 Bearer）
        app_resp = httpx.post(
            f"{FEISHU_BASE}/auth/v3/app_access_token/internal",
            json={"app_id": _settings.feishu_app_id, "app_secret": _settings.feishu_app_secret},
            timeout=10,
        )
        app_resp.raise_for_status()
        app_token = app_resp.json()["app_access_token"]

        # 优先用 OIDC 接口（/authen/v1/oidc/refresh_access_token），失败再降级到旧接口
        new_token = ""
        new_refresh = refresh_token
        new_expires_at = now + 7200
        new_refresh_expires_at = 0
        last_err = None

        for endpoint in [
            f"{FEISHU_BASE}/authen/v1/oidc/refresh_access_token",
            f"{FEISHU_BASE}/authen/v1/refresh_access_token",
        ]:
            try:
                resp = httpx.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {app_token}"},
                    json={"grant_type": "refresh_token", "refresh_token": refresh_token},
                    timeout=10,
                )
                resp.raise_for_status()
                resp_json = resp.json()
                # 检查飞书业务级错误码（HTTP 200 但 code != 0 表示失败）
                biz_code = resp_json.get("code", 0)
                if biz_code != 0:
                    last_err = RuntimeError(
                        f"refresh_token 续期失败（{endpoint.split('/')[-1]}）："
                        f"code={biz_code} msg={resp_json.get('msg', '')}。"
                        f"refresh_token 可能已失效，需要重新 OAuth 授权。"
                    )
                    continue
                data = resp_json.get("data", resp_json)
                new_token = data.get("access_token", "")
                if not new_token:
                    last_err = RuntimeError(f"续期响应中无 access_token：{resp_json}")
                    continue
                new_refresh = data.get("refresh_token", refresh_token)
                new_expires_at = now + data.get("expires_in", 7200)
                refresh_expires_in = data.get("refresh_expires_in", 0)
                if refresh_expires_in > 0:
                    new_refresh_expires_at = now + refresh_expires_in
                last_err = None
                break
            except httpx.HTTPStatusError as e:
                last_err = e
                continue

        if not new_token:
            raise last_err or RuntimeError("refresh_token 续期失败，原因未知。请重新 OAuth 授权。")

        _user_token_cache["token"] = new_token
        _user_token_cache["expires_at"] = new_expires_at
        os.environ["FEISHU_USER_ACCESS_TOKEN"] = new_token
        os.environ["FEISHU_USER_REFRESH_TOKEN"] = new_refresh
        os.environ["FEISHU_USER_TOKEN_EXPIRES_AT"] = str(int(new_expires_at))
        if new_refresh_expires_at > 0:
            os.environ["FEISHU_USER_REFRESH_EXPIRES_AT"] = str(int(new_refresh_expires_at))
        _update_env_user_token(new_token, new_refresh, new_expires_at, new_refresh_expires_at)
        logger.info("[user_token] 已自动续期并写回 .env")
        return new_token


def feishu_get_user(path: str, params: dict = None) -> dict:
    """用 user_access_token 做 GET 请求。"""
    token = get_user_access_token()
    resp = httpx.get(
        f"{FEISHU_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=15,
    )
    _raise_with_body(resp)
    return resp.json()


def feishu_post_user(path: str, json: dict = None) -> dict:
    """用 user_access_token 做 POST 请求。"""
    token = get_user_access_token()
    resp = httpx.post(
        f"{FEISHU_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=json,
        timeout=15,
    )
    _raise_with_body(resp)
    return resp.json()


def _raise_with_body(resp: httpx.Response) -> None:
    """Raise HTTPStatusError with response body included in the message."""
    if resp.is_success:
        return
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    raise httpx.HTTPStatusError(
        f"Client error '{resp.status_code} {resp.reason_phrase}' for url '{resp.url}' | body={body}",
        request=resp.request,
        response=resp,
    )


def feishu_get(path: str, params: dict = None) -> dict:
    token = get_tenant_access_token()
    resp = httpx.get(
        f"{FEISHU_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=15,
    )
    _raise_with_body(resp)
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
    _raise_with_body(resp)
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
    _raise_with_body(resp)
    return resp.json()
