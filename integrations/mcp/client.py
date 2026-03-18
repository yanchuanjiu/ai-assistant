"""
MCP 客户端：连接远程 Streamable-HTTP MCP Server，将工具转换为同步可用的 LangChain 工具。

使用 background asyncio event loop 让同步的 LangGraph tools_node 调用异步 MCP 工具。
每次工具调用会创建一个新的 HTTP 会话（stateless，适合 streamable-http 服务）。
"""
import asyncio
import logging
import threading
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

logger = logging.getLogger(__name__)

# 全局后台 event loop（用于在同步上下文中运行异步 MCP 调用）
_bg_loop: asyncio.AbstractEventLoop | None = None
_bg_thread: threading.Thread | None = None
_loop_lock = threading.Lock()


def _start_background_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _get_loop() -> asyncio.AbstractEventLoop:
    """获取（或创建）后台 event loop，线程安全。"""
    global _bg_loop, _bg_thread
    if _bg_loop is not None and _bg_loop.is_running():
        return _bg_loop
    with _loop_lock:
        if _bg_loop is not None and _bg_loop.is_running():
            return _bg_loop
        _bg_loop = asyncio.new_event_loop()
        _bg_thread = threading.Thread(
            target=_start_background_loop, args=(_bg_loop,), daemon=True
        )
        _bg_thread.start()
        # 等待 loop 启动
        import time
        for _ in range(100):
            if _bg_loop.is_running():
                break
            time.sleep(0.01)
    return _bg_loop


def _run_async(coro, timeout: int = 60) -> Any:
    """在后台 event loop 中同步执行异步协程。"""
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def _wrap_as_sync(mcp_tool: BaseTool) -> StructuredTool:
    """
    将异步 MCP tool（langchain_mcp_adapters 生成）包装为同步 StructuredTool。

    MCP tool 的 response_format="content_and_artifact"，ainvoke 返回 (content, artifact)。
    content 是 list[TextContentBlock | ImageContentBlock | ...]，提取文本后返回字符串。
    """
    tool_name = mcp_tool.name
    tool_desc = mcp_tool.description
    tool_schema = mcp_tool.args_schema

    def sync_fn(**kwargs) -> str:
        try:
            result = _run_async(mcp_tool.ainvoke(kwargs))
            # content_and_artifact format → (content_list, artifact)
            if isinstance(result, tuple) and len(result) == 2:
                content, _ = result
                if isinstance(content, list):
                    texts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            texts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            texts.append(block)
                    return "\n".join(t for t in texts if t)
                return str(content)
            return str(result)
        except Exception as e:
            logger.error(f"[MCP:{tool_name}] 调用失败: {e}")
            return f"工具调用失败：{e}"

    return StructuredTool(
        name=tool_name,
        description=tool_desc,
        func=sync_fn,
        args_schema=tool_schema,
    )


def load_mcp_tools(url: str, server_name: str = "mcp_server") -> list[BaseTool]:
    """
    连接指定 Streamable-HTTP MCP Server，返回同步可用的 LangChain 工具列表。

    Args:
        url: MCP server 的 streamable-http URL（含 key 等认证参数）
        server_name: 服务标识名（仅用于日志）

    Returns:
        可直接用于同步 LangGraph agent 的 StructuredTool 列表。
        连接失败时返回空列表，不抛出异常。
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(
            {server_name: {"transport": "streamable_http", "url": url}}
        )
        # get_tools() 打开一次临时会话拉取工具列表，工具调用时各自独立创建会话
        async_tools = _run_async(client.get_tools(), timeout=30)
        sync_tools = [_wrap_as_sync(t) for t in async_tools]
        logger.info(
            f"[MCP] {server_name} 已加载 {len(sync_tools)} 个工具: "
            f"{[t.name for t in sync_tools]}"
        )
        return sync_tools
    except Exception as e:
        logger.warning(f"[MCP] {server_name} 加载失败（跳过）: {e}")
        return []
