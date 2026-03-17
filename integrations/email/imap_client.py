"""
163 邮箱 IMAP 客户端：轮询未读邮件，提取会议相关内容。
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
        返回未读邮件列表，每条包含：
        subject, sender, date, body_text
        """
        results = []
        try:
            with IMAPClient(self.host, port=self.port, ssl=True) as client:
                client.login(self.username, self.password)
                client.select_folder(folder)
                uids = client.search(["UNSEEN"])
                if not uids:
                    return []

                for uid in uids[-limit:]:
                    try:
                        raw = client.fetch([uid], ["RFC822"])[uid][b"RFC822"]
                        msg = email.message_from_bytes(raw)
                        results.append(self._parse(msg))
                        client.set_flags([uid], [b"\\Seen"])
                    except Exception as e:
                        logger.warning(f"解析邮件 {uid} 失败: {e}")
        except Exception as e:
            logger.error(f"IMAP 连接失败: {e}")
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
            body = msg.get_payload(decode=True).decode(charset, errors="replace")

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
