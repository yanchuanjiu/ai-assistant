"""
Admin Web 配置管理界面。

提供一个轻量 HTTP 服务（默认端口 8080），无需新依赖（使用 Python stdlib）。
访问 http://localhost:8080 即可通过网页管理 agent_config 配置项。

API 端点：
  GET  /api/config          — 列出所有配置
  GET  /api/config/{key}    — 读取单个配置
  POST /api/config          — 写入配置（JSON body: {"key": "...", "value": "..."}）
  DELETE /api/config/{key}  — 删除配置
"""
import json
import logging
import os
import time
import httpx
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, unquote, parse_qs

from integrations.storage import config_store

logger = logging.getLogger(__name__)

# 常用配置项说明（用于前端展示提示）
CONFIG_HINTS = {
    "FEISHU_WIKI_MEETING_PAGE": "飞书会议纪要汇总页面 wiki token（如 Qo4nwLphWiXxx）",
    "FEISHU_WIKI_CONTEXT_PAGE": "AI 助理上下文快照页面 wiki token",
    "FEISHU_WIKI_SPACE_ID": "飞书知识库 Space ID",
    "DINGTALK_DOCS_SPACE_ID": "钉钉知识库空间 ID（如 r9xmyYP7YK1w1mEO）",
    "DINGTALK_WIKI_API_PATH": "钉钉文档内容 API 路径（自动探测后写入，通常为 wiki 或 drive）",
    "VOLCENGINE_MODEL": "火山云模型 Endpoint ID（如 ep-20260317143459-qtgqn）",
    "OPENROUTER_MODEL": "OpenRouter 备用模型 ID（如 anthropic/claude-sonnet-4-5）",
}

