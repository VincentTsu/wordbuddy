"""
WordBuddy Tencent COS sync service
Download → merge (updated_at wins) → upload merged result.
Soft-deletes are normal writes with deleted_at timestamp.
"""

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional, Callable

logger = logging.getLogger(__name__)

_META_FILENAME = "word_buddy_sync_meta.json"
_on_download_success: Optional[Callable[[], None]] = None


def _md5_of_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_etag(etag: str) -> str:
    return etag.strip('"') if etag else ""


class SyncService:

    def __init__(self):
        self._last_sync_time: str = ""

    # ────────── Meta ──────────

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
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save sync meta: {e}")

    @staticmethod
    def _wal_checkpoint():
        try:
            from app.db.repository import word_repo
            if word_repo._conn is not None:
                word_repo._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass

    # ────────── COS client ──────────

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
            raise RuntimeError("COS SDK not installed: pip install cos-python-sdk-v5")

    def head_remote(self) -> Tuple[str, int]:
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
            logger.info(f"head_remote failed (file may not exist): {e}")
            return "", 0

    def test_connection(self) -> Tuple[bool, str]:
        from app.config import config
        if not config.is_cos_configured():
            return False, "COS not configured"
        try:
            self.head_remote()
            return True, "COS connection OK"
        except Exception as e:
            err = str(e)
            if "InvalidAccessKeyId" in err or "AccessDenied" in err:
                return False, "SecretId or SecretKey invalid"
            elif "NoSuchBucket" in err:
                return False, "Bucket does not exist"
            elif "InvalidSecretId" in err or "AuthFailure" in err:
                return False, "SecretId or SecretKey invalid"
            else:
                return False, f"Connection failed: {err[:100]}"

    # ────────── Upload / Download ──────────

    def upload(self, local_db_path: Path) -> Tuple[bool, str]:
        from app.config import config
        from app.constants import COS_OBJECT_KEY
        if not config.is_cos_configured():
            return False, "COS not configured"
        if not local_db_path.exists():
            return False, "Local DB file does not exist"

        # WAL checkpoint before upload
        try:
            from app.db.repository import word_repo
            if word_repo._conn is not None:
                word_repo._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                time.sleep(0.05)
                word_repo._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                logger.debug("WAL checkpoint before upload complete")
        except Exception as e:
            logger.warning(f"WAL checkpoint before upload failed (non-fatal): {e}")

        try:
            client, bucket = self._get_client()
            with open(local_db_path, "rb") as f:
                client.put_object(
                    Bucket=bucket,
                    Body=f,
                    Key=COS_OBJECT_KEY,
                    ContentType="application/octet-stream",
                )
            local_md5 = _md5_of_file(local_db_path)
            meta = self._load_meta()
            meta["last_uploaded_etag"] = local_md5
            meta["last_upload_time"] = datetime.now().isoformat()
            self._save_meta(meta)
            self._last_sync_time = datetime.now().strftime("%H:%M:%S")
            logger.info(f"Uploaded to COS (ETag: {local_md5[:8]})")
            return True, f"Uploaded ({self._last_sync_time})"
        except Exception as e:
            logger.warning(f"COS upload failed: {e}")
            return False, f"Upload failed: {str(e)[:100]}"

    # ────────── Merge logic ──────────

    def merge_from_remote(self, db_path: Path) -> int:
        """
        Download remote DB, merge into local word-by-word.
        For each word, the side with newer updated_at wins.
        If updated_at is empty, falls back to created_at.
        Returns number of changed rows.
        """
        from app.config import config
        from app.constants import COS_OBJECT_KEY
        if not config.is_cos_configured():
            return 0

        client, bucket = self._get_client()
        tmp_path = None
        remote_conn = None
        try:
            # Download remote to temp (mkstemp releases file handle immediately on Windows)
            fd, tmp_path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            client.download_file(Bucket=bucket, Key=COS_OBJECT_KEY, DestFilePath=tmp_path)

            if os.path.getsize(tmp_path) < 100:
                return 0

            remote_conn = sqlite3.connect(tmp_path)
            remote_conn.row_factory = sqlite3.Row

            from app.db.repository import word_repo

            changed = 0
            batch = 0
            for row in remote_conn.execute("SELECT * FROM words"):
                remote_word = dict(row)
                remote_word_text = remote_word["word"]
                remote_updated = remote_word.get("updated_at") or remote_word.get("created_at") or ""

                # Find local (including soft-deleted rows)
                local_row = word_repo._conn.execute(
                    "SELECT * FROM words WHERE word = ? COLLATE NOCASE",
                    (remote_word_text,),
                ).fetchone()

                if local_row is None:
                    # New word from remote — insert
                    cols = ", ".join(remote_word.keys())
                    placeholders = ", ".join("?" * len(remote_word))
                    self._safe_execute(
                        word_repo._conn,
                        f"INSERT INTO words ({cols}) VALUES ({placeholders})",
                        tuple(remote_word.values()),
                    )
                    changed += 1
                else:
                    local_word = dict(local_row)
                    local_updated = local_word.get("updated_at") or local_word.get("created_at") or ""
                    if remote_updated > local_updated:
                        # Remote is newer — overwrite
                        set_clause = ", ".join(f"{k} = ?" for k in remote_word if k != "id")
                        values = [remote_word[k] for k in remote_word if k != "id"]
                        values.append(local_word["id"])
                        self._safe_execute(
                            word_repo._conn,
                            f"UPDATE words SET {set_clause} WHERE id = ?",
                            values,
                        )
                        changed += 1
                    # else: local is newer or equal — keep local

                batch += 1
                if batch % 20 == 0:
                    try:
                        word_repo._conn.commit()
                    except Exception:
                        pass

            if changed > 0:
                word_repo._conn.commit()
            logger.info(f"merge_from_remote: {changed} rows changed")

            # Update sync meta
            etag, _ = self.head_remote()
            if etag:
                meta = self._load_meta()
                meta["last_downloaded_etag"] = etag
                self._save_meta(meta)

            return changed
        except Exception as e:
            logger.error(f"merge_from_remote failed: {e}", exc_info=True)
            return 0
        finally:
            if remote_conn is not None:
                try:
                    remote_conn.close()
                except Exception:
                    pass
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    @staticmethod
    def _safe_execute(conn, sql, params):
        """Execute SQL with retry for "database is locked" errors."""
        max_retries = 5
        for attempt in range(max_retries):
            try:
                conn.execute(sql, params)
                return
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    time.sleep(0.05 * (attempt + 1))
                else:
                    raise


    def check_need_download(self, db_path: Path) -> bool:
        remote_etag, _ = self.head_remote()
        if not remote_etag:
            return False
        if not db_path.exists():
            return True
        # Compare with last downloaded ETag (no file read needed)
        meta = self._load_meta()
        last_dl = meta.get("last_downloaded_etag", "")
        return last_dl != remote_etag

    def check_need_upload(self, db_path: Path) -> bool:
        if not db_path.exists():
            return False
        # Always upload after merge ? the merged data is always newer
        # than what was last uploaded.  We rely on the caller to call
        # this only when there is a real reason to upload.
        meta = self._load_meta()
        last_uploaded = meta.get("last_uploaded_etag", "")
        # WAL checkpoint before computing MD5
        self._wal_checkpoint()
        try:
            local_md5 = _md5_of_file(db_path)
        except Exception:
            # File locked ? skip upload
            return False
        if not last_uploaded:
            return db_path.stat().st_size > 1024
        return local_md5 != last_uploaded

    # ────────── Public sync entry points ──────────

    def sync_now(self, close_db_fn=None, reopen_db_fn=None, force: bool = False) -> Tuple[bool, str]:
        """
        Manual sync: download → merge (updated_at comparison) → upload merged result.
        """
        from app.config import get_db_path
        db_path = get_db_path()
        msgs = []

        # Step 1: pull & merge remote changes
        need_dl = force or self.check_need_download(db_path)
        if need_dl:
            try:
                merged = self.merge_from_remote(db_path)
                if merged > 0:
                    msgs.append(f"Merged {merged} words from cloud")
                else:
                    msgs.append("Local already up-to-date")
            except Exception as e:
                logger.error(f"Merge from remote failed: {e}")
                msgs.append(f"Merge failed: {str(e)[:100]}")
        else:
            msgs.append("No cloud changes")

        # Step 2: upload merged result if changed
        if self.check_need_upload(db_path):
            ok_up, msg_up = self.upload(db_path)
            logger.info(f"Manual sync upload: {msg_up}")
            if ok_up:
                msgs.append("Uploaded local changes")

        msg = "; ".join(msgs) if msgs else "Already up-to-date"
        return True, msg

    def startup_sync(self, close_db_fn=None, reopen_db_fn=None) -> Tuple[bool, str]:
        """
        Startup sync: merge remote → upload if needed.
        Returns (merged, msg).
        """
        from app.config import config, get_db_path
        if not config.is_cos_configured():
            return False, "COS not configured"

        db_path = get_db_path()
        downloaded = False

        # Merge remote changes first
        need_dl = self.check_need_download(db_path)
        if need_dl:
            logger.info("Startup sync → pulling cloud changes")
            try:
                merged = self.merge_from_remote(db_path)
                logger.info(f"Startup sync merged: {merged} changes")
                if merged > 0:
                    downloaded = True
            except Exception as e:
                logger.error(f"Startup sync merge failed: {e}")

        # Upload if local has new changes
        if self.check_need_upload(db_path):
            logger.info("Startup sync → uploading local changes")
            ok_up, msg_up = self.upload(db_path)
            logger.info(f"Startup sync upload: {msg_up}")

        return downloaded, "Merged cloud words" if downloaded else "Already up-to-date"

    def post_query_sync(self):
        """
        Background sync after word lookup:
        merge remote → upload (all in background thread).
        """
        from app.config import config, get_db_path
        if not config.is_cos_configured():
            return
        import threading

        def _sync():
            db_path = get_db_path()
            try:
                if self.check_need_download(db_path):
                    merged = self.merge_from_remote(db_path)
                    logger.info(f"Post-query merged: {merged} changes")
                if self.check_need_upload(db_path):
                    self.upload(db_path)
            except Exception as e:
                logger.warning(f"Post-query sync failed: {e}")

        threading.Thread(target=_sync, daemon=True).start()

    @property
    def last_sync_time(self) -> str:
        return self._last_sync_time


# Global singleton
sync_service = SyncService()
