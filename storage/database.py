"""SQLite storage and schema migrations for the QQ group profile plugin."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar


Result = TypeVar("Result")


class GroupMemoryDatabase:
    """Owns the SQLite schema and message persistence for this plugin.

    ``users`` stores platform-level identities keyed by ``platform_id`` and the
    external user ID. A future ``group_members`` table should hold group-specific
    fields such as group cards, notes, tags, and relationship data.
    """

    SCHEMA_VERSION = 2
    BUSY_TIMEOUT_MS = 1_000
    WRITE_RETRY_ATTEMPTS = 3
    WRITE_RETRY_DELAY_SECONDS = 0.05
    MILLISECONDS_TIMESTAMP_THRESHOLD = 100_000_000_000

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        """Create or repair the current schema before accepting messages."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_with_retry(self._initialize_connection)

    def close(self) -> None:
        """Provide a stable shutdown interface for the plugin lifecycle.

        Each operation owns and closes its SQLite connection via a context
        manager, so the database helper has no persistent connection to release.
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
        """Persist one group message after validating its basic identifiers.

        A repeated non-empty platform message ID has no side effects: it does not
        insert a second message and does not update group or user profile fields.
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

    def _initialize_connection(self, connection: sqlite3.Connection) -> None:
        self._create_metadata_table(connection)
        schema_version = self._get_schema_version(connection)

        if schema_version > self.SCHEMA_VERSION:
            raise ValueError(
                "Database schema is newer than this plugin version supports."
            )

        # Run this for every supported version. CREATE IF NOT EXISTS repairs a
        # database marked as v2 whose tables or indexes were removed manually.
        self._ensure_version_2_schema(connection)
        self._validate_version_2_schema(connection)
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
        """Store one message while holding a write transaction.

        BEGIN IMMEDIATE serializes duplicate checks with later profile upserts,
        so a replay cannot mutate basic profile data.
        """
        connection.execute("BEGIN IMMEDIATE")
        if platform_message_id:
            duplicate = connection.execute(
                """
                SELECT 1
                FROM "messages"
                WHERE platform_id = ? AND platform_message_id = ?
                """,
                (platform_id, platform_message_id),
            ).fetchone()
            if duplicate is not None:
                return False

        connection.execute(
            """
            INSERT INTO "groups" (
                platform_id,
                platform_name,
                external_group_id,
                group_name
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(platform_id, external_group_id) DO UPDATE SET
                platform_name = excluded.platform_name,
                group_name = COALESCE(excluded.group_name, "groups".group_name),
                updated_at = CURRENT_TIMESTAMP
            """,
            (platform_id, platform_name, external_group_id, group_name),
        )
        group_id = connection.execute(
            """
            SELECT id
            FROM "groups"
            WHERE platform_id = ? AND external_group_id = ?
            """,
            (platform_id, external_group_id),
        ).fetchone()[0]

        connection.execute(
            """
            INSERT INTO "users" (
                platform_id,
                platform_name,
                external_user_id,
                nickname
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(platform_id, external_user_id) DO UPDATE SET
                platform_name = excluded.platform_name,
                nickname = COALESCE(excluded.nickname, "users".nickname),
                updated_at = CURRENT_TIMESTAMP
            """,
            (platform_id, platform_name, external_user_id, user_nickname),
        )
        user_id = connection.execute(
            """
            SELECT id
            FROM "users"
            WHERE platform_id = ? AND external_user_id = ?
            """,
            (platform_id, external_user_id),
        ).fetchone()[0]

        cursor = connection.execute(
            """
            INSERT INTO "messages" (
                group_id,
                user_id,
                platform_id,
                platform_name,
                platform_message_id,
                content,
                message_timestamp
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

    def _run_with_retry(self, operation: Callable[[sqlite3.Connection], Result]) -> Result:
        for attempt in range(self.WRITE_RETRY_ATTEMPTS):
            try:
                with self._connect() as connection:
                    return operation(connection)
            except sqlite3.OperationalError as error:
                if not self._is_busy_error(error) or attempt + 1 >= self.WRITE_RETRY_ATTEMPTS:
                    raise
                time.sleep(self.WRITE_RETRY_DELAY_SECONDS * (2**attempt))

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
        """Create missing v2 tables and indexes without changing existing rows."""
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
        # Users are platform-level. Future group-specific identity data belongs
        # in a separate group_members table keyed by group_id and user_id.
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

    @classmethod
    def _validate_version_2_schema(cls, connection: sqlite3.Connection) -> None:
        required_columns = {
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
        }
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

        foreign_keys = {
            (row[3], row[2], row[4])
            for row in connection.execute('PRAGMA foreign_key_list("messages")')
        }
        required_foreign_keys = {
            ("group_id", "groups", "id"),
            ("user_id", "users", "id"),
        }
        if not required_foreign_keys <= foreign_keys:
            raise ValueError("Database messages table is missing required foreign keys.")

        if not cls._has_unique_index(
            connection,
            "groups",
            ("platform_id", "external_group_id"),
        ):
            raise ValueError("Database groups table is missing its unique identity key.")
        if not cls._has_unique_index(
            connection,
            "users",
            ("platform_id", "external_user_id"),
        ):
            raise ValueError("Database users table is missing its unique identity key.")

        cls._validate_messages_indexes(connection)

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
