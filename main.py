"""AstrBot entry point for the QQ group profile plugin skeleton."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .storage import GroupMemoryDatabase


QQ_PLATFORM_FILTER = (
    filter.PlatformAdapterType.AIOCQHTTP
    | filter.PlatformAdapterType.QQOFFICIAL
    | filter.PlatformAdapterType.QQOFFICIAL_WEBHOOK
)


class GroupMemoryPlugin(Star):
    """Minimal, QQ-group-only foundation for future group profile features."""

    WARNING_LOG_INTERVAL_SECONDS = 60

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self.database: GroupMemoryDatabase | None = None
        self.database_ready = False
        self._last_warning_log_at: dict[str, float] = {}

        try:
            database_path = self._get_database_path()
            self.database = GroupMemoryDatabase(database_path)
            self.database.initialize()
            self.database_ready = True
            logger.info("QQ 群档案插件已初始化 SQLite 数据库。")
        except (OSError, sqlite3.Error, ValueError):
            logger.exception("QQ 群档案插件无法初始化 SQLite 数据库。")

    def _get_database_path(self) -> Path:
        """Build a safe database path in AstrBot's persistent plugin-data area."""
        filename = str(self.config.get("database_filename", "group_memory.db")).strip()
        candidate = Path(filename)
        if candidate.name != filename or candidate.suffix.lower() != ".db":
            raise ValueError("database_filename must be a .db file name")

        plugin_data_dir = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        return plugin_data_dir / candidate

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(QQ_PLATFORM_FILTER)
    async def on_qq_group_message(self, event: AstrMessageEvent):
        """Persist QQ group text messages without replying to the sender."""
        if not self.config.get("listen_enabled", True):
            return

        try:
            message_obj = getattr(event, "message_obj", None)
            group_id = self._as_text(event.get_group_id())
            user_id = self._as_text(event.get_sender_id())
            platform_id = self._as_text(event.get_platform_id())
            platform_name = self._as_text(event.get_platform_name())
            message_id = self._as_text(getattr(message_obj, "message_id", None))
            user_nickname = self._as_text(event.get_sender_name())
            message_content = self._as_message_content(event.get_message_str())
        except (AttributeError, TypeError, ValueError):
            self._log_exception_throttled(
                "event-fields-invalid",
                "QQ 群档案插件无法读取群消息字段。",
            )
            return

        if not platform_id:
            platform_id = platform_name
        if not platform_name:
            platform_name = platform_id
        if not group_id or not user_id or not platform_id:
            logger.debug(
                "QQ 群档案插件跳过缺少身份字段的群消息: "
                "platform_id=%s group_id=%s user_id=%s message_id=%s",
                platform_id,
                group_id,
                user_id,
                message_id,
            )
            return

        if not self.database_ready or self.database is None:
            self._log_warning_throttled(
                "database-not-ready",
                "QQ 群档案插件数据库未就绪，已跳过群消息记录: "
                "platform_id=%s group_id=%s user_id=%s message_id=%s",
                platform_id,
                group_id,
                user_id,
                message_id,
            )
            return

        group = getattr(message_obj, "group", None)
        group_name = self._as_text(getattr(group, "group_name", None))
        timestamp = self._get_message_timestamp(
            message_obj,
            platform_id=platform_id,
            group_id=group_id,
            user_id=user_id,
            message_id=message_id,
        )

        try:
            inserted = await asyncio.to_thread(
                self.database.record_group_message,
                platform_id=platform_id,
                platform_name=platform_name,
                external_group_id=group_id,
                group_name=group_name,
                external_user_id=user_id,
                user_nickname=user_nickname,
                platform_message_id=message_id,
                content=message_content,
                message_timestamp=timestamp,
            )
        except (AttributeError, TypeError, ValueError, sqlite3.Error, OSError):
            self._log_exception_throttled(
                "database-write-failed",
                "QQ 群档案插件写入群消息失败: "
                "platform_id=%s group_id=%s user_id=%s message_id=%s",
                platform_id,
                group_id,
                user_id,
                message_id,
            )
            return

        logger.debug(
            "QQ 群档案插件%s群消息: group_id=%s, message_id=%s",
            "已记录" if inserted else "已跳过重复",
            group_id,
            message_id,
        )

    @staticmethod
    def _as_text(value: object) -> str:
        """Normalize optional AstrBot values before storing them."""
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _as_message_content(value: object) -> str:
        """Store message text verbatim while keeping absent text as an empty value."""
        if value is None:
            return ""
        return str(value)

    def _get_message_timestamp(
        self,
        message_obj: object,
        *,
        platform_id: str,
        group_id: str,
        user_id: str,
        message_id: str,
    ) -> int:
        """Normalize source timestamps to Unix seconds with a safe fallback."""
        try:
            timestamp = int(getattr(message_obj, "timestamp", 0))
        except (TypeError, ValueError):
            timestamp = 0

        if timestamp <= 0:
            return int(time.time())
        if timestamp >= GroupMemoryDatabase.MILLISECONDS_TIMESTAMP_THRESHOLD:
            self._log_warning_throttled(
                "timestamp-milliseconds",
                "QQ 群档案插件检测到毫秒时间戳，已转换为 Unix 秒: "
                "platform_id=%s group_id=%s user_id=%s message_id=%s",
                platform_id,
                group_id,
                user_id,
                message_id,
            )
            return timestamp // 1_000
        return timestamp

    def _log_warning_throttled(self, key: str, message: str, *args: object) -> None:
        """Avoid repeated operational warnings during high-volume message traffic."""
        if not self._should_log_warning(key):
            return
        logger.warning(message, *args)

    def _log_exception_throttled(self, key: str, message: str, *args: object) -> None:
        """Keep the first exception traceback while preventing repeated log floods."""
        if not self._should_log_warning(key):
            return
        logger.exception(message, *args)

    def _should_log_warning(self, key: str) -> bool:
        now = time.monotonic()
        last_logged_at = self._last_warning_log_at.get(key)
        if (
            last_logged_at is not None
            and now - last_logged_at < self.WARNING_LOG_INTERVAL_SECONDS
        ):
            return False
        self._last_warning_log_at[key] = now
        return True

    @filter.command("群档案状态", alias={"group-profile-status"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(QQ_PLATFORM_FILTER)
    async def group_profile_status(self, event: AstrMessageEvent):
        """显示插件骨架的启动与数据库状态。"""
        if self.database_ready:
            yield event.plain_result("QQ 群档案插件已启动，SQLite 数据库已就绪。")
            return

        yield event.plain_result("QQ 群档案插件已启动，但 SQLite 数据库尚未就绪，请检查日志。")

    async def terminate(self) -> None:
        """Release resources when AstrBot unloads or disables this plugin."""
        if self.database is not None:
            try:
                self.database.close()
            except (OSError, sqlite3.Error, ValueError):
                logger.exception("QQ 群档案插件关闭数据库时出错。")
            finally:
                self.database = None
                self.database_ready = False
        logger.info("QQ 群档案插件已停止。")
