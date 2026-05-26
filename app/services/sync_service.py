"""
WordBuddy 腾讯云 COS 同步服务
上传/下载 SQLite 数据库文件，实现跨设备数据同步

同步策略（基于 ETag 哈希，不依赖时间戳）：
  - 每次下载后把远端 ETag 保存到本地元信息文件
  - 上传时同样保存上传后的 ETag
  - 判断"是否需要下载"：用本地文件 MD5 与远端 ETag 比较
  - 判断"是否需要上传"：用本地文件 MD5 与上次上传时保存的 ETag 比较
  - startup_sync：先下载（若远端更新），再上传（若本地有新改动）
  - post_query_sync：先下载合并，再上传，避免用旧数据覆盖新数据

关键设计原则：
  - 所有涉及 shutil.move() 替换 DB 文件的操作，
    必须在调用方先关闭 word_repo 连接，操作完成后重新打开。
  - 本模块不负责开关 DB，只负责 COS 交互 + 文件替换。
"""

import hashlib
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional, Callable

logger = logging.getLogger(__name__)

# 元信息文件：记录上次上传/下载的 ETag
_META_FILENAME = "word_buddy_sync_meta.json"

# 回调函数类型：下载成功后通知主线程重载数据库
# 由 AppController 在初始化时注入
_on_download_success: Optional[Callable[[], None]] = None


