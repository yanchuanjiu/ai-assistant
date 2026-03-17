"""
Claude Code 会话管理 — 向后兼容的重新导出。

实际实现已迁移至 tmux_session.py（基于 tmux，支持持久化和会话管理）。
"""
from integrations.claude_code.tmux_session import (
    reply_fn_registry,
    session_manager,
    list_active_sessions,
    TmuxClaudeSession as ClaudeCodeSession,
    SessionManager,
)

__all__ = [
    "reply_fn_registry",
    "session_manager",
    "list_active_sessions",
    "ClaudeCodeSession",
    "SessionManager",
]
