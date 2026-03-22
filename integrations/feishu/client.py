"""飞书 API 基础客户端：Token 管理 + 通用请求。

设计原则（参考 OpenClaw uat-client.js / tool-client.js）：
- feishu_call() 是统一入口：自动选 user/tenant token，access_token 过期时刷新后重试一次
- 业务错误码翻译为结构化异常，不向上暴露 HTTP 细节
- Token 管理完全在本层，工具层和 knowledge 层无需关心续期
"""
import os
import re
import time
import logging
import threading
import httpx
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)
FEISHU_BASE = "https://open.feishu.cn/open-apis"

# ---------------------------------------------------------------------------
# 飞书 API 错误码常量（来源：飞书官方文档 + OpenClaw auth-errors.js）
# ---------------------------------------------------------------------------

# access_token 失效，可尝试刷新后重试（官方文档 99991668/99991677）
TOKEN_RETRY_CODES: frozenset[int] = frozenset([
    99991668,   # "Invalid access token for authorization" — token过期或类型错误
    99991677,   # "token expire" — user token 已过期
])

# refresh_token 不可恢复，必须重新完整 OAuth（官方 v2 文档错误码）
REFRESH_TOKEN_IRRECOVERABLE: frozenset[int] = frozenset([
    20024,   # token 与 client_id 不匹配
    20037,   # refresh_token 已过期（365天有效期）
    20064,   # token 已被撤销（单次使用后失效）
    20074,   # 应用未开启 token 刷新功能
])

# 应用/用户权限问题（需管理员或用户操作，非代码问题）
APP_SCOPE_ERROR_CODES: frozenset[int] = frozenset([
    99991672,   # 应用 API scope 缺失，需管理员在开放平台开通
    99991679,   # user token scope 不足，需用户重新 OAuth 授权
])


# ---------------------------------------------------------------------------
# 异常类型（参考 OpenClaw auth-errors.js，适配单用户场景）
# ---------------------------------------------------------------------------

class FeishuAuthError(RuntimeError):
    """所有飞书认证/授权错误的基类。"""


class UserTokenNotConfiguredError(FeishuAuthError):
    """user token 完全未配置（.env 中无任何 token）。
    区别于 token 已过期：未配置 → 需初次 OAuth；已过期 → 需刷新。
    """


class UserTokenExpiredError(FeishuAuthError):
    """refresh_token 不可恢复（已过期/已撤销/未启用），必须重新完整 OAuth 授权。

    工具层捕获此异常 → 通过 IM 通知用户，返回一句话给 LLM。
    """
    def __init__(self, msg: str, error_code: int = 0):
        super().__init__(msg)
        self.error_code = error_code


class WikiPermissionError(FeishuAuthError):
    """Wiki 空间权限不足（error 131006）。
    根因：应用未被添加为 wiki 空间成员，或 user token 未配置/失效。
    这是管理员配置问题，OAuth 流程解决不了。
    工具层捕获此异常 → 通知用户，不走 OAuth 流程。
    """


class AppScopeError(FeishuAuthError):
    """应用 API 权限 scope 缺失（99991672）或 user scope 不足（99991679）。
    需管理员在飞书开放平台开通对应权限后重新发布，或用户重新授权。
    """


# ---------------------------------------------------------------------------
# 配置 + 缓存
# ---------------------------------------------------------------------------

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

# 5分钟提前刷新窗口（参考 OpenClaw token-store.js REFRESH_AHEAD_MS）
_REFRESH_AHEAD_SECS = 5 * 60


# ---------------------------------------------------------------------------
# Token 状态判断
# ---------------------------------------------------------------------------

def _user_token_status(token: str, expires_at: float) -> str:
    """判断 user token 状态。

    Returns: "valid" | "needs_refresh" | "expired" | "missing"
    """
    if not token:
        return "missing"
    now = time.time()
    if now < expires_at - _REFRESH_AHEAD_SECS:
        return "valid"
    if now < expires_at:
        return "needs_refresh"
    return "expired"


# ---------------------------------------------------------------------------
# Tenant Access Token
# ---------------------------------------------------------------------------

def get_tenant_access_token() -> str:
    """获取 tenant_access_token，内存缓存60秒提前刷新。"""
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


# ---------------------------------------------------------------------------
# User Access Token（含自动续期）
# ---------------------------------------------------------------------------

def _update_env_user_token(token: str, refresh_token: str, expires_at: float,
                            refresh_expires_at: float = 0):
    """将新 user token 写回 .env 文件持久化。"""
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