def _md5_of_file(path: Path) -> str:
    """计算本地文件的 MD5（与 COS ETag 格式一致）"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_etag(etag: str) -> str:
    """去掉 ETag 首尾的引号"""
    return etag.strip('"') if etag else ""


class SyncService:
    """腾讯云 COS 词库同步服务"""

    def __init__(self):
        self._last_sync_time: str = ""

    # ────────── 内部元信息 ──────────

    def _meta_path(self) -> Path:
        from app.config import get_app_data_dir
        return get_app_data_dir() / _META_FILENAME

    def _load_meta(self) -> dict:
        p = self._meta_path()
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_meta(self, meta: dict):
        try:
            self._meta_path().write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"保存同步元信息失败: {e}")

    @staticmethod
    def _wal_checkpoint():
        """PASSIVE checkpoint to merge WAL into main file without blocking."""
        try:
            from app.db.repository import word_repo
            if word_repo._conn is not None:
                word_repo._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass

    # ────────── COS 客户端 ──────────

    def _get_client(self):
        from app.config import config
        try:
            from qcloud_cos import CosConfig, CosS3Client
            cos_config = CosConfig(
                Region=config.cos_region,
                SecretId=config.cos_secret_id,
                SecretKey=config.cos_secret_key,
            )
            return CosS3Client(cos_config), config.cos_bucket
        except ImportError:
            raise RuntimeError("COS SDK 未安装，请执行: pip install cos-python-sdk-v5")

    def head_remote(self) -> Tuple[str, int]:
        """
        获取远端文件的 (ETag, 文件大小)。
        文件不存在时返回 ("", 0)。
        """
        from app.constants import COS_OBJECT_KEY
        try:
            client, bucket = self._get_client()
            head = client.head_object(Bucket=bucket, Key=COS_OBJECT_KEY)
            etag = _norm_etag(head.get("ETag", ""))
            size = head.get("Content-Length", 0)
            if isinstance(size, str):
                size = int(size)
            return etag, size
        except Exception as e:
            logger.info(f"获取远端头信息失败（可能文件不存在）: {e}")
            return "", 0

    # ────────── 公共接口 ──────────

    def test_connection(self) -> Tuple[bool, str]:
        """测试 COS 连接"""
        from app.config import config
        if not config.is_cos_configured():
            return False, "请先填写完整的 COS 配置信息"
        try:
            client, bucket = self._get_client()
            client.head_bucket(Bucket=bucket)
            return True, f"连接成功！Bucket: {bucket}"
        except Exception as e:
            err = str(e)
            if "NoSuchBucket" in err:
                return False, f"Bucket 不存在: {config.cos_bucket}"
            elif "InvalidSecretId" in err or "AuthFailure" in err:
                return False, "SecretId 或 SecretKey 无效"
            else:
                return False, f"连接失败: {err[:100]}"

    def upload(self, local_db_path: Path) -> Tuple[bool, str]:
        """上传本地数据库到 COS，并记录上传后的 ETag"""
        from app.config import config
        from app.constants import COS_OBJECT_KEY
        if not config.is_cos_configured():
            return False, "COS 未配置"
        if not local_db_path.exists():
            return False, "本地数据库文件不存在"

        # 上传前确保 WAL 已合并到主文件，否则上传的文件不完整
        # 使用短暂等待 + TRUNCATE，但不在主线程复习期间阻塞
        import time
        try:
            from app.db.repository import word_repo
            if word_repo._conn is not None:
                # 先用 PASSIVE（非阻塞）尝试，让已有事务先完成
                word_repo._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                time.sleep(0.05)  # 50ms 让主线程 commit 完成
                # 再用 TRUNCATE 确保完全合并
                word_repo._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                logger.debug("上传前 WAL checkpoint 完成")
        except Exception as e:
            logger.warning(f"上传前 WAL checkpoint 失败（非致命）: {e}")

        try:
            client, bucket = self._get_client()
            with open(local_db_path, "rb") as f:
                client.put_object(
                    Bucket=bucket,
                    Body=f,
                    Key=COS_OBJECT_KEY,
                    ContentType="application/octet-stream",
                )
            # 记录本次上传的 ETag（即当前本地文件的 MD5）
            local_md5 = _md5_of_file(local_db_path)
            meta = self._load_meta()
            meta["last_uploaded_etag"] = local_md5
            meta["last_upload_time"] = datetime.now().isoformat()
            # Upload succeeded — clear deletion tracking since the deleted
            # words are now gone from the remote file too.
            if "deleted" in meta:
                del meta["deleted"]
            self._save_meta(meta)

            self._last_sync_time = datetime.now().strftime("%H:%M:%S")
            logger.info(f"数据库已上传至 COS（ETag: {local_md5[:8]}…）")
            return True, f"上传成功（{self._last_sync_time}）"
        except Exception as e:
            logger.warning(f"COS 上传失败: {e}")
            return False, f"上传失败: {str(e)[:100]}"

    def download_to_replace(self, local_db_path: Path, force: bool = False) -> Tuple[bool, str]:
        """
        从 COS 下载数据库并替换本地文件。
        
        :param force: 强制下载，跳过 MD5 比较
        
        ⚠️ 调用前必须确保 word_repo 已关闭（释放文件锁），
           否则 Windows 上 shutil.move 会静默失败。
        
        返回 (ok, msg)，msg 含 "已下载" 表示确实替换了文件。
        """
        from app.config import config
        from app.constants import COS_OBJECT_KEY
        if not config.is_cos_configured():
            return False, "COS 未配置"
        try:
            client, bucket = self._get_client()

            # 获取远端 ETag
            remote_etag, remote_size = self.head_remote()
            if not remote_etag and remote_size == 0:
                logger.info("COS 无数据，跳过下载")
                return True, "COS 无数据，跳过"

            # 比较本地 MD5 与远端 ETag
            if not force and local_db_path.exists():
                local_md5 = _md5_of_file(local_db_path)
                if local_md5 == remote_etag:
                    logger.info(f"本地一致（ETag: {remote_etag[:8]}…），跳过")
                    return True, "本地已是最新"

            # === 开始下载 ===
            logger.info(f"开始下载：remote={remote_etag[:8]}… size={remote_size}")

            with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                tmp_path = tmp.name

            client.download_file(
                Bucket=bucket,
                Key=COS_OBJECT_KEY,
                DestFilePath=tmp_path
            )

            # 校验：文件非空且大小匹配
            actual_size = os.path.getsize(tmp_path)
            if actual_size < 100:
                os.unlink(tmp_path)
                return False, f"下载损坏（太小: {actual_size}B）"

            downloaded_md5 = _md5_of_file(Path(tmp_path))
            if remote_etag and downloaded_md5 != remote_etag:
                # 大文件分片上传时 ETag 可能不是简单 MD5，只做警告
                logger.warning(f"下载文件 MD5 与 ETag 不匹配（分片上传？）: "
                               f"local={downloaded_md5[:8]}… remote={remote_etag[:8]}…")

            # 备份
            if local_db_path.exists():
                backup_path = local_db_path.with_suffix(".db.bak")
                shutil.copy2(local_db_path, backup_path)

            # 替换（调用方必须确保 DB 已关闭）
            shutil.move(tmp_path, str(local_db_path))

            # 验证替换后的文件可读
            verify_size = os.path.getsize(local_db_path)
            logger.info(f"✅ 文件已替换: {local_db_path.name} ({verify_size} bytes)")

            # 记录元信息：只更新 last_downloaded_etag，不覆盖 last_uploaded_etag
            # 这样 check_need_upload 仍能正确判断本地是否有未上传的改动
            meta = self._load_meta()
            meta["last_downloaded_etag"] = remote_etag or downloaded_md5
            meta["last_download_time"] = datetime.now().isoformat()
            self._save_meta(meta)

            self._last_sync_time = datetime.now().strftime("%H:%M:%S")
            return True, "已下载"

        except Exception as e:
            logger.error(f"COS 下载失败: {e}")
            return False, f"下载失败: {str(e)[:200]}"

    def check_need_download(self, db_path: Path) -> bool:
        """快速检查是否需要下载：远端是否有新数据（不比较本地 MD5）"""
        remote_etag, _ = self.head_remote()
        if not remote_etag:
            return False
        meta = self._load_meta()
        last_downloaded = meta.get("last_downloaded_etag", "")
        return remote_etag != last_downloaded

    def check_need_upload(self, db_path: Path) -> bool:
        """检查是否有未上传的本地改动"""
        if not db_path.exists():
            return False
        # WAL checkpoint before computing MD5 — otherwise un-checkpointed
        # writes would not be reflected in the main file hash, causing the
        # upload check to see no change and skip the upload entirely.
        self._wal_checkpoint()
        meta = self._load_meta()
        last_uploaded = meta.get("last_uploaded_etag", "")
        local_md5 = _md5_of_file(db_path)
        if not last_uploaded:
            # 从未上传过——只有本地确实有数据时才上传
            # 避免用空数据库覆盖远端的有效数据
            return db_path.stat().st_size > 1024 and local_md5 != "d41d8cd98f00b204e9800998ecf8427e"
        return local_md5 != last_uploaded

    def merge_from_remote(self, db_path: Path) -> int:
        """
        下载远端数据库并与本地合并（逐词合并，不替换文件）。
        类似 Android 端的 mergeFrom 逻辑。
        返回合并的词条数。调用前确保 word_repo 已初始化。
        """
        import sqlite3
        from app.config import config
        from app.constants import COS_OBJECT_KEY

        client, bucket = self._get_client()
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            client.download_file(Bucket=bucket, Key=COS_OBJECT_KEY, DestFilePath=tmp_path)
            remote_conn = sqlite3.connect(f"file:{tmp_path}?mode=ro", uri=True)
            remote_cur = remote_conn.cursor()

            # 获取远端所有单词
            remote_cur.execute("SELECT * FROM words")
            remote_rows = remote_cur.fetchall()
            remote_words = {}
            for row in remote_rows:
                remote_words[row[1].lower()] = row  # word is column 1 (NOCASE key)

            remote_conn.close()

            # 获取本地所有单词
            from app.db.repository import word_repo
            from app.config import get_db_path
            if word_repo._conn is None:
                word_repo.initialize(get_db_path())
            local_conn = word_repo._conn
            local_cur = local_conn.cursor()
            local_cur.execute("SELECT * FROM words")
            local_rows = local_cur.fetchall()
            # 用字典存储列名
            col_names = [desc[0] for desc in local_cur.description]
            local_words = {}
            for row in local_rows:
                d = dict(zip(col_names, row))
                local_words[d['word'].lower()] = d

            merged = 0
            deleted = self._get_deleted_words()

            for word_lower, r_row in remote_words.items():
                r = dict(zip(col_names, r_row))
                if word_lower not in local_words:
                    # Skip if we intentionally deleted this word
                    if word_lower in deleted:
                        continue
                    # 远端有、本地没有 → 插入
                    cols = ",".join(col_names[1:])  # skip id
                    placeholders = ",".join(["?" for _ in col_names[1:]])
                    local_conn.execute(
                        f"INSERT INTO words ({cols}) VALUES ({placeholders})",
                        r_row[1:]
                    )
                    merged += 1
                else:
                    local_w = local_words[word_lower]
                    # 优先保留复习进度更新的那一边
                    if self._should_prefer_remote(local_w, r):
                        set_clauses = ",".join(f"{c}=?" for c in col_names[1:])
                        local_conn.execute(
                            f"UPDATE words SET {set_clauses} WHERE word=? COLLATE NOCASE",
                            list(r_row[1:]) + [r['word']]
                        )
                        merged += 1

            local_conn.commit()

            # 更新元信息
            remote_etag, _ = self.head_remote()
            meta = self._load_meta()
            meta["last_downloaded_etag"] = remote_etag
            meta["last_download_time"] = datetime.now().isoformat()
            self._save_meta(meta)

            logger.info(f"合并完成：{merged} 条变更")
            return merged

        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    @staticmethod
    def _should_prefer_remote(local: dict, remote: dict) -> bool:
        """判断是否用远端数据覆盖本地（逐字合并策略）"""
        if (not local.get('definition')) and remote.get('definition'):
            return True
        if remote.get('last_reviewed_at', '') > local.get('last_reviewed_at', ''):
            return True
        return (remote.get('total_reviews', 0) or 0) > (local.get('total_reviews', 0) or 0)

    def track_deletion(self, word: str):
        """Record a word deletion so merge won't re-insert it from remote."""
        meta = self._load_meta()
        deleted = meta.get("deleted", [])
        if word.lower() not in deleted:
            deleted.append(word.lower())
            meta["deleted"] = deleted
            self._save_meta(meta)

    def _get_deleted_words(self) -> set:
        meta = self._load_meta()
        return set(meta.get("deleted", []))

    def _clear_deleted_words(self):
        meta = self._load_meta()
        if "deleted" in meta:
            del meta["deleted"]
            self._save_meta(meta)

    def sync_now(self, close_db_fn=None, reopen_db_fn=None, force: bool = False) -> Tuple[bool, str]:
        """
        手动同步：先上传本地改动，再合并远端新数据（逐词合并，不替换文件）。

        :param close_db_fn: 关闭 DB 的回调（可选，用于释放文件锁）
        :param reopen_db_fn: 重新打开 DB 的回调（可选）
        :param force: 强制合并远端数据
        """
        from app.config import get_db_path
        db_path = get_db_path()

        msgs = []

        # Step 1: 先上传本地改动（保留本地数据到远端）
        if self.check_need_upload(db_path):
            ok_up, msg_up = self.upload(db_path)
            logger.info(f"手动同步上传: {msg_up}")
            if ok_up:
                msgs.append("已上传本地改动")

        # Step 2: 再合并远端新数据（逐词合并，不替换文件）
        need_dl = force or self.check_need_download(db_path)
        if need_dl:
            try:
                merged = self.merge_from_remote(db_path)
                if merged > 0:
                    msgs.append(f"已合并 {merged} 条云端词条")
                else:
                    msgs.append("云端与本地一致")
            except Exception as e:
                logger.error(f"合并远端失败: {e}")
                msgs.append(f"合并失败: {str(e)[:100]}")
        else:
            msgs.append("云端无新数据")

        msg = "；".join(msgs) if msgs else "无需同步"
        return True, msg

    def startup_sync(self, close_db_fn=None, reopen_db_fn=None) -> Tuple[bool, str]:
        """
        启动时同步（逐词合并策略，不替换文件）：
        1. 先上传本地改动
        2. 再合并远端新数据

        返回 (downloaded, msg)
        """
        from app.config import config, get_db_path
        if not config.is_cos_configured():
            return False, "COS 未配置"

        db_path = get_db_path()
        downloaded = False

        # Step 1: 上传本地改动
        if self.check_need_upload(db_path):
            logger.info("启动同步 → 本地有未上传的改动，先上传")
            ok_up, msg_up = self.upload(db_path)
            logger.info(f"启动同步上传结果: {msg_up}")

        # Step 2: 合并远端新数据
        need_dl = self.check_need_download(db_path)
        if need_dl:
            logger.info("启动同步 → 远端有更新，开始合并")
            try:
                merged = self.merge_from_remote(db_path)
                logger.info(f"启动同步合并结果: {merged} 条变更")
                if merged > 0:
                    downloaded = True
            except Exception as e:
                logger.error(f"启动同步合并失败: {e}")
        else:
            logger.info("启动同步 → 无需合并（远端无变化）")

        return downloaded, "已合并" if downloaded else "无需同步"

    def post_query_sync(self):
        """
        查词后同步（后台线程）：
        先上传本地改动，再合并远端新数据（逐词合并不替换文件）。
        """
        from app.config import config, get_db_path
        if not config.is_cos_configured():
            return
        import threading

        def _sync():
            db_path = get_db_path()
            try:
                # Step 1: 上传本地改动
                if self.check_need_upload(db_path):
                    logger.info("查词后 → 本地有改动，上传中")
                    self.upload(db_path)

                # Step 2: 合并远端新数据
                if self.check_need_download(db_path):
                    merged = self.merge_from_remote(db_path)
                    logger.info(f"查词后合并: {merged} 条变更")
                else:
                    logger.info("查词后 → 远端无变化，跳过")
            except Exception as e:
                logger.warning(f"查词后同步失败: {e}")

        threading.Thread(target=_sync, daemon=True).start()

    @property
    def last_sync_time(self) -> str:
        return self._last_sync_time


# 全局单例
sync_service = SyncService()
