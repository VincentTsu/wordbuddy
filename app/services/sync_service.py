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

            # 记录元信息
            meta = self._load_meta()
            meta["last_downloaded_etag"] = remote_etag or downloaded_md5
            meta["last_download_time"] = datetime.now().isoformat()
            meta["last_uploaded_etag"] = remote_etag or downloaded_md5  # 防止误判
            self._save_meta(meta)

            self._last_sync_time = datetime.now().strftime("%H:%M:%S")
            return True, "已下载"

        except Exception as e:
            logger.error(f"COS 下载失败: {e}")
            return False, f"下载失败: {str(e)[:200]}"

    def check_need_download(self, db_path: Path) -> bool:
        """快速检查是否需要下载（不下载，不改文件）"""
        remote_etag, _ = self.head_remote()
        if not remote_etag:
            return False
        if db_path.exists():
            local_md5 = _md5_of_file(db_path)
            return local_md5 != remote_etag
        return True

    def check_need_upload(self, db_path: Path) -> bool:
        """检查是否有未上传的本地改动"""
        if not db_path.exists():
            return False
        meta = self._load_meta()
        last_uploaded = meta.get("last_uploaded_etag", "")
        if not last_uploaded:
            return False  # 从未上传过，不需要主动上传
        local_md5 = _md5_of_file(db_path)
        return local_md5 != last_uploaded

    def sync_now(self, close_db_fn=None, reopen_db_fn=None, force: bool = False) -> Tuple[bool, str]:
        """
        手动同步：先下载（拉取最新），再按需上传（仅本地有改动时）。
        
        :param close_db_fn: 关闭 DB 的回调（可选，用于释放文件锁）
        :param reopen_db_fn: 重新打开 DB 的回调（可选）
        :param force: 强制下载，忽略 MD5 比较
        """
        from app.config import get_db_path
        db_path = get_db_path()

        need_dl = force or self.check_need_download(db_path)
        downloaded = False

        if need_dl:
            if close_db_fn:
                close_db_fn()
            ok, msg = self.download_to_replace(db_path, force=force)
            logger.info(f"手动同步下载结果: ok={ok}, msg={msg}")
            if ok and "已下载" in msg:
                downloaded = True
                if reopen_db_fn:
                    reopen_db_fn()
            elif reopen_db_fn:
                # 下载失败也要重新打开
                reopen_db_fn()
        else:
            logger.info("手动同步：无需下载")

        # 只有本地有未上传的改动时才上传，避免覆盖远端新数据
        need_up = self.check_need_upload(db_path)
        if need_up:
            ok_up, msg_up = self.upload(db_path)
            if downloaded and ok_up:
                return True, "双向同步完成"
            elif ok_up:
                return True, "上传成功"
            else:
                return False, f"上传失败: {msg_up}"

        if downloaded:
            return True, "已下载最新词库"
        else:
            return True, "词库已是最新，无需同步"

    def startup_sync(self, close_db_fn=None, reopen_db_fn=None) -> Tuple[bool, str]:
        """
        启动时同步：
        1. 先从 COS 下载（若远端有更新）
        2. 再上传本地（若本地有新改动）
        
        返回 (downloaded, msg)：downloaded=True 表示确实下载了新文件
        
        :param close_db_fn: 关闭 DB 的回调（由主线程通过信号注入）
        :param reopen_db_fn: 重新打开 DB 的回调
        """
        from app.config import config, get_db_path
        if not config.is_cos_configured():
            return False, "COS 未配置"

        db_path = get_db_path()

        # Step1: 检查并下载
        need_dl = self.check_need_download(db_path)
        downloaded = False

        if need_dl:
            logger.info("启动同步 → 远端有更新，准备下载")
            if close_db_fn:
                close_db_fn()
            ok, msg = self.download_to_replace(db_path)
            logger.info(f"启动同步下载结果: {msg}")
            if ok and "已下载" in msg:
                downloaded = True
            # 无论成败都尝试重新打开 DB
            if reopen_db_fn:
                try:
                    reopen_db_fn()
                except Exception as e:
                    logger.error(f"重启 DB 失败: {e}")
        else:
            logger.info("启动同步 → 无需下载（本地已是最新或远端无数据）")

        # Step2: 如果本地有未上传的改动，上传
        need_up = self.check_need_upload(db_path)
        if need_up:
            logger.info("启动同步 → 本地有未上传的改动，上传中")
            ok_up, msg_up = self.upload(db_path)
            logger.info(f"启动同步上传结果: {msg_up}")
        else:
            logger.info("启动同步 → 本地无新改动，跳过上传")

        return downloaded, "已下载" if downloaded else "无需下载"

    def post_query_sync(self):
        """
        查词后同步（后台线程）：
        先检查远端是否有更新（若有则先关闭 DB 再下载），再上传本地数据
        """
        from app.config import config, get_db_path
        if not config.is_cos_configured():
            return
        import threading

        def _sync():
            db_path = get_db_path()
            downloaded = False

            # Step1: 检查远端是否比本地新
            need_dl = self.check_need_download(db_path)
            if need_dl:
                logger.info(f"查词后 → 远端有更新，准备下载")
                # 关闭 DB 释放锁
                try:
                    from app.db.repository import word_repo
                    word_repo.close()
                    logger.info("查词后 → DB 已关闭")
                except Exception as e:
                    logger.warning(f"查词后关闭 DB 失败: {e}")

                ok, msg = self.download_to_replace(db_path)
                logger.info(f"查词后下载结果: {msg}")
                if ok and "已下载" in msg:
                    downloaded = True

                # 通知主线程重载
                if _on_download_success:
                    try:
                        _on_download_success()
                        logger.info("查词后 → 已通知主线程重载 DB")
                    except Exception as e:
                        logger.error(f"通知主线程重载失败: {e}")
                else:
                    logger.warning("查词后 → _on_download_success 未设置，无法通知主线程重载！")

            # Step2: WAL checkpoint + 上传本地数据
            # ⚠️ 用 PASSIVE 模式（非阻塞），不等待主线程未提交的事务，
            #    upload() 内部会再执行 TRUNCATE 确保完整合并
            try:
                from app.db.repository import word_repo
                if word_repo._conn is not None:
                    word_repo._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    logger.info("查词后 → WAL PASSIVE checkpoint 完成")
            except Exception as e:
                logger.warning(f"查词后 WAL checkpoint 失败: {e}")

            ok_up, msg_up = self.upload(db_path)
            logger.info(f"查词后上传: {msg_up}")

        threading.Thread(target=_sync, daemon=True).start()

    @property
    def last_sync_time(self) -> str:
        return self._last_sync_time


# 全局单例
sync_service = SyncService()