_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 助理 · 配置管理</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f5f5f5; color: #333; }
  .header { background: #1a73e8; color: #fff; padding: 16px 24px;
            display: flex; align-items: center; gap: 12px; }
  .header h1 { font-size: 20px; font-weight: 600; }
  .header .badge { background: rgba(255,255,255,.2); border-radius: 4px;
                   padding: 2px 8px; font-size: 12px; }
  .container { max-width: 900px; margin: 24px auto; padding: 0 16px; }
  .card { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.12);
          margin-bottom: 20px; overflow: hidden; }
  .card-header { padding: 16px 20px; border-bottom: 1px solid #eee;
                 font-size: 15px; font-weight: 600; color: #555; }
  .card-body { padding: 20px; }
  .form-row { display: flex; gap: 10px; flex-wrap: wrap; }
  .form-group { display: flex; flex-direction: column; gap: 4px; }
  .form-group label { font-size: 12px; color: #666; font-weight: 500; }
  input[type=text], select, textarea {
    border: 1px solid #ddd; border-radius: 6px; padding: 8px 12px;
    font-size: 14px; outline: none; transition: border-color .2s;
    font-family: inherit;
  }
  input[type=text]:focus, select:focus, textarea:focus { border-color: #1a73e8; }
  #keyInput { width: 260px; }
  #valueInput { flex: 1; min-width: 200px; }
  textarea#valueInput { resize: vertical; min-height: 80px; }
  .btn { padding: 8px 18px; border: none; border-radius: 6px; cursor: pointer;
         font-size: 14px; font-weight: 500; transition: background .15s; }
  .btn-primary { background: #1a73e8; color: #fff; }
  .btn-primary:hover { background: #1558b0; }
  .btn-danger { background: #ea4335; color: #fff; padding: 5px 12px; font-size: 13px; }
  .btn-danger:hover { background: #c5221f; }
  .btn-copy { background: #f1f3f4; color: #444; padding: 5px 10px; font-size: 12px; }
  .btn-copy:hover { background: #e8eaed; }
  .btn-sm { padding: 4px 10px; font-size: 12px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-size: 12px; color: #666; text-transform: uppercase;
       letter-spacing: .5px; padding: 8px 12px; border-bottom: 2px solid #eee; }
  td { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #fafafa; }
  .key-cell { font-family: monospace; font-size: 14px; font-weight: 600; color: #1a73e8; }
  .val-cell { font-family: monospace; font-size: 13px; color: #333;
              max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hint-cell { font-size: 12px; color: #888; max-width: 200px; }
  .time-cell { font-size: 12px; color: #999; white-space: nowrap; }
  .actions-cell { white-space: nowrap; }
  .hint-badge { display: inline-block; background: #e8f0fe; color: #1a73e8;
                font-size: 11px; padding: 2px 7px; border-radius: 12px; margin-top: 4px; }
  .empty-state { text-align: center; padding: 40px; color: #999; font-size: 14px; }
  .alert { padding: 10px 14px; border-radius: 6px; font-size: 14px; margin-bottom: 16px;
           display: none; }
  .alert-success { background: #e6f4ea; color: #137333; border: 1px solid #ceead6; }
  .alert-error { background: #fce8e6; color: #c5221f; border: 1px solid #f5c6c2; }
  .preset-select { width: 200px; }
  .section-title { font-size: 13px; color: #888; margin-bottom: 8px; }
  .tag { display: inline-block; background: #f1f3f4; border-radius: 4px;
         padding: 2px 8px; font-size: 12px; color: #555; }
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block;
         background: #34a853; margin-right: 6px; }
</style>
</head>
<body>
<div class="header">
  <h1>AI 助理配置管理</h1>
  <span class="badge">运行时配置 · 实时生效</span>
  <span class="badge" id="countBadge">加载中…</span>
</div>
<div class="container">
  <div id="alertBox" class="alert"></div>

  <!-- 添加 / 编辑配置 -->
  <div class="card">
    <div class="card-header">添加 / 更新配置项</div>
    <div class="card-body">
      <p class="section-title" style="margin-bottom:12px">
        配置保存到 SQLite，优先级高于 .env，服务无需重启即可生效。
      </p>
      <div class="form-row" style="margin-bottom:10px">
        <div class="form-group">
          <label>快速选择常用配置</label>
          <select id="presetSelect" class="preset-select" onchange="onPreset()">
            <option value="">— 手动输入 —</option>
            <option value="FEISHU_WIKI_MEETING_PAGE">FEISHU_WIKI_MEETING_PAGE</option>
            <option value="FEISHU_WIKI_CONTEXT_PAGE">FEISHU_WIKI_CONTEXT_PAGE</option>
            <option value="FEISHU_WIKI_SPACE_ID">FEISHU_WIKI_SPACE_ID</option>
            <option value="DINGTALK_DOCS_SPACE_ID">DINGTALK_DOCS_SPACE_ID</option>
            <option value="DINGTALK_WIKI_API_PATH">DINGTALK_WIKI_API_PATH</option>
            <option value="VOLCENGINE_MODEL">VOLCENGINE_MODEL</option>
            <option value="OPENROUTER_MODEL">OPENROUTER_MODEL</option>
          </select>
        </div>
      </div>
      <div class="form-row" style="align-items:flex-end">
        <div class="form-group">
          <label>配置 Key</label>
          <input type="text" id="keyInput" placeholder="如 FEISHU_WIKI_MEETING_PAGE" />
        </div>
        <div class="form-group" style="flex:1">
          <label>配置 Value</label>
          <input type="text" id="valueInput" placeholder="配置值" />
        </div>
        <button class="btn btn-primary" onclick="saveConfig()">保存</button>
      </div>
      <div id="hintText" style="margin-top:8px; font-size:12px; color:#666;"></div>
    </div>
  </div>

  <!-- 当前配置列表 -->
  <div class="card">
    <div class="card-header" style="display:flex; justify-content:space-between; align-items:center">
      <span>当前配置项</span>
      <button class="btn btn-sm" style="background:#f1f3f4; color:#333" onclick="loadConfigs()">刷新</button>
    </div>
    <div class="card-body" style="padding:0">
      <div id="tableContainer"></div>
    </div>
  </div>

  <!-- 常用配置说明 -->
  <div class="card">
    <div class="card-header">常用配置说明</div>
    <div class="card-body">
      <table>
        <thead><tr><th>Key</th><th>说明</th></tr></thead>
        <tbody>
          <tr><td class="key-cell">FEISHU_WIKI_MEETING_PAGE</td>
              <td class="hint-cell">飞书会议纪要汇总页面 wiki token</td></tr>
          <tr><td class="key-cell">FEISHU_WIKI_CONTEXT_PAGE</td>
              <td class="hint-cell">AI 助理上下文快照页面 wiki token</td></tr>
          <tr><td class="key-cell">FEISHU_WIKI_SPACE_ID</td>
              <td class="hint-cell">飞书知识库 Space ID（数字）</td></tr>
          <tr><td class="key-cell">DINGTALK_DOCS_SPACE_ID</td>
              <td class="hint-cell">钉钉知识库空间 ID</td></tr>
          <tr><td class="key-cell">DINGTALK_WIKI_API_PATH</td>
              <td class="hint-cell">钉钉文档 API 路径，首次调用自动探测写入</td></tr>
          <tr><td class="key-cell">VOLCENGINE_MODEL</td>
              <td class="hint-cell">火山云 Ark 模型 Endpoint ID</td></tr>
          <tr><td class="key-cell">OPENROUTER_MODEL</td>
              <td class="hint-cell">OpenRouter 备用模型 ID</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<script>
const HINTS = """ + json.dumps(CONFIG_HINTS, ensure_ascii=False) + r""";

function showAlert(msg, type) {
  const box = document.getElementById('alertBox');
  box.className = 'alert alert-' + type;
  box.textContent = msg;
  box.style.display = 'block';
  setTimeout(() => { box.style.display = 'none'; }, 3500);
}

function onPreset() {
  const key = document.getElementById('presetSelect').value;
  if (key) {
    document.getElementById('keyInput').value = key;
    document.getElementById('hintText').textContent = HINTS[key] || '';
  } else {
    document.getElementById('hintText').textContent = '';
  }
}

document.getElementById('keyInput').addEventListener('input', function() {
  const key = this.value.trim().toUpperCase();
  document.getElementById('hintText').textContent = HINTS[key] || '';
  const sel = document.getElementById('presetSelect');
  sel.value = key in HINTS ? key : '';
});

async function loadConfigs() {
  try {
    const resp = await fetch('/api/config');
    const data = await resp.json();
    const keys = Object.keys(data).sort();
    const badge = document.getElementById('countBadge');
    badge.textContent = keys.length + ' 项配置';

    const container = document.getElementById('tableContainer');
    if (keys.length === 0) {
      container.innerHTML = '<div class="empty-state">暂无配置项。使用上方表单添加第一个配置。</div>';
      return;
    }

    let rows = '';
    for (const key of keys) {
      const item = data[key];
      const val = item.value || '';
      const time = (item.updated_at || '').replace('T', ' ').slice(0, 16);
      const hint = HINTS[key.toUpperCase()] || '';
      const displayVal = val.length > 40 ? val.slice(0, 37) + '…' : val;
      rows += `<tr>
        <td class="key-cell">${escHtml(key)}</td>
        <td class="val-cell" title="${escHtml(val)}">${escHtml(displayVal)}</td>
        <td class="hint-cell">${hint ? `<span class="hint-badge">${escHtml(hint)}</span>` : ''}</td>
        <td class="time-cell">${time}</td>
        <td class="actions-cell">
          <button class="btn btn-copy btn-sm" onclick="copyVal('${escHtml(val.replace(/'/g, "\\'"))}')">复制</button>
          &nbsp;
          <button class="btn btn-copy btn-sm" onclick="editConfig('${escHtml(key)}', '${escHtml(val.replace(/'/g, "\\'"))}')">编辑</button>
          &nbsp;
          <button class="btn btn-danger btn-sm" onclick="deleteConfig('${escHtml(key)}')">删除</button>
        </td>
      </tr>`;
    }
    container.innerHTML = `<table>
      <thead><tr><th>Key</th><th>Value</th><th>说明</th><th>更新时间</th><th>操作</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  } catch(e) {
    showAlert('加载配置失败: ' + e.message, 'error');
  }
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
                  .replace(/"/g,'&quot;');
}

function copyVal(val) {
  navigator.clipboard.writeText(val).then(() => showAlert('已复制到剪贴板', 'success'));
}

function editConfig(key, val) {
  document.getElementById('keyInput').value = key;
  document.getElementById('valueInput').value = val;
  document.getElementById('hintText').textContent = HINTS[key.toUpperCase()] || '';
  const sel = document.getElementById('presetSelect');
  sel.value = key.toUpperCase() in HINTS ? key.toUpperCase() : '';
  document.getElementById('keyInput').focus();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

async function saveConfig() {
  const key = document.getElementById('keyInput').value.trim();
  const value = document.getElementById('valueInput').value;
  if (!key) { showAlert('Key 不能为空', 'error'); return; }
  try {
    const resp = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({key, value})
    });
    const data = await resp.json();
    if (resp.ok) {
      showAlert('✅ 配置已保存：' + key, 'success');
      document.getElementById('keyInput').value = '';
      document.getElementById('valueInput').value = '';
      document.getElementById('presetSelect').value = '';
      document.getElementById('hintText').textContent = '';
      loadConfigs();
    } else {
      showAlert('保存失败: ' + (data.error || '未知错误'), 'error');
    }
  } catch(e) {
    showAlert('请求失败: ' + e.message, 'error');
  }
}

async function deleteConfig(key) {
  if (!confirm('确认删除配置 ' + key + ' ？')) return;
  try {
    const resp = await fetch('/api/config/' + encodeURIComponent(key), {method: 'DELETE'});
    const data = await resp.json();
    if (resp.ok) {
      showAlert('🗑️ 已删除：' + key, 'success');
      loadConfigs();
    } else {
      showAlert('删除失败: ' + (data.error || '未知错误'), 'error');
    }
  } catch(e) {
    showAlert('请求失败: ' + e.message, 'error');
  }
}

// 回车提交
document.addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && (e.target.id === 'keyInput' || e.target.id === 'valueInput')) {
    saveConfig();
  }
});

loadConfigs();
</script>
</body>
</html>
"""


class AdminHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.debug("[admin] " + format % args)

    def _send_json(self, status: int, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body: str):
        enc = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(enc)))
        self.end_headers()
        self.wfile.write(enc)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path in ("", "/"):
            self._send_html(_HTML)
            return

        if path == "/feishu/oauth/callback":
            self._handle_feishu_oauth_callback(parsed)
            return

        if path == "/api/config":
            self._send_json(200, config_store.list_all())
            return

        if path.startswith("/api/config/"):
            key = unquote(path[len("/api/config/"):])
            val = config_store.get(key)
            if val:
                self._send_json(200, {"key": key, "value": val})
            else:
                self._send_json(404, {"error": f"key '{key}' not found"})
            return

        self._send_json(404, {"error": "not found"})

    def _handle_feishu_oauth_callback(self, parsed):
        """处理飞书 OAuth 回调，自动交换 code → token 并写入 .env。"""
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]

        if error or not code:
            self._send_html(f"<h2>授权失败</h2><p>error={error}</p>", status=400)
            return

        app_id = os.getenv("FEISHU_APP_ID", "")
        app_secret = os.getenv("FEISHU_APP_SECRET", "")
        redirect_uri = f"http://101.47.13.243:8080/feishu/oauth/callback"

        try:
            resp = httpx.post(
                "https://open.feishu.cn/open-apis/authen/v1/oidc/access_token",
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "app_id": app_id,
                    "app_secret": app_secret,
                    "redirect_uri": redirect_uri,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("data", resp.json())
            access_token = data.get("access_token", "")
            refresh_token = data.get("refresh_token", "")
            expires_in = data.get("expires_in", 7200)

            if not access_token:
                self._send_html(f"<h2>换取 token 失败</h2><pre>{resp.text}</pre>", status=500)
                return

            expires_at = int(time.time() + expires_in)
            # 写入 os.environ（运行时立即生效）
            os.environ["FEISHU_USER_ACCESS_TOKEN"] = access_token
            os.environ["FEISHU_USER_REFRESH_TOKEN"] = refresh_token
            os.environ["FEISHU_USER_TOKEN_EXPIRES_AT"] = str(expires_at)

            # 写回 .env 文件（持久化）
            import re
            env_path = ".env"
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    content = f.read()

                def _replace_or_append(text, key, value):
                    pattern = rf"^{key}=.*$"
                    repl = f"{key}={value}"
                    if re.search(pattern, text, re.MULTILINE):
                        return re.sub(pattern, repl, text, flags=re.MULTILINE)
                    return text + f"\n{key}={value}"

                content = _replace_or_append(content, "FEISHU_USER_ACCESS_TOKEN", access_token)
                content = _replace_or_append(content, "FEISHU_USER_REFRESH_TOKEN", refresh_token)
                content = _replace_or_append(content, "FEISHU_USER_TOKEN_EXPIRES_AT", expires_at)
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                logger.warning(f"[oauth_callback] 写 .env 失败: {e}")

            has_refresh = f"refresh_token: {refresh_token[:20]}..." if refresh_token else "⚠️ 未获得 refresh_token"
            html = (
                "<h2 style='color:green'>✅ 飞书授权成功！</h2>"
                f"<p>access_token 已写入（有效期 {expires_in//60} 分钟）</p>"
                f"<p>{has_refresh}</p>"
                "<p>Token 已写入 .env，服务立即生效，无需重启。</p>"
                "<p>可关闭此页面。</p>"
            )
            self._send_html(html)
            logger.info("[oauth_callback] 飞书 user token 已更新")

        except Exception as e:
            self._send_html(f"<h2>❌ 请求失败</h2><pre>{e}</pre>", status=500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/config":
            body = self._read_body()
            key = (body.get("key") or "").strip()
            value = body.get("value", "")
            if not key:
                self._send_json(400, {"error": "key is required"})
                return
            config_store.set(key, str(value))
            logger.info(f"[admin] config set: {key!r}")
            self._send_json(200, {"ok": True, "key": key})
            return

        self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/api/config/"):
            key = unquote(path[len("/api/config/"):])
            existed = config_store.delete(key)
            if existed:
                logger.info(f"[admin] config deleted: {key!r}")
                self._send_json(200, {"ok": True, "key": key})
            else:
                self._send_json(404, {"error": f"key '{key}' not found"})
            return

        self._send_json(404, {"error": "not found"})


def start_admin_server(port: int = None):
    """启动 Admin HTTP 服务，阻塞运行。端口已占用时跳过（另一实例已在运行）。"""
    import socket
    port = port or int(os.getenv("ADMIN_PORT", "8080"))
    HTTPServer.allow_reuse_address = True
    try:
        server = HTTPServer(("0.0.0.0", port), AdminHandler)
    except OSError as e:
        if e.errno == 98:  # Address already in use
            logger.info(f"[admin] 端口 {port} 已被占用，跳过启动（另一实例已在运行）")
            return
        raise
    logger.info(f"[admin] 配置管理界面启动：http://0.0.0.0:{port}")
    server.serve_forever()
