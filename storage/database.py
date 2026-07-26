"""SQLite storage and schema migrations for the QQ group profile plugin."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar


Result = TypeVar("Result")


class GroupMemoryDatabase:
    """Own the plugin SQLite schema and its small, synchronous data API.

    ``users`` is deliberately platform-level, keyed by ``platform_id`` and an
    external user ID. Fields that can differ between groups, such as notes and
    tags, use both ``group_id`` and ``user_id``. A future ``group_members``
    table can add QQ group cards or other membership-only fields without
    changing the current identity model.
    """

    SCHEMA_VERSION = 3
    BUSY_TIMEOUT_MS = 1_000
    WRITE_RETRY_ATTEMPTS = 3
    WRITE_RETRY_DELAY_SECONDS = 0.05
    MILLISECONDS_TIMESTAMP_THRESHOLD = 100_000_000_000
    DEFAULT_WEBUI_MEMBER_LIMIT = 100
    MAX_WEBUI_MEMBER_LIMIT = 500

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        """Create or repair every supported table and index before use."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_with_retry(self._initialize_connection)

    def close(self) -> None:
        """Provide a stable shutdown interface for the plugin lifecycle.

        Every operation owns its SQLite connection through a context manager,
        so this helper intentionally has no persistent connection to close.
        """
        return None

    def record_group_message(
        self,
        *,
        platform_id: str,
        platform_name: str,
        external_group_id: str,
        group_name: str | None,
        external_user_id: str,
        user_nickname: str | None,
        platform_message_id: str,
        content: str,
        message_timestamp: int,
    ) -> bool:
        """Persist one group message and create its base records when needed.

        A repeated non-empty platform message ID has no side effects. The
        duplicate check runs before profile upserts, so replayed events cannot
        overwrite a nickname or group name.
        """
        platform_id = self._require_identifier("platform_id", platform_id)
        platform_name = self._require_identifier("platform_name", platform_name)
        external_group_id = self._require_identifier(
            "external_group_id", external_group_id
        )
        external_user_id = self._require_identifier(
            "external_user_id", external_user_id
        )
        message_timestamp = self._require_timestamp(message_timestamp)
        group_name = self._optional_text(group_name)
        user_nickname = self._optional_text(user_nickname)
        platform_message_id = self._optional_text(platform_message_id) or ""
        content = self._message_content(content)

        return self._run_with_retry(
            lambda connection: self._record_group_message_in_transaction(
                connection,
                platform_id=platform_id,
                platform_name=platform_name,
                external_group_id=external_group_id,
                group_name=group_name,
                external_user_id=external_user_id,
                user_nickname=user_nickname,
                platform_message_id=platform_message_id,
                content=content,
                message_timestamp=message_timestamp,
            )
        )

    def set_note(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        content: str,
    ) -> None:
        """Create or replace one group-scoped manual note for a known member."""
        content = self._require_identifier("content", content)
        self._run_with_retry(
            lambda connection: self._set_note_in_transaction(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                external_user_id=self._require_identifier(
                    "external_user_id", external_user_id
                ),
                content=content,
            )
        )

    def get_note(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
    ) -> str | None:
        """Return a group-scoped note, or ``None`` when no note exists."""
        return self._run_with_retry(
            lambda connection: self._get_note(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                external_user_id=self._require_identifier(
                    "external_user_id", external_user_id
                ),
            )
        )

    def add_tag(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        tag_name: str,
    ) -> bool:
        """Attach a tag to a known member. Return whether it was newly added."""
        return self._run_with_retry(
            lambda connection: self._add_tag_in_transaction(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                external_user_id=self._require_identifier(
                    "external_user_id", external_user_id
                ),
                tag_name=self._require_identifier("tag_name", tag_name),
            )
        )

    def list_tags(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
    ) -> list[str]:
        """Return the member tags in stable alphabetical order."""
        return self._run_with_retry(
            lambda connection: self._list_tags(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                external_user_id=self._require_identifier(
                    "external_user_id", external_user_id
                ),
            )
        )

    def get_profile_overview(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
    ) -> dict[str, object] | None:
        """Return the minimal non-AI profile data for one group member."""
        return self._run_with_retry(
            lambda connection: self._get_profile_overview(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                external_user_id=self._require_identifier(
                    "external_user_id", external_user_id
                ),
            )
        )

    def list_memories(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """List manual long-term memory entries for the current group."""
        return self._run_with_retry(
            lambda connection: self._list_memories(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                limit=self._normalize_limit(limit, default=20, maximum=100),
            )
        )

    def clear_memories(
        self,
        *,
        platform_id: str,
        external_group_id: str,
    ) -> int:
        """Delete only manual memory entries for one group, never messages."""
        return self._run_with_retry(
            lambda connection: self._clear_memories_in_transaction(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
            )
        )

    def get_config_value(self, key: str, default: str | None = None) -> str | None:
        """Read one plugin-internal configuration value."""
        key = self._require_identifier("key", key)
        return self._run_with_retry(
            lambda connection: self._get_config_value(connection, key, default)
        )

    def set_config_value(self, key: str, value: str) -> None:
        """Persist one plugin-internal configuration value."""
        key = self._require_identifier("key", key)
        value = self._require_identifier("value", value)
        self._run_with_retry(
            lambda connection: self._set_config_value_in_transaction(
                connection, key, value
            )
        )

    def list_member_overview(self, limit: int | None = None) -> list[dict[str, object]]:
        """Return recent group-member data for the read-only plugin Page."""
        requested_limit = (
            self.DEFAULT_WEBUI_MEMBER_LIMIT if limit is None else int(limit)
        )
        return self._run_with_retry(
            lambda connection: self._list_member_overview(
                connection,
                limit=self._normalize_limit(
                    requested_limit,
                    default=self.DEFAULT_WEBUI_MEMBER_LIMIT,
                    maximum=self.MAX_WEBUI_MEMBER_LIMIT,
                ),
            )
        )

    def _initialize_connection(self, connection: sqlite3.Connection) -> None:
        self._create_metadata_table(connection)
        schema_version = self._get_schema_version(connection)
        if schema_version > self.SCHEMA_VERSION:
            raise ValueError(
                "Database schema is newer than this plugin version supports."
            )

        # These operations are deliberately idempotent. They repair a database
        # labelled v2/v3 when a table or index was removed outside the plugin.
        self._ensure_version_2_schema(connection)
        self._ensure_version_3_schema(connection)
        self._backfill_profiles(connection)
        self._validate_version_2_schema(connection)
        self._validate_version_3_schema(connection)

        if schema_version < self.SCHEMA_VERSION:
            self._set_schema_version(connection, self.SCHEMA_VERSION)

    def _record_group_message_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        platform_name: str,
        external_group_id: str,
        group_name: str | None,
        external_user_id: str,
        user_nickname: str | None,
        platform_message_id: str,
        content: str,
        message_timestamp: int,
    ) -> bool:
        connection.execute("BEGIN IMMEDIATE")
        if platform_message_id:
            duplicate = connection.execute(
                """
                SELECT 1 FROM "messages"
                WHERE platform_id = ? AND platform_message_id = ?
                """,
                (platform_id, platform_message_id),
            ).fetchone()
            if duplicate is not None:
                return False

        group_id = self._upsert_group(
            connection,
            platform_id=platform_id,
            platform_name=platform_name,
            external_group_id=external_group_id,
            group_name=group_name,
        )
        user_id = self._upsert_user(
            connection,
            platform_id=platform_id,
            platform_name=platform_name,
            external_user_id=external_user_id,
            nickname=user_nickname,
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO "profiles" (user_id)
            VALUES (?)
            """,
            (user_id,),
        )
        cursor = connection.execute(
            """
            INSERT INTO "messages" (
                group_id, user_id, platform_id, platform_name,
                platform_message_id, content, message_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                group_id,
                user_id,
                platform_id,
                platform_name,
                platform_message_id,
                content,
                message_timestamp,
            ),
        )
        return cursor.rowcount == 1

    @staticmethod
    def _upsert_group(
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        platform_name: str,
        external_group_id: str,
        group_name: str | None,
    ) -> int:
        connection.execute(
            """
            INSERT INTO "groups" (
                platform_id, platform_name, external_group_id, group_name
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(platform_id, external_group_id) DO UPDATE SET
                platform_name = excluded.platform_name,
                group_name = COALESCE(excluded.group_name, "groups".group_name),
                updated_at = CURRENT_TIMESTAMP
            """,
            (platform_id, platform_name, external_group_id, group_name),
        )
        return connection.execute(
            """
            SELECT id FROM "groups"
            WHERE platform_id = ? AND external_group_id = ?
            """,
            (platform_id, external_group_id),
        ).fetchone()[0]

    @staticmethod
    def _upsert_user(
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        platform_name: str,
        external_user_id: str,
        nickname: str | None,
    ) -> int:
        connection.execute(
            """
            INSERT INTO "users" (
                platform_id, platform_name, external_user_id, nickname
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(platform_id, external_user_id) DO UPDATE SET
                platform_name = excluded.platform_name,
                nickname = COALESCE(excluded.nickname, "users".nickname),
                updated_at = CURRENT_TIMESTAMP
            """,
            (platform_id, platform_name, external_user_id, nickname),
        )
        return connection.execute(
            """
            SELECT id FROM "users"
            WHERE platform_id = ? AND external_user_id = ?
            """,
            (platform_id, external_user_id),
        ).fetchone()[0]

    def _set_note_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        content: str,
    ) -> None:
        connection.execute("BEGIN IMMEDIATE")
        member_ids = self._find_member_ids(
            connection,
            platform_id=platform_id,
            external_group_id=external_group_id,
            external_user_id=external_user_id,
        )
        if member_ids is None:
            raise ValueError("Target group member has not been recorded yet.")
        group_id, user_id = member_ids
        connection.execute(
            """
            INSERT INTO "notes" (group_id, user_id, content)
            VALUES (?, ?, ?)
            ON CONFLICT(group_id, user_id) DO UPDATE SET
                content = excluded.content,
                updated_at = CURRENT_TIMESTAMP
            """,
            (group_id, user_id, content),
        )

    def _get_note(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
    ) -> str | None:
        row = connection.execute(
            """
            SELECT n.content
            FROM "notes" AS n
            JOIN "groups" AS g ON g.id = n.group_id
            JOIN "users" AS u ON u.id = n.user_id
            WHERE g.platform_id = ?
              AND g.external_group_id = ?
              AND u.external_user_id = ?
            """,
            (platform_id, external_group_id, external_user_id),
        ).fetchone()
        return None if row is None else str(row[0])

    def _add_tag_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        tag_name: str,
    ) -> bool:
        connection.execute("BEGIN IMMEDIATE")
        member_ids = self._find_member_ids(
            connection,
            platform_id=platform_id,
            external_group_id=external_group_id,
            external_user_id=external_user_id,
        )
        if member_ids is None:
            raise ValueError("Target group member has not been recorded yet.")
        group_id, user_id = member_ids
        connection.execute(
            """
            INSERT INTO "tags" (name)
            VALUES (?)
            ON CONFLICT(name) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
            """,
            (tag_name,),
        )
        tag_id = connection.execute(
            'SELECT id FROM "tags" WHERE name = ? COLLATE NOCASE', (tag_name,)
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO "user_tags" (group_id, user_id, tag_id)
            VALUES (?, ?, ?)
            """,
            (group_id, user_id, tag_id),
        )
        return cursor.rowcount == 1

    def _list_tags(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
    ) -> list[str]:
        rows = connection.execute(
            """
            SELECT t.name
            FROM "user_tags" AS ut
            JOIN "tags" AS t ON t.id = ut.tag_id
            JOIN "groups" AS g ON g.id = ut.group_id
            JOIN "users" AS u ON u.id = ut.user_id
            WHERE g.platform_id = ?
              AND g.external_group_id = ?
              AND u.external_user_id = ?
            ORDER BY t.name COLLATE NOCASE
            """,
            (platform_id, external_group_id, external_user_id),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def _get_profile_overview(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
    ) -> dict[str, object] | None:
        row = connection.execute(
            """
            SELECT
                u.external_user_id,
                u.nickname,
                p.summary,
                COUNT(m.id) AS message_count,
                MAX(m.message_timestamp) AS last_message_timestamp,
                n.content AS note
            FROM "groups" AS g
            JOIN "users" AS u
              ON u.platform_id = g.platform_id
             AND u.external_user_id = ?
            LEFT JOIN "profiles" AS p ON p.user_id = u.id
            LEFT JOIN "messages" AS m ON m.group_id = g.id AND m.user_id = u.id
            LEFT JOIN "notes" AS n ON n.group_id = g.id AND n.user_id = u.id
            WHERE g.platform_id = ?
              AND g.external_group_id = ?
              AND EXISTS (
                  SELECT 1
                  FROM "messages" AS member_message
                  WHERE member_message.group_id = g.id
                    AND member_message.user_id = u.id
              )
            GROUP BY u.id, g.id
            """,
            (external_user_id, platform_id, external_group_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "external_user_id": str(row[0]),
            "nickname": row[1] or "",
            "summary": row[2] or "",
            "message_count": int(row[3] or 0),
            "last_message_timestamp": row[4],
            "note": row[5] or "",
            "tags": self._list_tags(
                connection,
                platform_id=platform_id,
                external_group_id=external_group_id,
                external_user_id=external_user_id,
            ),
        }

    def _list_memories(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        limit: int,
    ) -> list[dict[str, object]]:
        rows = connection.execute(
            """
            SELECT m.id, m.content, m.created_at, u.external_user_id, u.nickname
            FROM "memories" AS m
            JOIN "groups" AS g ON g.id = m.group_id
            LEFT JOIN "users" AS u ON u.id = m.user_id
            WHERE g.platform_id = ? AND g.external_group_id = ?
            ORDER BY m.id DESC
            LIMIT ?
            """,
            (platform_id, external_group_id, limit),
        ).fetchall()
        return [
            {
                "id": int(row[0]),
                "content": str(row[1]),
                "created_at": str(row[2]),
                "external_user_id": row[3] or "",
                "nickname": row[4] or "",
            }
            for row in rows
        ]

    def _clear_memories_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
    ) -> int:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            DELETE FROM "memories"
            WHERE group_id = (
                SELECT id FROM "groups"
                WHERE platform_id = ? AND external_group_id = ?
            )
            """,
            (platform_id, external_group_id),
        )
        return cursor.rowcount

    @staticmethod
    def _get_config_value(
        connection: sqlite3.Connection, key: str, default: str | None
    ) -> str | None:
        row = connection.execute(
            'SELECT value FROM "config" WHERE key = ?', (key,)
        ).fetchone()
        return default if row is None else str(row[0])

    @staticmethod
    def _set_config_value_in_transaction(
        connection: sqlite3.Connection, key: str, value: str
    ) -> None:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO "config" (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )

    @staticmethod
    def _list_member_overview(
        connection: sqlite3.Connection, *, limit: int
    ) -> list[dict[str, object]]:
        rows = connection.execute(
            """
            SELECT
                g.platform_name,
                g.external_group_id,
                g.group_name,
                u.external_user_id,
                u.nickname,
                COUNT(m.id) AS message_count,
                MAX(m.message_timestamp) AS last_message_timestamp,
                n.content AS note,
                COALESCE((
                    SELECT GROUP_CONCAT(tag_name, ', ')
                    FROM (
                        SELECT t.name AS tag_name
                        FROM "user_tags" AS ut
                        JOIN "tags" AS t ON t.id = ut.tag_id
                        WHERE ut.group_id = g.id AND ut.user_id = u.id
                        ORDER BY t.name COLLATE NOCASE
                    )
                ), '') AS tags
            FROM "messages" AS m
            JOIN "groups" AS g ON g.id = m.group_id
            JOIN "users" AS u ON u.id = m.user_id
            LEFT JOIN "notes" AS n ON n.group_id = g.id AND n.user_id = u.id
            GROUP BY g.id, u.id
            ORDER BY last_message_timestamp DESC, message_count DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "platform_name": row[0] or "",
                "external_group_id": str(row[1]),
                "group_name": row[2] or "",
                "external_user_id": str(row[3]),
                "nickname": row[4] or "",
                "message_count": int(row[5] or 0),
                "last_message_timestamp": row[6],
                "note": row[7] or "",
                "tags": row[8] or "",
            }
            for row in rows
        ]

    @staticmethod
    def _find_member_ids(
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
    ) -> tuple[int, int] | None:
        row = connection.execute(
            """
            SELECT g.id, u.id
            FROM "groups" AS g
            JOIN "users" AS u ON u.platform_id = g.platform_id
            JOIN "messages" AS m ON m.group_id = g.id AND m.user_id = u.id
            WHERE g.platform_id = ?
              AND g.external_group_id = ?
              AND u.external_user_id = ?
            LIMIT 1
            """,
            (platform_id, external_group_id, external_user_id),
        ).fetchone()
        if row is None:
            return None
        return int(row[0]), int(row[1])

    def _run_with_retry(self, operation: Callable[[sqlite3.Connection], Result]) -> Result:
        for attempt in range(self.WRITE_RETRY_ATTEMPTS):
            connection: sqlite3.Connection | None = None
            try:
                connection = self._connect()
                with connection:
                    return operation(connection)
            except sqlite3.OperationalError as error:
                if (
                    not self._is_busy_error(error)
                    or attempt + 1 >= self.WRITE_RETRY_ATTEMPTS
                ):
                    raise
                time.sleep(self.WRITE_RETRY_DELAY_SECONDS * (2**attempt))
            finally:
                if connection is not None:
                    connection.close()
        raise RuntimeError("SQLite retry loop exited unexpectedly.")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=self.BUSY_TIMEOUT_MS / 1_000,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.BUSY_TIMEOUT_MS}")
        return connection

    @staticmethod
    def _is_busy_error(error: sqlite3.OperationalError) -> bool:
        message = str(error).lower()
        return "database is locked" in message or "database is busy" in message

    @staticmethod
    def _create_metadata_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS plugin_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    @staticmethod
    def _get_schema_version(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT value FROM plugin_metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            return 0
        try:
            return int(row[0])
        except (TypeError, ValueError) as error:
            raise ValueError("Database schema version is invalid.") from error

    @staticmethod
    def _set_schema_version(connection: sqlite3.Connection, version: int) -> None:
        connection.execute(
            """
            INSERT INTO plugin_metadata (key, value)
            VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (str(version),),
        )

    @staticmethod
    def _ensure_version_2_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "groups" (
                id INTEGER PRIMARY KEY,
                platform_id TEXT NOT NULL,
                platform_name TEXT NOT NULL,
                external_group_id TEXT NOT NULL,
                group_name TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(platform_id, external_group_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "users" (
                id INTEGER PRIMARY KEY,
                platform_id TEXT NOT NULL,
                platform_name TEXT NOT NULL,
                external_user_id TEXT NOT NULL,
                nickname TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(platform_id, external_user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "messages" (
                id INTEGER PRIMARY KEY,
                group_id INTEGER NOT NULL REFERENCES "groups"(id),
                user_id INTEGER NOT NULL REFERENCES "users"(id),
                platform_id TEXT NOT NULL,
                platform_name TEXT NOT NULL,
                platform_message_id TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                message_timestamp INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_platform_message_id
            ON "messages" (platform_id, platform_message_id)
            WHERE platform_message_id <> ''
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_group_timestamp
            ON "messages" (group_id, message_timestamp)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_user_timestamp
            ON "messages" (user_id, message_timestamp)
            """
        )

    @staticmethod
    def _ensure_version_3_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "profiles" (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL UNIQUE REFERENCES "users"(id),
                summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_user
            ON "profiles" (user_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "relations" (
                id INTEGER PRIMARY KEY,
                group_id INTEGER NOT NULL REFERENCES "groups"(id),
                source_user_id INTEGER NOT NULL REFERENCES "users"(id),
                target_user_id INTEGER NOT NULL REFERENCES "users"(id),
                relation_type TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, source_user_id, target_user_id, relation_type)
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_identity
            ON "relations" (
                group_id, source_user_id, target_user_id, relation_type
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_relations_group_source
            ON "relations" (group_id, source_user_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_relations_group_target
            ON "relations" (group_id, target_user_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "notes" (
                id INTEGER PRIMARY KEY,
                group_id INTEGER NOT NULL REFERENCES "groups"(id),
                user_id INTEGER NOT NULL REFERENCES "users"(id),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notes_group_user
            ON "notes" (group_id, user_id)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_notes_group_user_unique
            ON "notes" (group_id, user_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "tags" (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "user_tags" (
                group_id INTEGER NOT NULL REFERENCES "groups"(id),
                user_id INTEGER NOT NULL REFERENCES "users"(id),
                tag_id INTEGER NOT NULL REFERENCES "tags"(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_id, user_id, tag_id)
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_name_unique
            ON "tags" (name COLLATE NOCASE)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_tags_group_user
            ON "user_tags" (group_id, user_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "config" (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "memories" (
                id INTEGER PRIMARY KEY,
                group_id INTEGER NOT NULL REFERENCES "groups"(id),
                user_id INTEGER REFERENCES "users"(id),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memories_group_created
            ON "memories" (group_id, id DESC)
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO "config" (key, value)
            VALUES ('webui_member_limit', '100')
            """
        )

    @staticmethod
    def _backfill_profiles(connection: sqlite3.Connection) -> None:
        """Give users from v2 databases an empty, extension-ready profile."""
        connection.execute(
            """
            INSERT OR IGNORE INTO "profiles" (user_id)
            SELECT id FROM "users"
            """
        )

    @classmethod
    def _validate_version_2_schema(cls, connection: sqlite3.Connection) -> None:
        cls._validate_required_columns(
            connection,
            {
                "plugin_metadata": {"key", "value", "updated_at"},
                "groups": {
                    "id",
                    "platform_id",
                    "platform_name",
                    "external_group_id",
                    "group_name",
                    "created_at",
                    "updated_at",
                },
                "users": {
                    "id",
                    "platform_id",
                    "platform_name",
                    "external_user_id",
                    "nickname",
                    "created_at",
                    "updated_at",
                },
                "messages": {
                    "id",
                    "group_id",
                    "user_id",
                    "platform_id",
                    "platform_name",
                    "platform_message_id",
                    "content",
                    "message_timestamp",
                    "created_at",
                },
            },
        )
        cls._validate_foreign_keys(
            connection,
            "messages",
            {("group_id", "groups", "id"), ("user_id", "users", "id")},
        )
        if not cls._has_unique_index(
            connection, "groups", ("platform_id", "external_group_id")
        ):
            raise ValueError("Database groups table is missing its unique identity key.")
        if not cls._has_unique_index(
            connection, "users", ("platform_id", "external_user_id")
        ):
            raise ValueError("Database users table is missing its unique identity key.")
        cls._validate_messages_indexes(connection)

    @classmethod
    def _validate_version_3_schema(cls, connection: sqlite3.Connection) -> None:
        cls._validate_required_columns(
            connection,
            {
                "profiles": {"id", "user_id", "summary", "created_at", "updated_at"},
                "relations": {
                    "id",
                    "group_id",
                    "source_user_id",
                    "target_user_id",
                    "relation_type",
                    "description",
                    "created_at",
                    "updated_at",
                },
                "notes": {
                    "id",
                    "group_id",
                    "user_id",
                    "content",
                    "created_at",
                    "updated_at",
                },
                "tags": {"id", "name", "created_at", "updated_at"},
                "user_tags": {"group_id", "user_id", "tag_id", "created_at"},
                "config": {"key", "value", "updated_at"},
                "memories": {
                    "id",
                    "group_id",
                    "user_id",
                    "content",
                    "created_at",
                    "updated_at",
                },
            },
        )
        cls._validate_foreign_keys(
            connection, "profiles", {("user_id", "users", "id")}
        )
        cls._validate_foreign_keys(
            connection,
            "relations",
            {
                ("group_id", "groups", "id"),
                ("source_user_id", "users", "id"),
                ("target_user_id", "users", "id"),
            },
        )
        cls._validate_foreign_keys(
            connection,
            "notes",
            {("group_id", "groups", "id"), ("user_id", "users", "id")},
        )
        cls._validate_foreign_keys(
            connection,
            "user_tags",
            {
                ("group_id", "groups", "id"),
                ("user_id", "users", "id"),
                ("tag_id", "tags", "id"),
            },
        )
        cls._validate_foreign_keys(
            connection,
            "memories",
            {("group_id", "groups", "id"), ("user_id", "users", "id")},
        )
        for table_name, columns in {
            "profiles": ("user_id",),
            "relations": (
                "group_id",
                "source_user_id",
                "target_user_id",
                "relation_type",
            ),
            "notes": ("group_id", "user_id"),
            "tags": ("name",),
        }.items():
            if not cls._has_unique_index(connection, table_name, columns):
                raise ValueError(
                    f"Database {table_name} table is missing its unique identity key."
                )

    @staticmethod
    def _validate_required_columns(
        connection: sqlite3.Connection, required_columns: dict[str, set[str]]
    ) -> None:
        for table_name, expected_columns in required_columns.items():
            columns = {
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{table_name}")')
            }
            missing_columns = expected_columns - columns
            if missing_columns:
                raise ValueError(
                    f"Database table {table_name} is incompatible; missing columns: "
                    f"{', '.join(sorted(missing_columns))}."
                )

    @staticmethod
    def _validate_foreign_keys(
        connection: sqlite3.Connection,
        table_name: str,
        required_foreign_keys: set[tuple[str, str, str]],
    ) -> None:
        foreign_keys = {
            (row[3], row[2], row[4])
            for row in connection.execute(f'PRAGMA foreign_key_list("{table_name}")')
        }
        if not required_foreign_keys <= foreign_keys:
            raise ValueError(
                f"Database {table_name} table is missing required foreign keys."
            )

    @staticmethod
    def _has_unique_index(
        connection: sqlite3.Connection,
        table_name: str,
        columns: tuple[str, ...],
    ) -> bool:
        for row in connection.execute(f'PRAGMA index_list("{table_name}")'):
            index_name, is_unique = row[1], bool(row[2])
            if not is_unique:
                continue
            index_columns = tuple(
                item[2]
                for item in connection.execute(f'PRAGMA index_info("{index_name}")')
            )
            if index_columns == columns:
                return True
        return False

    @staticmethod
    def _validate_messages_indexes(connection: sqlite3.Connection) -> None:
        expected_indexes = {
            "idx_messages_platform_message_id": (
                ("platform_id", "platform_message_id"),
                True,
                True,
            ),
            "idx_messages_group_timestamp": (
                ("group_id", "message_timestamp"),
                False,
                False,
            ),
            "idx_messages_user_timestamp": (
                ("user_id", "message_timestamp"),
                False,
                False,
            ),
        }
        indexes = {
            row[1]: (bool(row[2]), bool(row[4]))
            for row in connection.execute('PRAGMA index_list("messages")')
        }
        for index_name, (columns, is_unique, is_partial) in expected_indexes.items():
            properties = indexes.get(index_name)
            actual_columns = (
                tuple(
                    row[2]
                    for row in connection.execute(f'PRAGMA index_info("{index_name}")')
                )
                if properties is not None
                else ()
            )
            if properties != (is_unique, is_partial) or actual_columns != columns:
                raise ValueError(
                    f"Database messages index {index_name} is missing or incompatible."
                )

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _message_content(value: object) -> str:
        return "" if value is None else str(value)

    @classmethod
    def _require_identifier(cls, field_name: str, value: object) -> str:
        text = cls._optional_text(value)
        if text is None:
            raise ValueError(f"{field_name} must not be empty")
        return text

    @classmethod
    def _require_timestamp(cls, value: object) -> int:
        try:
            timestamp = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("message_timestamp must be an integer") from error
        if timestamp <= 0:
            raise ValueError("message_timestamp must be positive")
        if timestamp >= cls.MILLISECONDS_TIMESTAMP_THRESHOLD:
            return timestamp // 1_000
        return timestamp

    @staticmethod
    def _normalize_limit(value: object, *, default: int, maximum: int) -> int:
        try:
            limit = int(value)
        except (TypeError, ValueError):
            return default
        return min(max(limit, 1), maximum)
