"""飞书工具层中间件：统一错误处理装饰器 + IM 通知函数。

职责：
- 捕获 client.py 抛出的结构化认证/权限异常
- 需要用户干预的错误：推送 IM 通知，返回简洁失败消息给 LLM
- token 刷新等透明错误：已在 feishu_call() 层处理，不到达此层
- 其他未知异常：logger.error + 返回"操作失败：{msg}"

此文件属于 integrations/feishu/ 层，graph/tools.py 通过 import 使用而不直接处理异常。
"""
import json
import os
import functools
import logging
import httpx

logger = logging.getLogger(__name__)


def notify_owner_reauth(reason: str = ""):
    """通过飞书 IM 向 owner 发送重新授权通知（使用 tenant_access_token）。

    在 UserTokenExpiredError 被捕获时调用，绕过 LLM 直接通知用户。
    """
    from integrations.feishu.client import get_tenant_access_token, FEISHU_BASE
    try:
        owner_chat_id = os.getenv("OWNER_FEISHU_CHAT_ID", "")
        if not owner_chat_id:
            logger.warning("[notify_owner_reauth] OWNER_FEISHU_CHAT_ID 未配置，无法推送通知")
            return
        text = (
            "⚠️ 飞书 OAuth 授权已失效，需要重新授权\n\n"
            f"原因：{reason or 'refresh_token 已过期或被撤销'}\n\n"
            "请告诉我：「帮我重新授权飞书」，我会生成授权链接。"
        )
        token = get_tenant_access_token()
        httpx.post(
            f"{FEISHU_BASE}/im/v1/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"receive_id_type": "chat_id"},
            json={"receive_id": owner_chat_id, "msg_type": "text",
                  "content": json.dumps({"text": text})},
            timeout=10,
        ).raise_for_status()
        logger.info("[notify_owner_reauth] 重新授权通知已发送")
    except Exception as e:
        logger.error(f"[notify_owner_reauth] 推送通知失败: {e}")


def notify_wiki_permission_issue():
    """通知用户 wiki 空间权限问题（131006）。"""
    from integrations.feishu.client import get_tenant_access_token, FEISHU_BASE
    try:
        owner_chat_id = os.getenv("OWNER_FEISHU_CHAT_ID", "")
        if not owner_chat_id:
            return
        text = (
            "⚠️ 飞书知识库权限问题（131006）\n\n"
            "应用无法访问 wiki 空间，解决方法（三选一）：\n"
            "① 在飞书知识库「空间设置→成员管理」将应用添加为成员\n"
            "② 在 .env 中配置 FEISHU_WIKI_ROOT_NODES\n"
            "③ 告诉我「帮我重新授权飞书」重新配置 user token"
        )
        token = get_tenant_access_token()
        httpx.post(
            f"{FEISHU_BASE}/im/v1/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"receive_id_type": "chat_id"},
            json={"receive_id": owner_chat_id, "msg_type": "text",
                  "content": json.dumps({"text": text})},
            timeout=10,
        ).raise_for_status()
        logger.info("[notify_wiki_permission] 权限问题通知已发送")
    except Exception as e:
        logger.error(f"[notify_wiki_permission] 推送通知失败: {e}")


def feishu_tool(func):
    """飞书工具调用中间件（透明错误处理）。

    捕获 client.py 抛出的结构化认证/权限异常，翻译为 LLM 友好的字符串：
    - UserTokenExpiredError       → 推 IM 通知（owner 重新授权），返回一句话
    - WikiPermissionError         → 推 IM 通知（131006 说明），返回说明文字
    - AppScopeError               → 返回需管理员操作的说明
    - UserTokenNotConfiguredError → 返回需授权的说明
    - 其他异常                    → log + 返回操作失败：{msg}

    注：token 过期自动刷新、降级策略等透明错误已在 feishu_call() 层处理，不会到达此处。

    用法（顺序重要：@tool 在外，@feishu_tool 在内）：
      @tool
      @feishu_tool
      def feishu_xxx(...) -> str:
          ...
    """
    from integrations.feishu.client import (
        UserTokenExpiredError, WikiPermissionError,
        AppScopeError, UserTokenNotConfiguredError,
    )

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except UserTokenExpiredError as e:
            notify_owner_reauth(str(e))
            return (
                "⚠️ 飞书 OAuth 授权已失效（refresh_token 过期/撤销），"
                "已通过飞书消息通知你重新授权，请完成授权后重试。"
            )
        except WikiPermissionError:
            notify_wiki_permission_issue()
            return (
                "⚠️ wiki 空间权限未配置（131006），已通过飞书消息通知你。\n"
                "解决方法（三选一）：\n"
                "① 在飞书知识库「空间设置→成员管理」将应用添加为成员\n"
                "② 在 .env 配置 FEISHU_WIKI_ROOT_NODES\n"
                "③ 告诉我「帮我重新授权飞书」"
            )
        except AppScopeError as e:
            return f"⚠️ 应用 API 权限缺失，需管理员在飞书开放平台开通权限后重新发布应用。详情：{e}"
        except UserTokenNotConfiguredError:
            return "⚠️ 飞书 user token 未配置。请告诉我「帮我授权飞书」开始 OAuth 流程。"
        except Exception as e:
            logger.error(f"[{func.__name__}] {e}", exc_info=True)
            return f"操作失败：{e}"
    return wrapper
