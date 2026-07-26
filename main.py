"""AstrBot entry point for the QQ group profile plugin."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.api.web import error_response, json_response, request
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .storage import GroupMemoryDatabase


PLUGIN_NAME = "astrbot_plugin_group_memory"
QQ_PLATFORM_FILTER = (
    filter.PlatformAdapterType.AIOCQHTTP
    | filter.PlatformAdapterType.QQOFFICIAL
    | filter.PlatformAdapterType.QQOFFICIAL_WEBHOOK
)


class GroupMemoryPlugin(Star):
    """QQ group message recorder with basic group-member management commands."""

    WARNING_LOG_INTERVAL_SECONDS = 60

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self.database: GroupMemoryDatabase | None = None
        self.database_ready = False
        self._last_warning_log_at: dict[str, float] = {}

        context.register_web_api(
            f"/{PLUGIN_NAME}/members",
            self.webui_members,
            ["GET"],
            "List recorded QQ group members for the plugin Page.",
        )

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

    @filter.command("群档案状态", alias={"group-profile-status"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(QQ_PLATFORM_FILTER)
    async def group_profile_status(self, event: AstrMessageEvent):
        """显示插件与 SQLite 数据库状态。"""
        if self.database_ready:
            yield event.plain_result("QQ 群档案插件已启动，SQLite 数据库已就绪。")
            return
        yield event.plain_result("QQ 群档案插件已启动，但 SQLite 数据库尚未就绪，请检查日志。")

    @filter.command("备注", alias={"group-memory-note"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(QQ_PLATFORM_FILTER)
    async def note_command(self, event: AstrMessageEvent):
        """管理群内成员备注：/备注 添加 QQ号 内容，/备注 查看 [QQ号]。"""
        scope = self._get_command_scope(event)
        if scope is None:
            yield event.plain_result("无法读取当前群或用户信息。")
            return
        action, target_user_id, content = self._parse_member_command(
            event, "备注", default_target_user_id=scope[2]
        )
        if action == "查看":
            try:
                note = await self._database_call(
                    "note-read-failed",
                    self.database.get_note,
                    platform_id=scope[0],
                    external_group_id=scope[1],
                    external_user_id=target_user_id,
                )
            except (ValueError, sqlite3.Error, OSError):
                yield event.plain_result("读取备注失败，数据库暂时不可用。")
                return
            message = note if note else "暂无备注"
            yield event.plain_result(f"成员 {target_user_id} 的群内备注：{message}")
            return
        if action != "添加" or not content:
            yield event.plain_result("用法：/备注 添加 QQ号 备注内容，或 /备注 查看 [QQ号]")
            return
        try:
            await self._database_call(
                "note-write-failed",
                self.database.set_note,
                platform_id=scope[0],
                external_group_id=scope[1],
                external_user_id=target_user_id,
                content=content,
            )
        except (ValueError, sqlite3.Error, OSError):
            yield event.plain_result("保存备注失败：目标成员尚无消息记录，或数据库暂时不可用。")
            return
        yield event.plain_result(f"已保存成员 {target_user_id} 的群内备注。")

    @filter.command("标签", alias={"group-memory-tag"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(QQ_PLATFORM_FILTER)
    async def tag_command(self, event: AstrMessageEvent):
        """管理群内成员标签：/标签 添加 QQ号 标签，/标签 查看 [QQ号]。"""
        scope = self._get_command_scope(event)
        if scope is None:
            yield event.plain_result("无法读取当前群或用户信息。")
            return
        action, target_user_id, tag_name = self._parse_member_command(
            event, "标签", default_target_user_id=scope[2]
        )
        if action == "查看":
            try:
                tags = await self._database_call(
                    "tag-read-failed",
                    self.database.list_tags,
                    platform_id=scope[0],
                    external_group_id=scope[1],
                    external_user_id=target_user_id,
                )
            except (ValueError, sqlite3.Error, OSError):
                yield event.plain_result("读取标签失败，数据库暂时不可用。")
                return
            display_tags = "、".join(tags) if tags else "暂无标签"
            yield event.plain_result(f"成员 {target_user_id} 的标签：{display_tags}")
            return
        if action != "添加" or not tag_name:
            yield event.plain_result("用法：/标签 添加 QQ号 标签，或 /标签 查看 [QQ号]")
            return
        try:
            added = await self._database_call(
                "tag-write-failed",
                self.database.add_tag,
                platform_id=scope[0],
                external_group_id=scope[1],
                external_user_id=target_user_id,
                tag_name=tag_name,
            )
        except (ValueError, sqlite3.Error, OSError):
            yield event.plain_result("添加标签失败：目标成员尚无消息记录，或数据库暂时不可用。")
            return
        result = "已添加" if added else "标签已存在"
        yield event.plain_result(f"{result}：成员 {target_user_id} - {tag_name}")

    @filter.command("记忆", alias={"group-memory"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(QQ_PLATFORM_FILTER)
    async def memory_command(self, event: AstrMessageEvent):
        """查看或清理群的手动长期记忆：/记忆 列表，/记忆 清理。"""
        scope = self._get_command_scope(event)
        if scope is None:
            yield event.plain_result("无法读取当前群信息。")
            return
        action = self._parse_action(event, "记忆")
        if action == "列表":
            try:
                memories = await self._database_call(
                    "memory-read-failed",
                    self.database.list_memories,
                    platform_id=scope[0],
                    external_group_id=scope[1],
                )
            except (ValueError, sqlite3.Error, OSError):
                yield event.plain_result("读取记忆失败，数据库暂时不可用。")
                return
            if not memories:
                yield event.plain_result("当前群暂无手动长期记忆。")
                return
            lines = [f"#{item['id']} {item['content']}" for item in memories]
            yield event.plain_result("当前群记忆：\n" + "\n".join(lines))
            return
        if action == "清理":
            try:
                count = await self._database_call(
                    "memory-clear-failed",
                    self.database.clear_memories,
                    platform_id=scope[0],
                    external_group_id=scope[1],
                )
            except (ValueError, sqlite3.Error, OSError):
                yield event.plain_result("清理记忆失败，数据库暂时不可用。")
                return
            yield event.plain_result(f"已清理当前群 {count} 条手动长期记忆。")
            return
        yield event.plain_result("用法：/记忆 列表，或 /记忆 清理")

    @filter.command("画像", alias={"group-memory-profile"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(QQ_PLATFORM_FILTER)
    async def profile_command(self, event: AstrMessageEvent):
        """查看基础画像：/画像 查看 [QQ号]。"""
        scope = self._get_command_scope(event)
        if scope is None:
            yield event.plain_result("无法读取当前群或用户信息。")
            return
        action, target_user_id, _ = self._parse_member_command(
            event, "画像", default_target_user_id=scope[2]
        )
        if action != "查看":
            yield event.plain_result("用法：/画像 查看 [QQ号]")
            return
        try:
            profile = await self._database_call(
                "profile-read-failed",
                self.database.get_profile_overview,
                platform_id=scope[0],
                external_group_id=scope[1],
                external_user_id=target_user_id,
            )
        except (ValueError, sqlite3.Error, OSError):
            yield event.plain_result("读取画像失败，数据库暂时不可用。")
            return
        if profile is None:
            yield event.plain_result("目标成员尚无消息记录。")
            return
        nickname = profile["nickname"] or "未获取昵称"
        tags = "、".join(profile["tags"]) if profile["tags"] else "暂无"
        note = profile["note"] or "暂无"
        yield event.plain_result(
            "基础画像\n"
            f"成员：{nickname} ({profile['external_user_id']})\n"
            f"消息数：{profile['message_count']}\n"
            f"标签：{tags}\n"
            f"备注：{note}\n"
            "自动画像：尚未启用"
        )

    @filter.command("配置", alias={"group-memory-config"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(QQ_PLATFORM_FILTER)
    async def config_command(self, event: AstrMessageEvent):
        """管理插件内部配置：/配置 查看 [键]，/配置 修改 键 值。"""
        action, key, value = self._parse_config_command(event)
        if action == "查看":
            try:
                config_value = await self._database_call(
                    "config-read-failed",
                    self.database.get_config_value,
                    key or "webui_member_limit",
                    None,
                )
            except (ValueError, sqlite3.Error, OSError):
                yield event.plain_result("读取插件配置失败，数据库暂时不可用。")
                return
            actual_key = key or "webui_member_limit"
            if config_value is None:
                yield event.plain_result(f"插件内部配置 {actual_key} 尚未设置。")
                return
            yield event.plain_result(f"插件内部配置：{actual_key} = {config_value}")
            return
        if action == "修改" and key and value:
            try:
                await self._database_call(
                    "config-write-failed",
                    self.database.set_config_value,
                    key,
                    value,
                )
            except (ValueError, sqlite3.Error, OSError):
                yield event.plain_result("修改插件配置失败，数据库暂时不可用。")
                return
            yield event.plain_result(f"已保存插件内部配置：{key} = {value}")
            return
        yield event.plain_result(
            "用法：/配置 查看 [键]，或 /配置 修改 键 值\n"
            "当前可用键：webui_member_limit"
        )

    async def webui_members(self):
        """Return a read-only member list to the bundled AstrBot plugin Page."""
        if not self.database_ready or self.database is None:
            return error_response("数据库尚未就绪", status_code=503)
        database = self.database
        try:
            configured_limit = await asyncio.to_thread(
                database.get_config_value,
                "webui_member_limit",
                str(GroupMemoryDatabase.DEFAULT_WEBUI_MEMBER_LIMIT),
            )
            requested_limit = request.query.get("limit", configured_limit, type=int)
            members = await asyncio.to_thread(
                database.list_member_overview, requested_limit
            )
        except (TypeError, ValueError, sqlite3.Error, OSError):
            self._log_exception_throttled(
                "webui-members-failed", "QQ 群档案插件读取 WebUI 成员数据失败。"
            )
            return error_response("读取成员数据失败", status_code=500)
        return json_response({"members": members, "count": len(members)})

    async def _database_call(self, warning_key: str, operation, *args, **kwargs):
        """Run short SQLite operations away from AstrBot's event loop."""
        if not self.database_ready or self.database is None:
            self._log_warning_throttled(
                "database-not-ready-command", "QQ 群档案插件数据库未就绪，命令无法完成。"
            )
            raise OSError("database is not ready")
        try:
            return await asyncio.to_thread(operation, *args, **kwargs)
        except ValueError:
            raise
        except (sqlite3.Error, OSError):
            self._log_exception_throttled(
                warning_key, "QQ 群档案插件命令数据库操作失败。"
            )
            raise

    def _get_command_scope(
        self, event: AstrMessageEvent
    ) -> tuple[str, str, str] | None:
        try:
            platform_id = self._as_text(event.get_platform_id())
            if not platform_id:
                platform_id = self._as_text(event.get_platform_name())
            group_id = self._as_text(event.get_group_id())
            user_id = self._as_text(event.get_sender_id())
        except (AttributeError, TypeError, ValueError):
            self._log_exception_throttled(
                "command-fields-invalid", "QQ 群档案插件无法读取命令上下文。"
            )
            return None
        if not platform_id or not group_id or not user_id:
            return None
        return platform_id, group_id, user_id

    def _parse_member_command(
        self,
        event: AstrMessageEvent,
        command_name: str,
        *,
        default_target_user_id: str,
    ) -> tuple[str, str, str]:
        parts = self._command_parts(event, command_name)
        action = parts[0] if parts else ""
        if action == "查看":
            return action, parts[1] if len(parts) > 1 else default_target_user_id, ""
        if action == "添加" and len(parts) >= 3:
            return action, parts[1], " ".join(parts[2:]).strip()
        return action, default_target_user_id, ""

    def _parse_action(self, event: AstrMessageEvent, command_name: str) -> str:
        parts = self._command_parts(event, command_name)
        return parts[0] if parts else ""

    def _parse_config_command(
        self, event: AstrMessageEvent
    ) -> tuple[str, str, str]:
        parts = self._command_parts(event, "配置")
        action = parts[0] if parts else ""
        if action == "查看":
            return action, parts[1] if len(parts) > 1 else "", ""
        if action == "修改" and len(parts) >= 3:
            return action, parts[1], " ".join(parts[2:]).strip()
        return action, "", ""

    def _command_parts(self, event: AstrMessageEvent, command_name: str) -> list[str]:
        """Extract arguments whether AstrBot retains the command token or not."""
        try:
            raw_text = self._as_message_content(event.get_message_str()).strip()
        except (AttributeError, TypeError, ValueError):
            return []
        if not raw_text:
            return []
        tokens = raw_text.split()
        first_token = tokens[0] if tokens else ""
        first = first_token.lstrip("/")
        if first_token.startswith("/") or first == command_name:
            return tokens[1:]
        return tokens

    @staticmethod
    def _as_text(value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _as_message_content(value: object) -> str:
        return "" if value is None else str(value)

    def _get_message_timestamp(
        self,
        message_obj: object,
        *,
        platform_id: str,
        group_id: str,
        user_id: str,
        message_id: str,
    ) -> int:
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
        if self._should_log_warning(key):
            logger.warning(message, *args)

    def _log_exception_throttled(self, key: str, message: str, *args: object) -> None:
        if self._should_log_warning(key):
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
