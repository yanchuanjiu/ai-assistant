"""
163 邮箱 IMAP 客户端：轮询未读邮件，提取会议相关内容。

常见问题排查：
  "Unsafe Login" / 认证失败：
    1. 登录 163 网页版 → 设置 → POP3/SMTP/IMAP → 开启 IMAP
    2. 在"客户端授权密码"处生成专用授权码
    3. 将授权码填入 .env EMAIL_AUTH_CODE（不是登录密码）
"""
import logging
import email
from email.header import decode_header
from imapclient import IMAPClient
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class EmailSettings(BaseSettings):
    email_address: str = ""
    email_auth_code: str = ""
    imap_host: str = "imap.163.com"
    imap_port: int = 993

    class Config:
        env_file = ".env"
        extra = "ignore"


_cfg = EmailSettings()


class IMAPPoller:
    def __init__(self):
        self.host = _cfg.imap_host
        self.port = _cfg.imap_port
        self.username = _cfg.email_address
        self.password = _cfg.email_auth_code

    def fetch_unread(self, folder: str = "INBOX", limit: int = 20) -> list[dict]:
        """
        返回未读邮件列表，每条包含：subject, sender, date, body。
        连接或认证失败时返回空列表并记录详细错误。
        """
        if not self.username or not self.password:
            logger.warning("[IMAP] EMAIL_ADDRESS 或 EMAIL_AUTH_CODE 未配置，跳过轮询")
            return []

        results = []
        try:
            with IMAPClient(self.host, port=self.port, ssl=True) as client:
                try:
                    client.login(self.username, self.password)
                except Exception as auth_err:
                    # 163 "Unsafe Login" 通常是 IMAP 未开启或授权码错误
                    logger.error(
                        f"[IMAP] 认证失败（用户: {self.username}）: {auth_err}\n"
                        "排查：163 网页版 → 设置 → POP3/SMTP/IMAP → 开启 IMAP，并使用客户端授权码"
                    )
                    return []

                client.select_folder(folder)
                uids = client.search(["UNSEEN"])
                if not uids:
                    logger.debug(f"[IMAP] 无未读邮件（{folder}）")
                    return []

                logger.info(f"[IMAP] 发现 {len(uids)} 封未读邮件，处理最新 {min(limit, len(uids))} 封")
                for uid in uids[-limit:]:
                    try:
                        raw = client.fetch([uid], ["RFC822"])[uid][b"RFC822"]
                        msg = email.message_from_bytes(raw)
                        results.append(self._parse(msg))
                        client.set_flags([uid], [b"\\Seen"])
                    except Exception as e:
                        logger.warning(f"[IMAP] 解析邮件 uid={uid} 失败: {e}")

        except Exception as e:
            logger.error(f"[IMAP] 连接 {self.host}:{self.port} 失败: {e}")

        return results

    def _parse(self, msg) -> dict:
        subject = self._decode_header(msg.get("Subject", ""))
        sender = self._decode_header(msg.get("From", ""))
        date = msg.get("Date", "")
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    charset = part.get_content_charset() or "utf-8"
                    body = part.get_payload(decode=True).decode(charset, errors="replace")
                    break
        else:
            charset = msg.get_content_charset() or "utf-8"
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(charset, errors="replace")

        return {"subject": subject, "sender": sender, "date": date, "body": body.strip()}

    @staticmethod
    def _decode_header(value: str) -> str:
        parts = decode_header(value)
        decoded = []
        for text, charset in parts:
            if isinstance(text, bytes):
                decoded.append(text.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(text)
        return "".join(decoded)
