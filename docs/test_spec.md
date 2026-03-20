# 测试脚本规范文档
> AI 优化场景自动化测试 — v1.0.0 · 2026-03-20

---

## 1. 目录结构

```
tests/ai_scenarios/
├── __init__.py
├── conftest.py              # 公共 fixtures，环境加载
├── test_color_value.py      # 场景一：染发色值还原偏差
├── test_live_stream.py      # 场景二：直播数字人抖音适配
├── test_cross_platform.py   # 场景三：跨平台兼容性 + 模型监控
├── test_cases.json          # 测试用例库（JSON 格式）
└── run_ai_scenarios.py      # CLI 测试运行入口
.github/workflows/
└── ai_scenarios_ci.yml      # GitHub Actions CI 配置
reports/ai_scenarios/        # 测试报告输出目录（自动生成）
```

---

## 2. 命名规范

### 2.1 文件命名

| 类型 | 规则 | 示例 |
|------|------|------|
| 测试文件 | `test_{场景名}.py` | `test_color_value.py` |
| 测试类 | `Test{场景+功能}` | `TestColorValueBasic` |
| 测试方法 | `test_{动词}_{条件}` | `test_delta_e_within_threshold` |
| Fixture | 名词或名词短语 | `mock_monitor`, `color_test_cases` |

### 2.2 用例 ID 规范

```
TC-{场景码}-{序号：两位}
```

| 场景码 | 对应测试 |
|--------|---------|
| `COL`  | 色值还原 |
| `LIVE` | 直播数字人 |
| `PLAT` | 跨平台 / 模型监控 |

示例：`TC-COL-01`、`TC-LIVE-03`、`TC-PLAT-05`

---

## 3. 脚本结构规范

每个测试方法必须包含以下四节（以 docstring 形式）：

```python
def test_功能名称(self, fixture):
    """
    TC-XXX-YY：用例标题
    前置条件：描述运行此测试所需的数据/环境
    执行步骤：描述测试操作流程
    断言逻辑：描述如何判断通过/失败（含量化指标）
    """
    # 1. Arrange — 准备数据和 Mock
    ...
    # 2. Act — 执行被测逻辑
    ...
    # 3. Assert — 断言结果
    assert result == expected, f"详细失败信息，含实际值和期望值"
```

---

## 4. 参数化方法

复数场景使用 `@pytest.mark.parametrize` 替代循环：

```python
# ✅ 正确：参数化，每个用例独立报告
@pytest.mark.parametrize("name,true_rgb,ai_rgb,max_delta_e", [
    ("自然黑", (25, 20, 18), (28, 22, 20), 5.0),
    ("栗色",   (100, 55, 40), (98, 57, 42), 5.0),
])
def test_delta_e_within_threshold(self, name, true_rgb, ai_rgb, max_delta_e):
    ...

# ❌ 错误：循环，一个断言失败会跳过后续
def test_all_colors(self):
    for name, true_rgb, ai_rgb, threshold in COLOR_PATCHES:
        ...
```

---

## 5. 日志打印格式

所有 `print()` 输出遵循以下格式（便于 CI 日志追踪）：

```python
# 数值指标（带单位）
print(f"  {指标名}：{值}{单位}（阈值={阈值}）")
# 示例：
print(f"  色差 ΔE：{delta_e:.2f}（阈值=5.0）")
print(f"  P95 时延：{p95}ms（阈值=3000ms）")

# 警告
print(f"  ⚠️  {警告内容}")

# 状态汇总
print(f"  {通过数}/{总数} = {通过率:.1%}")
```

---

## 6. Mock 与真实 API 切换

```python
# 测试文件头部标注 API 状态
class ColorRestorationAPI:
    """商汤染发色值还原 API — 当前为 STUB 模式
    接入真实 API：替换 analyze() 方法为 requests.post 调用
    环境变量：SENSETIME_API_KEY, SENSETIME_API_BASE
    """
    ...

# CI 中通过 pytest.skip 优雅跳过
@pytest.fixture(scope="session")
def sensetime_api_key():
    key = os.getenv("SENSETIME_API_KEY", "")
    if not key:
        pytest.skip("SENSETIME_API_KEY 未配置，跳过需要真实 API 的用例")
    return key
```

---

## 7. 异常处理规范

### 7.1 重试机制（API 类）

