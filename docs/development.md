# 开发指南

## 本地开发环境

```bash
git clone https://github.com/yanchuanjiu/ai-assistant.git
cd ai-assistant

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 填写 .env（至少填 VOLCENGINE_API_KEY 或 OPENROUTER_API_KEY）

python main.py
```

## 如何新增工具（技能）

所有工具在 `graph/tools.py` 中注册。新增步骤：

**1. 在 `tools.py` 添加函数**

```python
from langchain_core.tools import tool

@tool
def my_new_tool(param: str) -> str:
    """工具描述：Agent 会根据这段描述决定何时调用。param: 参数说明。"""
    # 实现逻辑
    return "结果"
```

**2. 加入 TOOL_CATEGORIES 对应分类**

```python
# 按工具用途选择合适的分类（meeting/feishu_wiki/feishu_advanced/claude/dingtalk_mcp）
TOOL_CATEGORIES["meeting"] = [
    ...
    my_new_tool,   # 加在这里
]
```

**3. 同步更新 CATEGORY_KEYWORDS（如需新触发词）**

```python
CATEGORY_KEYWORDS["meeting"] = [
    "会议", "纪要", ...,
    "my_keyword",   # 加在这里
]
```

完成，无需修改其他文件。Agent 下次启动会自动识别新工具。

> **注意**：若工具需要每次都可用，加入 `CORE_TOOLS` 而非 `TOOL_CATEGORIES`。

## 如何新增集成平台

以新增"企业微信"为例：

```
integrations/
└── wecom/
    ├── __init__.py
    ├── client.py    # Token 管理 + 基础请求
    └── bot.py       # Webhook 接收 + 消息发送（FastAPI router）
```

在 `main.py` 注册 supervised thread：

```python
threads = [
    ...
    threading.Thread(target=_supervised("wecom-ws", wecom_start), daemon=True),
]
```

在 `graph/nodes.py` 的 `respond_node` 加分支：

```python
elif platform == "wecom":
    from integrations.wecom.bot import WeComBot
    WeComBot().send_text(user_id=chat_id, text=content)
```

## 自迭代开发工作流

通过机器人对话触发 Claude Code 自动开发：

```
你：帮我加一个工具，每天早8点总结昨天钉钉文档的内容发给我

Agent → trigger_self_iteration(
  requirement="新增定时任务：每天08:00从钉钉文档拉取
  前一天更新的文件，用LLM总结后发送到飞书机器人..."
)

Claude Code → 自动修改 scheduler.py + graph/tools.py
           → 返回修改摘要
Agent → 汇报结果给你
```

**注意**：自迭代后需要重启服务才能加载新代码：

```bash
# 手动重启（当前阶段）
Ctrl+C → python main.py

# 未来可让 Agent 自动触发重启（加入白名单命令）
```

## 回归测试

`tests/regression/` 是功能回归测试套件，确保每次迭代后已有能力不被破坏。

```bash
source .venv/bin/activate

# 运行全部套件
python tests/regression/run_all.py

# 单独运行某套件
python tests/regression/run_all.py feishu    # 飞书知识库（14用例）
python tests/regression/run_all.py dingtalk  # 钉钉 MCP（8用例）
python tests/regression/run_all.py e2e       # 端到端流水线（11用例）

# 标准 pytest 命令（同样有效）
python -m pytest tests/regression/ -v
```

**测试分类原则（问题分类方法论）**：

| 测试类型 | 用途 | 示例 |
|---------|------|------|
| 回归测试（`tests/regression/`） | 验证系统调用、API 成功/失败、数据格式 | API 返回 200、token 非空、结果含指定字段 |
| 手动场景测试 | 验证 LLM 选择工具是否正确、回复是否符合预期 | 发"搜索钉钉文档" → 触发 `search_documents` |

> **代码问题**（API 失败、参数错误、Python 异常）→ 修 `integrations/`、写回归测试
> **提示词/技能问题**（LLM 选错工具、理解歧义）→ 修 `prompts/system.md` 或工具 docstring，手动测试验证

**注意**：`TestAnalyze` 类因 LLM 超时会自动 skip（`pytest.skip`），属预期行为，不影响套件结果。

## 代码规范

- **语言**：Python 3.11+，类型注解尽量完整
- **日志**：使用 `logging`，不用 `print`
- **配置**：新配置项通过 `pydantic-settings` + `.env` 管理
- **错误处理**：集成层的失败不应 crash 整个 agent，用 try/except 兜住并返回错误描述
- **工具描述**：`@tool` docstring 要清晰，这是 LLM 判断是否调用的依据

## 分支策略

```
main          生产分支，直接部署到服务器
feat/xxx      新功能开发
fix/xxx       Bug 修复
```

自迭代产生的代码直接提交到 `main`（因为是个人项目，无 CI 要求）。

## 添加新依赖

```bash
pip install new-package
pip freeze | grep new-package >> requirements.txt
# 或手动编辑 requirements.txt 加入版本约束
```

## 调试技巧

**查看 Agent 决策过程**：

设置 `LOG_LEVEL=DEBUG` 可看到每次 LLM 调用和工具执行的详细日志。

**单独测试工具**：

```python
# 在项目根目录
from dotenv import load_dotenv; load_dotenv()
from graph.tools import read_feishu_knowledge
print(read_feishu_knowledge.invoke({"query": "会议"}))
```

**测试飞书 API**：

```bash
python -m tools.list_feishu_spaces
```

**测试邮件连接**：

```python
from dotenv import load_dotenv; load_dotenv()
from integrations.email.imap_client import IMAPPoller
emails = IMAPPoller().fetch_unread()
print(f"未读邮件: {len(emails)} 封")
```
