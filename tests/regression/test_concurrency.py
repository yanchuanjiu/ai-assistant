"""
回归测试：并发安全性（P2）

覆盖：
  CC-1x  SQLite meeting.db 并发 INSERT 唯一性（UNIQUE constraint）
  CC-2x  config_store 并发读写一致性
  CC-3x  error_tracker 并发记录无竞态
"""
import os
import sqlite3
import threading
import tempfile
import pytest
from unittest.mock import patch


# ── CC-1x: SQLite meeting.db 并发 INSERT 唯一性──────────────────────────────
class TestMeetingDbConcurrency:
    """meeting.db 中 meeting_docs 表以 doc_id 为主键，并发 INSERT 不应产生重复"""

    @pytest.fixture
    def meeting_db(self, tmp_path):
        """创建临时 meeting.db 并初始化表结构"""
        db_path = str(tmp_path / "meeting.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meeting_docs (
                doc_id       TEXT PRIMARY KEY,
                title        TEXT,
                status       TEXT DEFAULT 'pending',
                created_at   TEXT,
                updated_at   TEXT
            )
        """)
        conn.commit()
        conn.close()
        return db_path

    def test_concurrent_insert_same_doc_id_no_duplicate(self, meeting_db):
        """10个线程并发 INSERT 同一 doc_id → 最终只有 1 条记录"""
        success_count = 0
        error_count = 0
        lock = threading.Lock()

        def insert_fn():
            nonlocal success_count, error_count
            try:
                conn = sqlite3.connect(meeting_db)
                conn.execute(
                    "INSERT INTO meeting_docs (doc_id, title, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
                    ("doc_unique_001", "会议纪要", "pending")
                )
                conn.commit()
                conn.close()
                with lock:
                    success_count += 1
            except sqlite3.IntegrityError:
                # UNIQUE constraint 正常触发，这是预期行为
                with lock:
                    error_count += 1
            except Exception as e:
                with lock:
                    error_count += 1

        threads = [threading.Thread(target=insert_fn) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 验证：只有 1 条成功
        assert success_count == 1, f"期望1次成功，实际: {success_count}"
        assert error_count == 9, f"期望9次主键冲突，实际: {error_count}"

        # 验证数据库中确实只有 1 条
        conn = sqlite3.connect(meeting_db)
        count = conn.execute("SELECT COUNT(*) FROM meeting_docs WHERE doc_id='doc_unique_001'").fetchone()[0]
        conn.close()
        assert count == 1

    def test_concurrent_insert_different_doc_ids_all_succeed(self, meeting_db):
        """10个线程并发 INSERT 不同 doc_id → 全部成功，共10条记录"""
        results = []
        lock = threading.Lock()

        def insert_fn(i):
            try:
                conn = sqlite3.connect(meeting_db)
                conn.execute(
                    "INSERT INTO meeting_docs (doc_id, title, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
                    (f"doc_{i:03d}", f"会议{i}", "pending")
                )
                conn.commit()
                conn.close()
                with lock:
                    results.append("ok")
            except Exception as e:
                with lock:
                    results.append(f"err: {e}")

        threads = [threading.Thread(target=insert_fn, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        errors = [r for r in results if r.startswith("err")]
        assert not errors, f"并发 INSERT 不同 doc_id 时出现错误: {errors}"

        conn = sqlite3.connect(meeting_db)
        count = conn.execute("SELECT COUNT(*) FROM meeting_docs").fetchone()[0]
        conn.close()
        assert count == 10

    def test_not_meeting_status_flag_dedup(self, meeting_db):
        """非会议文档标记为 not_meeting，再次 INSERT 时触发主键冲突"""
        conn = sqlite3.connect(meeting_db)
        conn.execute(
            "INSERT INTO meeting_docs (doc_id, title, status, created_at, updated_at) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("not_meeting_doc", "普通文档", "not_meeting")
        )
        conn.commit()
        conn.close()

        # 再次尝试 INSERT 同一 doc_id
        with pytest.raises(sqlite3.IntegrityError):
            conn = sqlite3.connect(meeting_db)
            conn.execute(
                "INSERT INTO meeting_docs (doc_id, title, status, created_at, updated_at) "
                "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
                ("not_meeting_doc", "普通文档", "not_meeting")
            )
            conn.commit()
            conn.close()


# ── CC-2x: config_store 并发读写一致性────────────────────────────────────────
class TestConfigStoreConcurrency:

    @pytest.fixture(autouse=True)
    def isolate_db(self, tmp_path, monkeypatch):
        import integrations.storage.config_store as cs
        tmp_db = str(tmp_path / "test_config.db")
        monkeypatch.setattr(cs, "_DB_PATH", tmp_db)

    def test_concurrent_set_same_key(self):
        """10个线程并发 set 同一 key → 最终值是其中一个，无崩溃"""
        from integrations.storage.config_store import set as cfg_set, get as cfg_get
        errors = []
        lock = threading.Lock()

        def set_fn(i):
            try:
                cfg_set("CONCURRENT_KEY", f"value_{i}")
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=set_fn, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发 set 出现异常: {errors}"
        # 最终值应该是某个 value_N（非空，不崩溃）
        final_val = cfg_get("CONCURRENT_KEY")
        assert final_val.startswith("value_"), f"最终值异常: {final_val!r}"

    def test_concurrent_set_different_keys(self):
        """10个线程并发 set 不同 key → 全部写入成功"""
        from integrations.storage.config_store import set as cfg_set, get as cfg_get
        errors = []
        lock = threading.Lock()

        def set_fn(i):
            try:
                cfg_set(f"KEY_{i}", f"val_{i}")
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=set_fn, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发 set 不同 key 出现异常: {errors}"
        # 验证每个 key 都写入了
        for i in range(10):
            val = cfg_get(f"KEY_{i}")
            assert val == f"val_{i}", f"KEY_{i} 的值错误: {val!r}"


# ── CC-3x: error_tracker 并发记录无竞态──────────────────────────────────────
class TestErrorTrackerConcurrency:

    @pytest.fixture(autouse=True)
    def isolate_tracker(self, tmp_path, monkeypatch):
        import integrations.logging.error_tracker as et
        tracker_path = str(tmp_path / "tracker.json")
        monkeypatch.setattr(et, "_TRACKER_FILE", tracker_path)

    def test_concurrent_record_same_pattern(self):
        """20个线程并发记录同一错误模式 → 计数最终等于20"""
        from integrations.logging.error_tracker import record_error, get_fix_status
        results = []
        errors = []
        lock = threading.Lock()

        def record_fn():
            try:
                count = record_error("concurrent_error_pattern", "err_snippet", "feishu", "chat1")
                with lock:
                    results.append(count)
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=record_fn) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发记录时出现异常: {errors}"
        assert len(results) == 20
        status = get_fix_status("concurrent_error_pattern")
        # 最终计数应精确等于20
        assert status["count"] == 20, f"并发记录后计数应为20，实际: {status['count']}"