def _do_refresh_token(refresh_token: str) -> dict:
    """调用官方 v2 端点刷新 access_token。

    使用 POST /authen/v2/oauth/token（client_id/client_secret 在请求体中）。
    这是飞书官方当前推荐的 token 刷新方式。

    Returns: 包含 access_token, refresh_token, expires_in 等字段的 dict
    Raises:
      UserTokenExpiredError — refresh_token 不可恢复（20024/20037/20064/20074）
      RuntimeError          — 其他刷新失败（临时错误）
    """
    resp = httpx.post(
        f"{FEISHU_BASE}/authen/v2/oauth/token",
        json={
            "grant_type": "refresh_token",
            "client_id": _settings.feishu_app_id,
            "client_secret": _settings.feishu_app_secret,
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    biz_code = data.get("code", 0)
    if biz_code != 0:
        if biz_code in REFRESH_TOKEN_IRRECOVERABLE:
            raise UserTokenExpiredError(
                f"refresh_token 不可恢复（code={biz_code}: {data.get('msg', '')}），"
                f"需要重新 OAuth 授权。",
                error_code=biz_code,
            )
        raise RuntimeError(
            f"token 刷新失败（code={biz_code}: {data.get('msg', '')}），"
            f"可能是临时错误，可稍后重试。"
        )

    new_token = data.get("access_token", "")
    if not new_token:
        raise RuntimeError(f"刷新响应中无 access_token: {data}")

    return data


def get_user_access_token() -> str:
    """获取有效的 user_access_token，必要时自动刷新（线程安全）。

    状态机（参考 OpenClaw getValidAccessToken）：
      missing       → raise UserTokenNotConfiguredError
      valid         → 直接返回（快速路径）
      needs_refresh → 加锁刷新（提前5分钟，防止临界点失效）
      expired       → 加锁刷新（已过期但 refresh_token 可能仍有效）

    刷新结果：
      成功               → 更新缓存 + .env，返回新 token
      REFRESH_IRRECOVERABLE → raise UserTokenExpiredError（需重新 OAuth）
      其他错误           → raise RuntimeError（临时错误）
    """
    now = time.time()

    # 快速路径：内存缓存有效
    cached_token = _user_token_cache["token"]
    cached_expires = _user_token_cache["expires_at"]
    if cached_token and _user_token_status(cached_token, cached_expires) == "valid":
        return cached_token

    token = os.getenv("FEISHU_USER_ACCESS_TOKEN", "")
    refresh_token = os.getenv("FEISHU_USER_REFRESH_TOKEN", "")
    expires_at = float(os.getenv("FEISHU_USER_TOKEN_EXPIRES_AT", "0"))

    if not token and not refresh_token:
        raise UserTokenNotConfiguredError(
            "FEISHU_USER_ACCESS_TOKEN / FEISHU_USER_REFRESH_TOKEN 均未配置，需初次 OAuth 授权。"
        )

    # 手动配置 token 但未设过期时间，视为从现在起 ~2小时有效
    if token and expires_at == 0:
        expires_at = now + 7100
        os.environ["FEISHU_USER_TOKEN_EXPIRES_AT"] = str(int(expires_at))

    status = _user_token_status(token, expires_at)
    if status == "valid":
        _user_token_cache.update({"token": token, "expires_at": expires_at})
        return token

    if not refresh_token:
        raise UserTokenNotConfiguredError(
            "access_token 已过期且 refresh_token 未配置，无法自动续期。"
        )

    # 需要刷新 — 加锁防并发竞争（refresh_token 单次使用，并发会导致第二次失败）
    with _user_token_refresh_lock:
        # 双重检查：可能其他线程已完成刷新
        now = time.time()
        if _user_token_cache["token"] and _user_token_status(
            _user_token_cache["token"], _user_token_cache["expires_at"]
        ) == "valid":
            return _user_token_cache["token"]

        # 重新读取（其他线程可能已写回 os.environ）
        refresh_token = os.getenv("FEISHU_USER_REFRESH_TOKEN", "")
        token = os.getenv("FEISHU_USER_ACCESS_TOKEN", "")
        expires_at = float(os.getenv("FEISHU_USER_TOKEN_EXPIRES_AT", "0"))

        if token and _user_token_status(token, expires_at) == "valid":
            _user_token_cache.update({"token": token, "expires_at": expires_at})
            return token

        # 调用 v2 刷新（_do_refresh_token 会按错误码精确抛出异常）
        data = _do_refresh_token(refresh_token)
        new_token = data["access_token"]
        new_refresh = data.get("refresh_token", refresh_token)
        new_expires_at = now + data.get("expires_in", 7200)
        new_refresh_expires_at = (
            now + data["refresh_token_expires_in"]
            if data.get("refresh_token_expires_in")
            else 0
        )

        _user_token_cache.update({"token": new_token, "expires_at": new_expires_at})
        os.environ["FEISHU_USER_ACCESS_TOKEN"] = new_token
        os.environ["FEISHU_USER_REFRESH_TOKEN"] = new_refresh
        os.environ["FEISHU_USER_TOKEN_EXPIRES_AT"] = str(int(new_expires_at))
        if new_refresh_expires_at > 0:
            os.environ["FEISHU_USER_REFRESH_EXPIRES_AT"] = str(int(new_refresh_expires_at))
        _update_env_user_token(new_token, new_refresh, new_expires_at, new_refresh_expires_at)
        logger.info("[user_token] 已自动续期（v2 端点）并写回 .env")
        return new_token


def invalidate_user_token_cache():
    """强制清空内存 token 缓存。下次调用 get_user_access_token() 会重新读取并刷新。"""
    _user_token_cache["token"] = None
    _user_token_cache["expires_at"] = 0


# ---------------------------------------------------------------------------
# 业务错误码 → 结构化异常
# ---------------------------------------------------------------------------

def _raise_for_biz_code(code: int, data: dict, path: str = ""):
    """将飞书业务错误码翻译为结构化异常（不向上暴露原始 HTTP/JSON 细节）。"""
    msg = data.get("msg", "")
    if code == 131006:
        raise WikiPermissionError(
            f"wiki 空间权限不足（131006）：应用需要被 wiki 空间管理员添加为成员，"
            f"或配置 user_access_token。"
        )
    if code in APP_SCOPE_ERROR_CODES:
        raise AppScopeError(
            f"API 权限不足（code={code}）：{'应用缺少 scope，需管理员在开放平台开通后重新发布' if code == 99991672 else 'user token scope 不足，需重新 OAuth 授权'}。"
            f" path={path}"
        )
    raise RuntimeError(f"飞书 API 错误 code={code} msg={msg} path={path}")


# ---------------------------------------------------------------------------
# feishu_call() — 统一调用入口（参考 OpenClaw callWithUAT）
# ---------------------------------------------------------------------------

def feishu_call(
    path: str,
    method: str = "GET",
    json_body: dict = None,
    params: dict = None,
    as_: str = "user",
) -> dict:
    """统一飞书 API 调用入口。

    自动处理（参考 OpenClaw callWithUAT + rethrowStructuredError）：
    1. 根据 as_ 选择 user / tenant token
    2. access_token 过期（TOKEN_RETRY_CODES）→ 刷新后重试一次
    3. 业务错误码翻译为结构化异常

    Args:
      path      — API 路径，如 "/wiki/v2/spaces/{id}/nodes"
      method    — HTTP 方法（GET/POST/PUT/DELETE/PATCH）
      json_body — 请求体（JSON）
      params    — 查询参数
      as_       — "user"（user_access_token）| "tenant"（tenant_access_token）

    Returns: 飞书 API 响应 dict（已确保 code=0）

    Raises:
      UserTokenNotConfiguredError — user token 未配置
      UserTokenExpiredError       — refresh_token 不可恢复
      WikiPermissionError         — 131006 wiki 空间权限
      AppScopeError               — 99991672/99991679 权限 scope
      RuntimeError                — 其他业务错误
      httpx.HTTPStatusError       — HTTP 层 4xx/5xx
    """
    def _do(token: str) -> dict:
        resp = httpx.request(
            method.upper(),
            f"{FEISHU_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=json_body,
            params=params,
            timeout=15,
        )
        _raise_with_body(resp)
        return resp.json()

    token = get_user_access_token() if as_ == "user" else get_tenant_access_token()
    data = _do(token)
    biz_code = data.get("code", 0)

    # access_token 失效 → 刷新后重试一次（参考 OpenClaw callWithUAT retry）
    if biz_code in TOKEN_RETRY_CODES and as_ == "user":
        logger.warning(f"[feishu_call] token 失效（code={biz_code}），刷新后重试: {path}")
        invalidate_user_token_cache()
        token = get_user_access_token()   # 触发刷新
        data = _do(token)
        biz_code = data.get("code", 0)

    if biz_code != 0:
        _raise_for_biz_code(biz_code, data, path)

    return data


# ---------------------------------------------------------------------------
# 向后兼容的旧接口（knowledge.py 迁移期间仍在使用）
# ---------------------------------------------------------------------------

def feishu_get_user(path: str, params: dict = None) -> dict:
    """用 user_access_token 做 GET 请求（旧接口，新代码请用 feishu_call）。"""
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
    """用 user_access_token 做 POST 请求（旧接口，新代码请用 feishu_call）。"""
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
        f"HTTP {resp.status_code} {resp.reason_phrase} | url={resp.url} | body={body}",
        request=resp.request,
        response=resp,
    )


def feishu_get(path: str, params: dict = None) -> dict:
    """tenant_access_token GET（旧接口）。"""
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
    """tenant_access_token DELETE（旧接口）。"""
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
    """tenant_access_token POST（旧接口）。"""
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