```python
import time

def call_with_retry(fn, max_retries=2, backoff_s=1.0):
    """API 调用重试，指数退避"""
    for attempt in range(max_retries):
        try:
            return fn()
        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt == max_retries - 1:
                raise
            wait = backoff_s * (2 ** attempt)
            print(f"  重试 {attempt+1}/{max_retries}，等待 {wait}s：{e}")
            time.sleep(wait)
```

### 7.2 元素定位失败（UI 类）

```python
# Playwright 示例
async def safe_click(page, selector: str, timeout_ms=5000):
    """带重试的元素点击"""
    try:
        await page.click(selector, timeout=timeout_ms)
    except TimeoutError:
        # 截图保存到 reports/screenshots/
        await page.screenshot(path=f"reports/screenshots/fail_{time.time()}.png")
        raise
```

---

## 8. 测试标签（Markers）

在 `pytest.ini` / `pyproject.toml` 中注册：

```ini
[pytest]
markers =
    smoke: 冒烟测试，每次推送必跑，< 2min
    color_basic: 色值还原基础用例
    color_boundary: 色值边界/异常用例
    stream_spec: 推流规格合规检查
    reliability: 稳定性/重试/熔断测试
    lipsync: 嘴形同步检测
    cross_platform: 跨平台一致性
    model_monitor: 模型性能监控
    docker: 容器化测试（需 Docker 环境）
    regression: 回归防守（精度/行为不得倒退）
```

---

## 9. 测试用例库（test_cases.json）管理

```json
{
  "{场景名}": [
    {
      "id": "TC-XXX-YY",
      "title": "用例标题",
      "priority": "P0|P1|P2",
      "input": { ... },
      "expected": { ... },
      "tags": ["smoke", "scenario_tag"]
    }
  ]
}
```

**优先级定义**：
- `P0`：核心路径，必须通过，否则阻塞发布
- `P1`：重要场景，失败触发告警但不阻塞
- `P2`：边界/降级场景，失败记录 warning

---

## 10. 运行方式速查

```bash
# 本地运行（需在项目根目录，激活 venv）
cd /root/ai-assistant
source .venv/bin/activate

# 运行全部 AI 场景测试
python tests/ai_scenarios/run_ai_scenarios.py

# 只跑色值场景
python tests/ai_scenarios/run_ai_scenarios.py color

# 只跑 smoke 标签
python tests/ai_scenarios/run_ai_scenarios.py --smoke

# 生成 Allure 报告
python tests/ai_scenarios/run_ai_scenarios.py --allure
allure serve reports/ai_scenarios/allure_results/

# 直接用 pytest（更灵活）
pytest tests/ai_scenarios/ -v -m "not docker"
pytest tests/ai_scenarios/test_color_value.py::TestColorValueBasic -v
```

---

## 11. CI 集成（GitHub Actions）

| Job | 触发条件 | 耗时目标 |
|-----|---------|---------|
| `smoke-test` | 每次 push | < 2 min |
| `full-regression` | PR + 每日 00:00 UTC | < 30 min |
| `publish-allure` | 全量回归完成后 | < 5 min |
| `notify-on-failure` | 任意 job 失败 | < 1 min |

**报告查看**：
- Allure 报告发布到 GitHub Pages（需在 repo Settings > Pages 配置）
- JUnit XML 在 Actions 页面 Artifacts 下载

---

## 12. 扩展新场景步骤

1. 在 `tests/ai_scenarios/` 新增 `test_{新场景}.py`
2. 在 `test_cases.json` 添加 `{新场景}` 节点
3. 在 `run_ai_scenarios.py` 的 `SUITE_MAP` 添加映射
4. 在 `ai_scenarios_ci.yml` 的 `matrix.suite` 添加新场景
5. 更新本文档和 `CLAUDE.md`

---

## 13. 依赖清单

```
pytest>=7.4.0          # 测试框架
pytest-xdist>=3.3      # 并行执行（-n auto）
allure-pytest>=2.13    # Allure 报告（可选）
numpy>=1.24            # 数值计算
opencv-python>=4.8     # 图像处理（可选，需要图像识别时启用）
requests>=2.31         # API 调用
python-dotenv>=1.0     # 环境变量加载
```

安装：
```bash
pip install pytest pytest-xdist allure-pytest numpy requests python-dotenv
# 可选（图像场景）：
pip install opencv-python-headless
```
