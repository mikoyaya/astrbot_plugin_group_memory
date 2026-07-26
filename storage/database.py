"""SQLite storage and schema migrations for the QQ group profile plugin."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path
import re
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

    SCHEMA_VERSION = 6
    BUSY_TIMEOUT_MS = 1_000
    WRITE_RETRY_ATTEMPTS = 3
    WRITE_RETRY_DELAY_SECONDS = 0.05
    MILLISECONDS_TIMESTAMP_THRESHOLD = 100_000_000_000
    DEFAULT_WEBUI_MEMBER_LIMIT = 100
    MAX_WEBUI_MEMBER_LIMIT = 500
    MAX_RELATION_EVENT_LIMIT = 200
    DEFAULT_RELATION_AGGREGATE_LIMIT = 50
    MAX_RELATION_AGGREGATE_LIMIT = 200
    DEFAULT_NETWORK_NODE_LIMIT = 30
    MAX_NETWORK_NODE_LIMIT = 100
    DEFAULT_NETWORK_EDGE_LIMIT = 50
    MAX_NETWORK_EDGE_LIMIT = 200
    DEFAULT_RELATION_EVIDENCE_LIMIT = 50
    MAX_RELATION_EVIDENCE_LIMIT = 100
    ALIAS_TYPES = {"nickname", "group_note", "manual", "historical", "mention"}
    TAG_LAYERS = {"confirmed", "observed", "reported", "manual"}
    EVENT_TYPES = {
        "mention",
        "evaluation",
        "praise",
        "complaint",
        "reported",
        "confirmation",
    }
    EVENT_SOURCE_TYPES = {"manual", "observed", "reported"}
    NETWORK_SCOPES = {"one_hop", "two_hop", "group"}

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
        mention_targets: list[tuple[str, str]] | None = None,
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
        mention_targets = self._normalize_mention_targets(mention_targets)

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
                mention_targets=mention_targets,
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

    def remove_tag(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        tag_name: str,
    ) -> bool:
        """Detach one tag from a known group member.

        The reusable tag definition stays in ``tags`` so it remains available
        for other members and groups.
        """
        return self._run_with_retry(
            lambda connection: self._remove_tag_in_transaction(
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
        """Return recent group-member data for the plugin Page."""
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

    def list_member_aliases(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
    ) -> list[dict[str, object]]:
        """List aliases for a member's canonical identity in one group."""
        return self._run_with_retry(
            lambda connection: self._list_member_aliases_for_identity(
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

    def add_member_alias(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        alias: str,
        alias_type: str = "manual",
        confidence: float = 1.0,
    ) -> None:
        """Attach a manually verified alias to a group member identity."""
        self._run_with_retry(
            lambda connection: self._add_member_alias_in_transaction(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                external_user_id=self._require_identifier(
                    "external_user_id", external_user_id
                ),
                alias=self._require_identifier("alias", alias),
                alias_type=self._validate_choice(
                    "alias_type", alias_type, self.ALIAS_TYPES
                ),
                confidence=self._normalize_confidence(confidence),
            )
        )

    def remove_member_alias(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        alias_id: int,
    ) -> bool:
        """Remove one alias owned by the member's canonical identity."""
        return self._run_with_retry(
            lambda connection: self._remove_member_alias_in_transaction(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                external_user_id=self._require_identifier(
                    "external_user_id", external_user_id
                ),
                alias_id=self._require_positive_int("alias_id", alias_id),
            )
        )

    def resolve_member_reference(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        reference: str,
    ) -> dict[str, object]:
        """Resolve an ID, alias, or fuzzy name without guessing ambiguous matches.

        The return value always includes a confidence score and candidate list.
        ``member`` is only present when one canonical identity is unambiguous.
        """
        return self._run_with_retry(
            lambda connection: self._resolve_member_reference(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                reference=self._require_identifier("reference", reference),
            )
        )

    def merge_members(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        source_external_user_id: str,
        target_external_user_id: str,
        reason: str = "",
    ) -> None:
        """Redirect one group member identity to another, retaining all history."""
        self._run_with_retry(
            lambda connection: self._merge_members_in_transaction(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                source_external_user_id=self._require_identifier(
                    "source_external_user_id", source_external_user_id
                ),
                target_external_user_id=self._require_identifier(
                    "target_external_user_id", target_external_user_id
                ),
                reason=self._optional_text(reason) or "",
            )
        )

    def list_layered_tags(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
    ) -> list[dict[str, object]]:
        """List v4 layered tags plus legacy manual tags for one member."""
        return self._run_with_retry(
            lambda connection: self._list_layered_tags_for_identity(
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

    def add_layered_tag(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        tag_name: str,
        layer: str = "manual",
        confidence: float = 1.0,
        source_type: str = "manual",
    ) -> None:
        """Add or update a layered tag; this never promotes a fact implicitly."""
        self._run_with_retry(
            lambda connection: self._add_layered_tag_in_transaction(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                external_user_id=self._require_identifier(
                    "external_user_id", external_user_id
                ),
                tag_name=self._require_identifier("tag_name", tag_name),
                layer=self._validate_choice("layer", layer, self.TAG_LAYERS),
                confidence=self._normalize_confidence(confidence),
                source_type=self._validate_choice(
                    "source_type", source_type, self.EVENT_SOURCE_TYPES
                ),
            )
        )

    def remove_layered_tag(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        tag_id: int,
    ) -> bool:
        """Remove one v4 layered tag record by its stable record ID."""
        return self._run_with_retry(
            lambda connection: self._remove_layered_tag_in_transaction(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                external_user_id=self._require_identifier(
                    "external_user_id", external_user_id
                ),
                tag_id=self._require_positive_int("tag_id", tag_id),
            )
        )

    def list_relationship_events(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """List relation events for one group or a selected member identity."""
        return self._run_with_retry(
            lambda connection: self._list_relationship_events(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                external_user_id=self._optional_text(external_user_id),
                limit=self._normalize_limit(
                    limit, default=50, maximum=self.MAX_RELATION_EVENT_LIMIT
                ),
            )
        )

    def list_relationship_aggregates(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str | None = None,
        limit: int = DEFAULT_RELATION_AGGREGATE_LIMIT,
        event_types: list[str] | None = None,
        source_types: list[str] | None = None,
    ) -> list[dict[str, object]]:
        """Aggregate immutable relationship evidence for display only."""
        return self._run_with_retry(
            lambda connection: self._list_relationship_aggregates(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                external_user_id=self._optional_text(external_user_id),
                limit=self._normalize_limit(
                    limit,
                    default=self.DEFAULT_RELATION_AGGREGATE_LIMIT,
                    maximum=self.MAX_RELATION_AGGREGATE_LIMIT,
                ),
                event_types=self._normalize_choices(
                    event_types, self.EVENT_TYPES
                ),
                source_types=self._normalize_choices(
                    source_types, self.EVENT_SOURCE_TYPES
                ),
            )
        )

    def get_relationship_network(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        scope: str = "one_hop",
        node_limit: int = DEFAULT_NETWORK_NODE_LIMIT,
        edge_limit: int = DEFAULT_NETWORK_EDGE_LIMIT,
        event_types: list[str] | None = None,
        source_types: list[str] | None = None,
    ) -> dict[str, object]:
        """Return a bounded graph built from aggregated relationship evidence."""
        return self._run_with_retry(
            lambda connection: self._get_relationship_network(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                external_user_id=self._require_identifier(
                    "external_user_id", external_user_id
                ),
                scope=self._validate_choice("scope", scope, self.NETWORK_SCOPES),
                node_limit=self._normalize_limit(
                    node_limit,
                    default=self.DEFAULT_NETWORK_NODE_LIMIT,
                    maximum=self.MAX_NETWORK_NODE_LIMIT,
                ),
                edge_limit=self._normalize_limit(
                    edge_limit,
                    default=self.DEFAULT_NETWORK_EDGE_LIMIT,
                    maximum=self.MAX_NETWORK_EDGE_LIMIT,
                ),
                event_types=self._normalize_choices(
                    event_types, self.EVENT_TYPES
                ),
                source_types=self._normalize_choices(
                    source_types, self.EVENT_SOURCE_TYPES
                ),
            )
        )

    def list_relationship_aggregate_events(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        source_member_id: int,
        target_member_id: int | None,
        event_type: str,
        limit: int = DEFAULT_RELATION_EVIDENCE_LIMIT,
        before_timestamp: int | None = None,
        before_id: int | None = None,
    ) -> dict[str, object]:
        """Page raw evidence for one canonical aggregate without changing it."""
        return self._run_with_retry(
            lambda connection: self._list_relationship_aggregate_events(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                source_member_id=self._require_positive_int(
                    "source_member_id", source_member_id
                ),
                target_member_id=(
                    None
                    if target_member_id is None
                    else self._require_positive_int(
                        "target_member_id", target_member_id
                    )
                ),
                event_type=self._validate_choice(
                    "event_type", event_type, self.EVENT_TYPES
                ),
                limit=self._normalize_limit(
                    limit,
                    default=self.DEFAULT_RELATION_EVIDENCE_LIMIT,
                    maximum=self.MAX_RELATION_EVIDENCE_LIMIT,
                ),
                before_timestamp=(
                    None
                    if before_timestamp is None
                    else self._require_timestamp(before_timestamp)
                ),
                before_id=(
                    None
                    if before_id is None
                    else self._require_positive_int("before_id", before_id)
                ),
            )
        )

    def add_relationship_event(
        self,
        *,
        platform_id: str,
        external_group_id: str,
        source_external_user_id: str,
        target_external_user_id: str | None,
        event_type: str,
        content: str,
        confidence: float,
        source_type: str,
        event_timestamp: int | None = None,
    ) -> None:
        """Append an immutable relation event; it does not alter final relations."""
        self._run_with_retry(
            lambda connection: self._add_relationship_event_in_transaction(
                connection,
                platform_id=self._require_identifier("platform_id", platform_id),
                external_group_id=self._require_identifier(
                    "external_group_id", external_group_id
                ),
                source_external_user_id=self._require_identifier(
                    "source_external_user_id", source_external_user_id
                ),
                target_external_user_id=self._optional_text(target_external_user_id),
                event_type=self._validate_choice(
                    "event_type", event_type, self.EVENT_TYPES
                ),
                content=self._require_identifier("content", content),
                confidence=self._normalize_confidence(confidence),
                source_type=self._validate_choice(
                    "source_type", source_type, self.EVENT_SOURCE_TYPES
                ),
                event_timestamp=self._require_timestamp(
                    int(time.time()) if event_timestamp is None else event_timestamp
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

        member_status_missing = "member_status" not in {
            str(row[1])
            for row in connection.execute('PRAGMA table_info("members")')
        }

        # These operations are deliberately idempotent. They repair a database
        # labelled with a supported version when a table, column, or index was
        # removed outside the plugin.
        self._ensure_version_2_schema(connection)
        self._ensure_version_3_schema(connection)
        self._ensure_version_4_schema(connection)
        self._ensure_version_5_schema(connection)
        self._ensure_version_6_schema(connection)
        self._backfill_profiles(connection)
        self._backfill_members(connection)
        self._backfill_version_5_schema(
            connection,
            reconstruct_member_status=(
                schema_version < self.SCHEMA_VERSION or member_status_missing
            ),
        )
        self._validate_version_2_schema(connection)
        self._validate_version_3_schema(connection)
        self._validate_version_4_schema(connection)
        self._validate_version_5_schema(connection)
        self._validate_version_6_schema(connection)

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
        mention_targets: list[tuple[str, str]],
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
        member_id = self._ensure_member(
            connection,
            group_id=group_id,
            user_id=user_id,
            canonical_name=user_nickname,
            member_status="normal",
        )
        canonical_member_id = self._canonical_member_id(connection, member_id)
        if user_nickname:
            self._upsert_member_alias(
                connection,
                member_id=canonical_member_id,
                alias=user_nickname,
                alias_type="nickname",
                confidence=1.0,
                source_type="observed",
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
        if mention_targets:
            self._record_structured_mentions(
                connection,
                group_id=group_id,
                source_member_id=canonical_member_id,
                message_id=int(cursor.lastrowid),
                platform_message_id=platform_message_id,
                platform_id=platform_id,
                platform_name=platform_name,
                mention_targets=mention_targets,
                content=content,
                event_timestamp=message_timestamp,
            )
        else:
            self._record_observed_mentions(
                connection,
                group_id=group_id,
                source_member_id=canonical_member_id,
                message_id=int(cursor.lastrowid),
                platform_message_id=platform_message_id,
                content=content,
                event_timestamp=message_timestamp,
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

    def _remove_tag_in_transaction(
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
        cursor = connection.execute(
            """
            DELETE FROM "user_tags"
            WHERE group_id = ?
              AND user_id = ?
              AND tag_id = (
                  SELECT id FROM "tags" WHERE name = ? COLLATE NOCASE
              )
            """,
            (group_id, user_id, tag_name),
        )
        return cursor.rowcount == 1

    def _get_profile_overview(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
    ) -> dict[str, object] | None:
        try:
            group_id, _, member_id = self._member_context(
                connection,
                platform_id=platform_id,
                external_group_id=external_group_id,
                external_user_id=external_user_id,
            )
        except ValueError:
            return None
        canonical_identity = self._member_public_identity(connection, member_id)
        external_user_id = str(canonical_identity["user_id"])
        row = connection.execute(
            """
            SELECT
                g.platform_id,
                g.platform_name,
                g.external_group_id,
                g.group_name,
                u.external_user_id,
                u.nickname,
                p.summary,
                n.content AS note
            FROM "groups" AS g
            JOIN "users" AS u
              ON u.platform_id = g.platform_id
             AND u.external_user_id = ?
            LEFT JOIN "profiles" AS p ON p.user_id = u.id
            LEFT JOIN "notes" AS n ON n.group_id = g.id AND n.user_id = u.id
            WHERE g.platform_id = ?
              AND g.external_group_id = ?
            """,
            (external_user_id, platform_id, external_group_id),
        ).fetchone()
        if row is None:
            return None
        message_count, last_message_timestamp = self._member_message_stats(
            connection, group_id=group_id, canonical_member_id=member_id
        )
        return {
            "member_id": member_id,
            "platform_id": str(row[0]),
            "platform_name": row[1] or "",
            "group_id": str(row[2]),
            "external_group_id": str(row[2]),
            "group_name": row[3] or "",
            "user_id": str(row[4]),
            "external_user_id": str(row[4]),
            "nickname": row[5] or "",
            "member_status": str(canonical_identity["member_status"]),
            "summary": row[6] or "",
            "message_count": message_count,
            "last_message_timestamp": last_message_timestamp,
            "note": row[7] or "",
            "tags": self._list_tags(
                connection,
                platform_id=platform_id,
                external_group_id=external_group_id,
                external_user_id=external_user_id,
            ),
            "layered_tags": self._list_layered_tags_for_identity(
                connection,
                platform_id=platform_id,
                external_group_id=external_group_id,
                external_user_id=external_user_id,
            ),
            "aliases": self._list_member_aliases_for_identity(
                connection,
                platform_id=platform_id,
                external_group_id=external_group_id,
                external_user_id=external_user_id,
            ),
            "relationship_events": self._list_relationship_events(
                connection,
                platform_id=platform_id,
                external_group_id=external_group_id,
                external_user_id=external_user_id,
                limit=50,
            ),
            "relationship_aggregates": self._list_relationship_aggregates(
                connection,
                platform_id=platform_id,
                external_group_id=external_group_id,
                external_user_id=external_user_id,
                limit=self.DEFAULT_RELATION_AGGREGATE_LIMIT,
                event_types=[],
                source_types=[],
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

    def _list_member_overview(
        self, connection: sqlite3.Connection, *, limit: int
    ) -> list[dict[str, object]]:
        rows = connection.execute(
            """
            SELECT
                mem.id,
                g.platform_id,
                g.platform_name,
                g.external_group_id,
                g.group_name,
                u.external_user_id,
                u.nickname,
                n.content AS note
            FROM "members" AS mem
            JOIN "groups" AS g ON g.id = mem.group_id
            JOIN "users" AS u ON u.id = mem.user_id
            LEFT JOIN "messages" AS m ON m.group_id = g.id AND m.user_id = u.id
            LEFT JOIN "notes" AS n ON n.group_id = g.id AND n.user_id = u.id
            WHERE EXISTS (
                SELECT 1 FROM "messages" AS member_message
                WHERE member_message.group_id = g.id AND member_message.user_id = u.id
            ) OR EXISTS (
                SELECT 1 FROM "relationship_events" AS relation_event
                WHERE relation_event.group_id = g.id
                  AND (
                      relation_event.source_member_id = mem.id
                      OR relation_event.target_member_id = mem.id
                  )
            )
            GROUP BY mem.id
            """,
        ).fetchall()
        by_canonical_member: dict[int, dict[str, object]] = {}
        for row in rows:
            canonical_member_id = self._canonical_member_id(connection, int(row[0]))
            existing = by_canonical_member.get(canonical_member_id)
            if existing is None:
                canonical_identity = self._member_public_identity(
                    connection, canonical_member_id
                )
                group_id = self._member_group_id(connection, canonical_member_id)
                message_count, last_message_timestamp = self._member_message_stats(
                    connection,
                    group_id=group_id,
                    canonical_member_id=canonical_member_id,
                )
                tags = self._list_tags(
                    connection,
                    platform_id=str(row[1]),
                    external_group_id=str(row[3]),
                    external_user_id=str(canonical_identity["user_id"]),
                )
                by_canonical_member[canonical_member_id] = {
                    "member_id": canonical_member_id,
                    "platform_id": str(row[1]),
                    "platform_name": row[2] or "",
                    "group_id": str(row[3]),
                    "external_group_id": str(row[3]),
                    "group_name": row[4] or "",
                    "user_id": str(canonical_identity["user_id"]),
                    "external_user_id": str(canonical_identity["user_id"]),
                    "nickname": canonical_identity["nickname"] or row[6] or "",
                    "member_status": str(canonical_identity["member_status"]),
                    "aliases": [
                        str(alias["alias"])
                        for alias in self._list_member_aliases_for_identity(
                            connection,
                            platform_id=str(row[1]),
                            external_group_id=str(row[3]),
                            external_user_id=str(canonical_identity["user_id"]),
                        )
                    ],
                    "message_count": message_count,
                    "last_message_timestamp": last_message_timestamp,
                    "note": self._get_note(
                        connection,
                        platform_id=str(row[1]),
                        external_group_id=str(row[3]),
                        external_user_id=str(canonical_identity["user_id"]),
                    ) or "",
                    "tags": ", ".join(tags),
                }
        return sorted(
            by_canonical_member.values(),
            key=lambda member: (
                int(member["last_message_timestamp"] or 0),
                int(member["message_count"]),
            ),
            reverse=True,
        )[:limit]

    @staticmethod
    def _member_group_id(connection: sqlite3.Connection, member_id: int) -> int:
        row = connection.execute(
            'SELECT group_id FROM "members" WHERE id = ?', (member_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Member identity does not exist.")
        return int(row[0])

    @staticmethod
    def _member_message_stats(
        connection: sqlite3.Connection,
        *,
        group_id: int,
        canonical_member_id: int,
    ) -> tuple[int, int | None]:
        """Aggregate source identities after a merge without rewriting messages."""
        row = connection.execute(
            """
            WITH RECURSIVE descendants(member_id) AS (
                SELECT ?
                UNION ALL
                SELECT m.id
                FROM "members" AS m
                JOIN descendants AS d ON m.merged_into_member_id = d.member_id
            )
            SELECT COUNT(msg.id), MAX(msg.message_timestamp)
            FROM "messages" AS msg
            JOIN "members" AS m
              ON m.group_id = msg.group_id AND m.user_id = msg.user_id
            WHERE msg.group_id = ?
              AND m.id IN descendants
            """,
            (canonical_member_id, group_id),
        ).fetchone()
        return int(row[0] or 0), row[1]

    def _member_context(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        canonical: bool = True,
    ) -> tuple[int, int, int]:
        row = connection.execute(
            """
            SELECT g.id, u.id, m.id
            FROM "members" AS m
            JOIN "groups" AS g ON g.id = m.group_id
            JOIN "users" AS u ON u.id = m.user_id
            WHERE g.platform_id = ?
              AND g.external_group_id = ?
              AND u.external_user_id = ?
            """,
            (platform_id, external_group_id, external_user_id),
        ).fetchone()
        if row is None:
            raise ValueError("Target group member has not been recorded yet.")
        group_id, user_id, member_id = (int(row[0]), int(row[1]), int(row[2]))
        return group_id, user_id, self._canonical_member_id(connection, member_id) if canonical else member_id

    @staticmethod
    def _ensure_member(
        connection: sqlite3.Connection,
        *,
        group_id: int,
        user_id: int,
        canonical_name: str | None,
        member_status: str = "normal",
    ) -> int:
        if member_status not in {"normal", "mentioned_only"}:
            raise ValueError("member_status is invalid")
        connection.execute(
            """
            INSERT INTO "members" (
                group_id, user_id, canonical_name, member_status
            ) VALUES (?, ?, COALESCE(?, ''), ?)
            ON CONFLICT(group_id, user_id) DO UPDATE SET
                canonical_name = CASE
                    WHEN excluded.canonical_name <> '' THEN excluded.canonical_name
                    ELSE "members".canonical_name
                END,
                -- A sender has a real group message. That evidence is stronger
                -- than an observed @ mention and must never be downgraded.
                member_status = CASE
                    WHEN "members".member_status = 'normal'
                      OR excluded.member_status = 'normal' THEN 'normal'
                    ELSE 'mentioned_only'
                END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (group_id, user_id, canonical_name, member_status),
        )
        return int(
            connection.execute(
                'SELECT id FROM "members" WHERE group_id = ? AND user_id = ?',
                (group_id, user_id),
            ).fetchone()[0]
        )

    @staticmethod
    def _canonical_member_id(connection: sqlite3.Connection, member_id: int) -> int:
        """Follow merge redirects without changing old message or user records."""
        current = member_id
        seen: set[int] = set()
        while current not in seen:
            seen.add(current)
            row = connection.execute(
                'SELECT merged_into_member_id FROM "members" WHERE id = ?', (current,)
            ).fetchone()
            if row is None or row[0] is None:
                return current
            current = int(row[0])
        raise ValueError("Member merge history contains a cycle.")

    @staticmethod
    def _upsert_member_alias(
        connection: sqlite3.Connection,
        *,
        member_id: int,
        alias: str,
        alias_type: str,
        confidence: float,
        source_type: str,
    ) -> None:
        existing = connection.execute(
            """
            SELECT id FROM "member_aliases"
            WHERE member_id = ? AND alias = ? COLLATE NOCASE
            """,
            (member_id, alias),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO "member_aliases" (
                    member_id, alias, alias_type, confidence, source_type
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (member_id, alias, alias_type, confidence, source_type),
            )
            return
        connection.execute(
            """
            UPDATE "member_aliases"
            SET alias_type = ?, confidence = ?, source_type = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (alias_type, confidence, source_type, int(existing[0])),
        )

    def _list_member_aliases_for_identity(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
    ) -> list[dict[str, object]]:
        _, _, member_id = self._member_context(
            connection,
            platform_id=platform_id,
            external_group_id=external_group_id,
            external_user_id=external_user_id,
        )
        rows = connection.execute(
            """
            SELECT id, alias, alias_type, confidence, source_type, created_at, updated_at
            FROM "member_aliases"
            WHERE member_id = ?
            ORDER BY confidence DESC, alias COLLATE NOCASE
            """,
            (member_id,),
        ).fetchall()
        return [
            {
                "id": int(row[0]),
                "alias": str(row[1]),
                "alias_type": str(row[2]),
                "confidence": float(row[3]),
                "source_type": str(row[4]),
                "created_at": str(row[5]),
                "updated_at": str(row[6]),
            }
            for row in rows
        ]

    def _add_member_alias_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        alias: str,
        alias_type: str,
        confidence: float,
    ) -> None:
        connection.execute("BEGIN IMMEDIATE")
        _, _, member_id = self._member_context(
            connection,
            platform_id=platform_id,
            external_group_id=external_group_id,
            external_user_id=external_user_id,
        )
        self._upsert_member_alias(
            connection,
            member_id=member_id,
            alias=alias,
            alias_type=alias_type,
            confidence=confidence,
            source_type="manual",
        )

    def _remove_member_alias_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        alias_id: int,
    ) -> bool:
        connection.execute("BEGIN IMMEDIATE")
        _, _, member_id = self._member_context(
            connection,
            platform_id=platform_id,
            external_group_id=external_group_id,
            external_user_id=external_user_id,
        )
        cursor = connection.execute(
            'DELETE FROM "member_aliases" WHERE id = ? AND member_id = ?',
            (alias_id, member_id),
        )
        return cursor.rowcount == 1

    def _member_public_identity(
        self, connection: sqlite3.Connection, member_id: int
    ) -> dict[str, object]:
        row = connection.execute(
            """
            SELECT m.id, g.platform_id, g.external_group_id, u.external_user_id,
                   COALESCE(NULLIF(m.canonical_name, ''), u.nickname, '') AS nickname,
                   m.member_status
            FROM "members" AS m
            JOIN "groups" AS g ON g.id = m.group_id
            JOIN "users" AS u ON u.id = m.user_id
            WHERE m.id = ?
            """,
            (member_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Member identity does not exist.")
        return {
            "member_id": int(row[0]),
            "platform_id": str(row[1]),
            "group_id": str(row[2]),
            "user_id": str(row[3]),
            "nickname": row[4] or "",
            "member_status": str(row[5]),
        }

    def _resolve_member_reference(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        reference: str,
    ) -> dict[str, object]:
        group = connection.execute(
            'SELECT id FROM "groups" WHERE platform_id = ? AND external_group_id = ?',
            (platform_id, external_group_id),
        ).fetchone()
        if group is None:
            return {"member": None, "confidence": 0.0, "candidates": []}
        group_id = int(group[0])
        normalized = self._normalize_reference(reference)
        candidates: dict[int, tuple[float, str]] = {}
        direct_rows = connection.execute(
            """
            SELECT m.id FROM "members" AS m
            JOIN "users" AS u ON u.id = m.user_id
            WHERE m.group_id = ? AND u.external_user_id = ?
            """,
            (group_id, reference),
        ).fetchall()
        for row in direct_rows:
            candidates[self._canonical_member_id(connection, int(row[0]))] = (
                1.0,
                "external_user_id",
            )
        alias_rows = connection.execute(
            """
            SELECT m.id, a.alias
            FROM "member_aliases" AS a
            JOIN "members" AS m ON m.id = a.member_id
            WHERE m.group_id = ?
            """,
            (group_id,),
        ).fetchall()
        for row in alias_rows:
            alias_normalized = self._normalize_reference(row[1])
            if not alias_normalized:
                continue
            score = 1.0 if alias_normalized == normalized else SequenceMatcher(
                None, normalized, alias_normalized
            ).ratio()
            if score < 0.72:
                continue
            canonical_id = self._canonical_member_id(connection, int(row[0]))
            previous = candidates.get(canonical_id)
            if previous is None or score > previous[0]:
                candidates[canonical_id] = (score, "alias" if score == 1.0 else "fuzzy_alias")
        ordered = sorted(candidates.items(), key=lambda item: item[1][0], reverse=True)
        public_candidates = [
            {**self._member_public_identity(connection, member_id), "confidence": score, "match_type": match_type}
            for member_id, (score, match_type) in ordered[:10]
        ]
        if not ordered:
            return {"member": None, "confidence": 0.0, "candidates": []}
        winner_id, (winner_score, winner_type) = ordered[0]
        ambiguous = len(ordered) > 1 and winner_score - ordered[1][1][0] < 0.05
        return {
            "member": None if ambiguous else self._member_public_identity(connection, winner_id),
            "confidence": winner_score,
            "match_type": winner_type,
            "candidates": public_candidates,
        }

    def _merge_members_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        source_external_user_id: str,
        target_external_user_id: str,
        reason: str,
    ) -> None:
        connection.execute("BEGIN IMMEDIATE")
        _, _, source_member_id = self._member_context(
            connection,
            platform_id=platform_id,
            external_group_id=external_group_id,
            external_user_id=source_external_user_id,
            canonical=False,
        )
        _, _, target_member_id = self._member_context(
            connection,
            platform_id=platform_id,
            external_group_id=external_group_id,
            external_user_id=target_external_user_id,
        )
        if source_member_id == target_member_id:
            raise ValueError("Source and target already resolve to the same member.")
        if self._canonical_member_id(connection, source_member_id) != source_member_id:
            raise ValueError("Source member has already been merged.")
        aliases = connection.execute(
            """
            SELECT alias, alias_type, confidence, source_type
            FROM "member_aliases" WHERE member_id = ?
            """,
            (source_member_id,),
        ).fetchall()
        for alias in aliases:
            self._upsert_member_alias(
                connection,
                member_id=target_member_id,
                alias=str(alias[0]),
                alias_type="historical",
                confidence=float(alias[2]),
                source_type="manual",
            )
        source_identity = self._member_public_identity(connection, source_member_id)
        if source_identity["nickname"]:
            self._upsert_member_alias(
                connection,
                member_id=target_member_id,
                alias=str(source_identity["nickname"]),
                alias_type="historical",
                confidence=1.0,
                source_type="manual",
            )
        connection.execute(
            """
            UPDATE "members"
            SET member_status = 'normal', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (target_member_id,),
        )
        connection.execute(
            """
            UPDATE "members"
            SET merged_into_member_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (target_member_id, source_member_id),
        )
        connection.execute(
            """
            INSERT INTO "identity_merge_history" (
                source_member_id, target_member_id, reason, operator_type
            ) VALUES (?, ?, ?, 'manual')
            """,
            (source_member_id, target_member_id, reason),
        )

    def _list_layered_tags_for_identity(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
    ) -> list[dict[str, object]]:
        group_id, user_id, member_id = self._member_context(
            connection,
            platform_id=platform_id,
            external_group_id=external_group_id,
            external_user_id=external_user_id,
        )
        descendant_member_ids = self._member_descendant_ids(connection, member_id)
        placeholders = ", ".join("?" for _ in descendant_member_ids)
        rows = connection.execute(
            """
            SELECT mt.id, td.name, mt.layer, mt.confidence, mt.source_type,
                   mt.created_at, mt.updated_at
            FROM "member_tags" AS mt
            JOIN "tag_definitions" AS td ON td.id = mt.tag_definition_id
            WHERE mt.member_id IN (""" + placeholders + """)
            ORDER BY td.name COLLATE NOCASE, mt.layer, mt.source_type
            """,
            tuple(descendant_member_ids),
        ).fetchall()
        layered_tags = [
            {
                "id": int(row[0]),
                "name": str(row[1]),
                "layer": str(row[2]),
                "confidence": float(row[3]),
                "source_type": str(row[4]),
                "created_at": str(row[5]),
                "updated_at": str(row[6]),
            }
            for row in rows
        ]
        # v3 tags are human-entered assignments. Keep them visible as manual
        # facts without mutating the old tables or pretending they were inferred.
        legacy_rows = connection.execute(
            """
            SELECT t.name, ut.created_at
            FROM "user_tags" AS ut
            JOIN "tags" AS t ON t.id = ut.tag_id
            JOIN "members" AS mem
              ON mem.group_id = ut.group_id AND mem.user_id = ut.user_id
            WHERE ut.group_id = ?
              AND mem.id IN (""" + placeholders + """)
            ORDER BY t.name COLLATE NOCASE
            """,
            (group_id, *descendant_member_ids),
        ).fetchall()
        legacy_tags = [
            {
                "id": None,
                "name": str(row[0]),
                "layer": "manual",
                "confidence": 1.0,
                "source_type": "legacy_manual",
                "created_at": str(row[1]),
                "updated_at": str(row[1]),
                "legacy": True,
            }
            for row in legacy_rows
        ]
        return [*legacy_tags, *layered_tags]

    def _add_layered_tag_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        tag_name: str,
        layer: str,
        confidence: float,
        source_type: str,
    ) -> None:
        connection.execute("BEGIN IMMEDIATE")
        _, _, member_id = self._member_context(
            connection,
            platform_id=platform_id,
            external_group_id=external_group_id,
            external_user_id=external_user_id,
        )
        self._insert_or_update_layered_tag(
            connection,
            member_id=member_id,
            tag_name=tag_name,
            layer=layer,
            confidence=confidence,
            source_type=source_type,
        )

    @staticmethod
    def _insert_or_update_layered_tag(
        connection: sqlite3.Connection,
        *,
        member_id: int,
        tag_name: str,
        layer: str,
        confidence: float,
        source_type: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO "tag_definitions" (name) VALUES (?)
            ON CONFLICT(name) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
            """,
            (tag_name,),
        )
        tag_definition_id = int(
            connection.execute(
                'SELECT id FROM "tag_definitions" WHERE name = ? COLLATE NOCASE',
                (tag_name,),
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO "member_tags" (
                member_id, tag_definition_id, layer, confidence, source_type
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(member_id, tag_definition_id, layer, source_type) DO UPDATE SET
                confidence = excluded.confidence,
                updated_at = CURRENT_TIMESTAMP
            """,
            (member_id, tag_definition_id, layer, confidence, source_type),
        )

    def _remove_layered_tag_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        tag_id: int,
    ) -> bool:
        connection.execute("BEGIN IMMEDIATE")
        _, _, member_id = self._member_context(
            connection,
            platform_id=platform_id,
            external_group_id=external_group_id,
            external_user_id=external_user_id,
        )
        cursor = connection.execute(
            'DELETE FROM "member_tags" WHERE id = ? AND member_id = ?',
            (tag_id, member_id),
        )
        return cursor.rowcount == 1

    def _list_relationship_events(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        group = connection.execute(
            'SELECT id FROM "groups" WHERE platform_id = ? AND external_group_id = ?',
            (platform_id, external_group_id),
        ).fetchone()
        if group is None:
            return []
        group_id = int(group[0])
        member_id: int | None = None
        descendant_member_ids: list[int] = []
        if external_user_id:
            _, _, member_id = self._member_context(
                connection,
                platform_id=platform_id,
                external_group_id=external_group_id,
                external_user_id=external_user_id,
            )
            descendant_member_ids = self._member_descendant_ids(
                connection, member_id
            )
        params: list[object] = [group_id]
        member_filter = ""
        if member_id is not None:
            placeholders = ", ".join("?" for _ in descendant_member_ids)
            member_filter = (
                f" AND (re.source_member_id IN ({placeholders})"
                f" OR re.target_member_id IN ({placeholders}))"
            )
            params.extend(descendant_member_ids)
            params.extend(descendant_member_ids)
        params.append(limit)
        rows = connection.execute(
            f"""
            SELECT re.id, re.event_type, re.content, re.event_timestamp, re.confidence,
                   re.source_type, re.created_at,
                   su.external_user_id, COALESCE(NULLIF(sm.canonical_name, ''), su.nickname, ''),
                   tu.external_user_id, COALESCE(NULLIF(tm.canonical_name, ''), tu.nickname, '')
            FROM "relationship_events" AS re
            JOIN "members" AS sm ON sm.id = re.source_member_id
            JOIN "users" AS su ON su.id = sm.user_id
            LEFT JOIN "members" AS tm ON tm.id = re.target_member_id
            LEFT JOIN "users" AS tu ON tu.id = tm.user_id
            WHERE re.group_id = ? {member_filter}
            ORDER BY re.event_timestamp DESC, re.id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return [
            {
                "id": int(row[0]),
                "event_type": str(row[1]),
                "content": str(row[2]),
                "event_timestamp": int(row[3]),
                "confidence": float(row[4]),
                "source_type": str(row[5]),
                "created_at": str(row[6]),
                "source_user_id": str(row[7]),
                "source_nickname": row[8] or "",
                "target_user_id": row[9] or "",
                "target_nickname": row[10] or "",
            }
            for row in rows
        ]

    def _list_relationship_aggregates(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str | None,
        limit: int,
        event_types: list[str],
        source_types: list[str],
    ) -> list[dict[str, object]]:
        group_id = self._group_internal_id(
            connection, platform_id=platform_id, external_group_id=external_group_id
        )
        if group_id is None:
            return []
        member_id: int | None = None
        if external_user_id:
            _, _, member_id = self._member_context(
                connection,
                platform_id=platform_id,
                external_group_id=external_group_id,
                external_user_id=external_user_id,
            )
        aggregates = self._relationship_aggregates_for_group(
            connection,
            group_id=group_id,
            event_types=event_types,
            source_types=source_types,
        )
        if member_id is not None:
            aggregates = [
                aggregate
                for aggregate in aggregates
                if aggregate["source_member_id"] == member_id
                or aggregate["target_member_id"] == member_id
            ]
        return aggregates[:limit]

    def _get_relationship_network(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        external_user_id: str,
        scope: str,
        node_limit: int,
        edge_limit: int,
        event_types: list[str],
        source_types: list[str],
    ) -> dict[str, object]:
        group_id, _, center_member_id = self._member_context(
            connection,
            platform_id=platform_id,
            external_group_id=external_group_id,
            external_user_id=external_user_id,
        )
        aggregates = [
            aggregate
            for aggregate in self._relationship_aggregates_for_group(
                connection,
                group_id=group_id,
                event_types=event_types,
                source_types=source_types,
            )
            if aggregate["target_member_id"] is not None
        ]
        direct_member_ids: set[int] = set()
        for aggregate in aggregates:
            if aggregate["source_member_id"] == center_member_id:
                direct_member_ids.add(int(aggregate["target_member_id"]))
            elif aggregate["target_member_id"] == center_member_id:
                direct_member_ids.add(int(aggregate["source_member_id"]))

        selected_member_ids: set[int]
        if scope == "group":
            selected_member_ids = {
                int(aggregate["source_member_id"])
                for aggregate in aggregates
            } | {
                int(aggregate["target_member_id"])
                for aggregate in aggregates
                if aggregate["target_member_id"] is not None
            }
            selected_member_ids.add(center_member_id)
        else:
            one_hop = {center_member_id, *direct_member_ids}
            selected_member_ids = set(one_hop)
            if scope == "two_hop":
                for aggregate in aggregates:
                    if (
                        aggregate["source_member_id"] in one_hop
                        or aggregate["target_member_id"] in one_hop
                    ):
                        selected_member_ids.add(int(aggregate["source_member_id"]))
                        selected_member_ids.add(int(aggregate["target_member_id"]))

        ranked_direct_members = self._rank_direct_network_members(
            aggregates,
            center_member_id=center_member_id,
            member_ids=direct_member_ids,
        )
        ranked_outer_members = self._rank_network_members(
            aggregates,
            center_member_id=center_member_id,
            member_ids=selected_member_ids - direct_member_ids - {center_member_id},
        )
        ranked_members = ranked_direct_members + ranked_outer_members
        node_capacity = max(node_limit - 1, 0)
        direct_capacity = min(node_capacity, edge_limit)
        chosen_ranked_members = (
            ranked_direct_members[:direct_capacity]
            + ranked_outer_members[:max(node_capacity - len(ranked_direct_members), 0)]
        )
        chosen_member_ids = set(chosen_ranked_members)
        chosen_member_ids.add(center_member_id)
        visible_edges = self._rank_network_edges(
            aggregates, center_member_id=center_member_id, member_ids=chosen_member_ids
        )[:edge_limit]
        nodes = [
            self._network_member_node(connection, member_id)
            for member_id in sorted(chosen_member_ids)
        ]
        return {
            "center_member_id": center_member_id,
            "scope": scope,
            "nodes": nodes,
            "edges": visible_edges,
            "node_limit": node_limit,
            "edge_limit": edge_limit,
            "has_more_nodes": len(ranked_members) > len(chosen_ranked_members),
            "has_more_edges": len(
                [
                    aggregate
                    for aggregate in aggregates
                    if aggregate["source_member_id"] in chosen_member_ids
                    and aggregate["target_member_id"] in chosen_member_ids
                ]
            ) > edge_limit,
        }

    def _list_relationship_aggregate_events(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        source_member_id: int,
        target_member_id: int | None,
        event_type: str,
        limit: int,
        before_timestamp: int | None,
        before_id: int | None,
    ) -> dict[str, object]:
        group_id = self._group_internal_id(
            connection, platform_id=platform_id, external_group_id=external_group_id
        )
        if group_id is None:
            return {"events": [], "next_cursor": None}
        source_ids = self._member_descendant_ids(connection, source_member_id)
        source_placeholders = ", ".join("?" for _ in source_ids)
        target_filter = "re.target_member_id IS NULL"
        params: list[object] = [group_id, event_type, *source_ids]
        if target_member_id is not None:
            target_ids = self._member_descendant_ids(connection, target_member_id)
            target_placeholders = ", ".join("?" for _ in target_ids)
            target_filter = f"re.target_member_id IN ({target_placeholders})"
            params.extend(target_ids)
        cursor_filter = ""
        if before_timestamp is not None and before_id is not None:
            cursor_filter = (
                " AND (re.event_timestamp < ?"
                " OR (re.event_timestamp = ? AND re.id < ?))"
            )
            params.extend((before_timestamp, before_timestamp, before_id))
        params.append(limit + 1)
        rows = connection.execute(
            f"""
            SELECT re.id, re.source_member_id, re.target_member_id, re.event_type,
                   re.content, re.event_timestamp, re.confidence, re.source_type,
                   re.created_at,
                   su.external_user_id, COALESCE(NULLIF(sm.canonical_name, ''), su.nickname, ''),
                   tu.external_user_id, COALESCE(NULLIF(tm.canonical_name, ''), tu.nickname, '')
            FROM "relationship_events" AS re
            JOIN "members" AS sm ON sm.id = re.source_member_id
            JOIN "users" AS su ON su.id = sm.user_id
            LEFT JOIN "members" AS tm ON tm.id = re.target_member_id
            LEFT JOIN "users" AS tu ON tu.id = tm.user_id
            WHERE re.group_id = ?
              AND re.event_type = ?
              AND re.source_member_id IN ({source_placeholders})
              AND {target_filter}
              {cursor_filter}
            ORDER BY re.event_timestamp DESC, re.id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        events: list[dict[str, object]] = []
        for row in rows:
            timestamp = int(row[5])
            event_id = int(row[0])
            events.append({
                "id": event_id,
                "event_type": str(row[3]),
                "content": str(row[4]),
                "event_timestamp": timestamp,
                "confidence": float(row[6]),
                "source_type": str(row[7]),
                "created_at": str(row[8]),
                "source_user_id": str(row[9]),
                "source_nickname": row[10] or "",
                "target_user_id": row[11] or "",
                "target_nickname": row[12] or "",
            })
            if len(events) > limit:
                break
        has_more = len(events) > limit
        events = events[:limit]
        next_cursor = None
        if has_more and events:
            last = events[-1]
            next_cursor = {
                "before_timestamp": last["event_timestamp"],
                "before_id": last["id"],
            }
        return {"events": events, "next_cursor": next_cursor}

    def _relationship_aggregates_for_group(
        self,
        connection: sqlite3.Connection,
        *,
        group_id: int,
        event_types: list[str],
        source_types: list[str],
    ) -> list[dict[str, object]]:
        rows = connection.execute(
            """
            SELECT id, source_member_id, target_member_id, event_type, content,
                   event_timestamp, source_type
            FROM "relationship_events"
            WHERE group_id = ?
            ORDER BY event_timestamp DESC, id DESC
            """,
            (group_id,),
        ).fetchall()
        grouped: dict[tuple[int, int | None, str], dict[str, object]] = {}
        for row in rows:
            event_type = str(row[3])
            source_type = str(row[6])
            if event_types and event_type not in event_types:
                continue
            if source_types and source_type not in source_types:
                continue
            source_member_id = self._canonical_member_id(connection, int(row[1]))
            target_member_id = (
                None if row[2] is None
                else self._canonical_member_id(connection, int(row[2]))
            )
            key = (source_member_id, target_member_id, event_type)
            aggregate = grouped.get(key)
            if aggregate is None:
                source = self._network_member_node(connection, source_member_id)
                target = (
                    None if target_member_id is None
                    else self._network_member_node(connection, target_member_id)
                )
                aggregate = {
                    "source_member_id": source_member_id,
                    "target_member_id": target_member_id,
                    "event_type": event_type,
                    "count": 0,
                    "first_time": int(row[5]),
                    "last_time": int(row[5]),
                    "last_evidence": str(row[4]),
                    "source_counts": {},
                    "source": source,
                    "target": target,
                }
                grouped[key] = aggregate
            aggregate["count"] = int(aggregate["count"]) + 1
            aggregate["first_time"] = min(int(aggregate["first_time"]), int(row[5]))
            aggregate["last_time"] = max(int(aggregate["last_time"]), int(row[5]))
            source_counts = aggregate["source_counts"]
            source_counts[source_type] = int(source_counts.get(source_type, 0)) + 1
        return sorted(
            grouped.values(),
            key=lambda item: (int(item["count"]), int(item["last_time"])),
            reverse=True,
        )

    @staticmethod
    def _rank_network_members(
        aggregates: list[dict[str, object]],
        *,
        center_member_id: int,
        member_ids: set[int],
    ) -> list[int]:
        weights: dict[int, tuple[int, int]] = {
            member_id: (0, 0) for member_id in member_ids
        }
        for aggregate in aggregates:
            weight = int(aggregate["count"])
            last_time = int(aggregate["last_time"])
            for member_id in (
                aggregate["source_member_id"], aggregate["target_member_id"]
            ):
                if member_id in weights and member_id != center_member_id:
                    current_weight, current_last_time = weights[member_id]
                    weights[member_id] = (
                        current_weight + weight,
                        max(current_last_time, last_time),
                    )
        return [
            member_id
            for member_id, _ in sorted(
                weights.items(),
                key=lambda item: (-item[1][0], -item[1][1], item[0]),
            )
            if member_id != center_member_id
        ]

    @staticmethod
    def _rank_direct_network_members(
        aggregates: list[dict[str, object]],
        *,
        center_member_id: int,
        member_ids: set[int],
    ) -> list[int]:
        """Rank direct neighbors without allowing outer activity to displace them."""
        weights: dict[int, tuple[int, int]] = {
            member_id: (0, 0) for member_id in member_ids
        }
        for aggregate in aggregates:
            source_member_id = int(aggregate["source_member_id"])
            target_member_id = int(aggregate["target_member_id"])
            if source_member_id == center_member_id:
                other_member_id = target_member_id
            elif target_member_id == center_member_id:
                other_member_id = source_member_id
            else:
                continue
            if other_member_id not in weights:
                continue
            current_weight, current_last_time = weights[other_member_id]
            weights[other_member_id] = (
                current_weight + int(aggregate["count"]),
                max(current_last_time, int(aggregate["last_time"])),
            )
        return [
            member_id
            for member_id, _ in sorted(
                weights.items(),
                key=lambda item: (-item[1][0], -item[1][1], item[0]),
            )
        ]

    @staticmethod
    def _rank_network_edges(
        aggregates: list[dict[str, object]],
        *,
        center_member_id: int,
        member_ids: set[int],
    ) -> list[dict[str, object]]:
        """Place center edges first so selected direct members stay connected."""
        eligible = [
            aggregate
            for aggregate in aggregates
            if int(aggregate["source_member_id"]) in member_ids
            and int(aggregate["target_member_id"]) in member_ids
        ]

        def edge_key(aggregate: dict[str, object]) -> tuple[int, int, str, int, int]:
            return (
                -int(aggregate["count"]),
                -int(aggregate["last_time"]),
                str(aggregate["event_type"]),
                int(aggregate["source_member_id"]),
                int(aggregate["target_member_id"]),
            )

        direct_by_member: dict[int, list[dict[str, object]]] = {}
        outer_edges: list[dict[str, object]] = []
        for aggregate in eligible:
            source_member_id = int(aggregate["source_member_id"])
            target_member_id = int(aggregate["target_member_id"])
            if source_member_id == center_member_id:
                direct_by_member.setdefault(target_member_id, []).append(aggregate)
            elif target_member_id == center_member_id:
                direct_by_member.setdefault(source_member_id, []).append(aggregate)
            else:
                outer_edges.append(aggregate)

        direct_members = sorted(
            direct_by_member,
            key=lambda member_id: (
                -sum(int(item["count"]) for item in direct_by_member[member_id]),
                -max(int(item["last_time"]) for item in direct_by_member[member_id]),
                member_id,
            ),
        )
        required_edges = [
            sorted(direct_by_member[member_id], key=edge_key)[0]
            for member_id in direct_members
        ]
        required_keys = {
            (
                int(aggregate["source_member_id"]),
                int(aggregate["target_member_id"]),
                str(aggregate["event_type"]),
            )
            for aggregate in required_edges
        }
        remaining_direct_edges = [
            aggregate
            for aggregates_for_member in direct_by_member.values()
            for aggregate in aggregates_for_member
            if (
                int(aggregate["source_member_id"]),
                int(aggregate["target_member_id"]),
                str(aggregate["event_type"]),
            ) not in required_keys
        ]
        return (
            required_edges
            + sorted(remaining_direct_edges, key=edge_key)
            + sorted(outer_edges, key=edge_key)
        )

    def _network_member_node(
        self, connection: sqlite3.Connection, member_id: int
    ) -> dict[str, object]:
        identity = self._member_public_identity(connection, member_id)
        return {
            **identity,
            "label": identity["nickname"] or identity["user_id"],
        }

    @staticmethod
    def _group_internal_id(
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
    ) -> int | None:
        row = connection.execute(
            'SELECT id FROM "groups" WHERE platform_id = ? AND external_group_id = ?',
            (platform_id, external_group_id),
        ).fetchone()
        return None if row is None else int(row[0])

    @staticmethod
    def _member_descendant_ids(
        connection: sqlite3.Connection, canonical_member_id: int
    ) -> list[int]:
        rows = connection.execute(
            """
            WITH RECURSIVE descendants(member_id) AS (
                SELECT ?
                UNION ALL
                SELECT m.id
                FROM "members" AS m
                JOIN descendants AS d ON m.merged_into_member_id = d.member_id
            )
            SELECT member_id FROM descendants
            """,
            (canonical_member_id,),
        ).fetchall()
        return [int(row[0]) for row in rows]

    def _add_relationship_event_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        platform_id: str,
        external_group_id: str,
        source_external_user_id: str,
        target_external_user_id: str | None,
        event_type: str,
        content: str,
        confidence: float,
        source_type: str,
        event_timestamp: int,
    ) -> None:
        connection.execute("BEGIN IMMEDIATE")
        group_id, _, source_member_id = self._member_context(
            connection,
            platform_id=platform_id,
            external_group_id=external_group_id,
            external_user_id=source_external_user_id,
        )
        target_member_id: int | None = None
        if target_external_user_id:
            _, _, target_member_id = self._member_context(
                connection,
                platform_id=platform_id,
                external_group_id=external_group_id,
                external_user_id=target_external_user_id,
            )
        connection.execute(
            """
            INSERT INTO "relationship_events" (
                group_id, source_member_id, target_member_id, event_type, content,
                event_timestamp, confidence, source_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                group_id,
                source_member_id,
                target_member_id,
                event_type,
                content,
                event_timestamp,
                confidence,
                source_type,
            ),
        )

    def _record_observed_mentions(
        self,
        connection: sqlite3.Connection,
        *,
        group_id: int,
        source_member_id: int,
        message_id: int,
        platform_message_id: str,
        content: str,
        event_timestamp: int,
    ) -> None:
        """Store only unambiguous textual @ mentions as low-risk observations.

        This deliberately does not infer sentiment, rumours or facts. Native
        adapter mention components can be added later; the conservative text
        fallback avoids assigning an event when an alias maps to multiple people.
        """
        references = set(re.findall(r"@([^\s@,，。.!！?？:：]{1,64})", content))
        # Common QQ/OneBot textual representations of a native @ mention.
        references.update(re.findall(r"\[CQ:at,(?:qq|id)=([^,\]]+)", content))
        references.update(re.findall(r"<@(\d{1,32})>", content))
        for raw_reference in references:
            normalized = self._normalize_reference(raw_reference)
            if not normalized:
                continue
            rows = connection.execute(
                """
                SELECT m.id
                FROM "members" AS m
                JOIN "users" AS u ON u.id = m.user_id
                WHERE m.group_id = ? AND u.external_user_id = ?
                UNION
                SELECT m.id
                FROM "member_aliases" AS a
                JOIN "members" AS m ON m.id = a.member_id
                WHERE m.group_id = ? AND a.alias = ? COLLATE NOCASE
                """,
                (group_id, raw_reference.strip(), group_id, raw_reference.strip()),
            ).fetchall()
            target_ids = {
                self._canonical_member_id(connection, int(row[0])) for row in rows
            }
            if len(target_ids) != 1:
                continue
            target_member_id = target_ids.pop()
            target_identity = self._member_public_identity(
                connection, target_member_id
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO "relationship_events" (
                    group_id, source_member_id, target_member_id, event_type,
                    content, message_id, platform_message_id,
                    mention_target_user_id, event_timestamp, confidence, source_type
                ) VALUES (?, ?, ?, 'mention', ?, ?, ?, ?, ?, 1.0, 'observed')
                """,
                (
                    group_id,
                    source_member_id,
                    target_member_id,
                    content,
                    message_id,
                    platform_message_id,
                    target_identity["user_id"],
                    event_timestamp,
                ),
            )

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
            FROM "members" AS member
            JOIN "groups" AS g ON g.id = member.group_id
            JOIN "users" AS u ON u.id = member.user_id
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

    def _record_structured_mentions(
        self,
        connection: sqlite3.Connection,
        *,
        group_id: int,
        source_member_id: int,
        message_id: int,
        platform_message_id: str,
        platform_id: str,
        platform_name: str,
        mention_targets: list[tuple[str, str]],
        content: str,
        event_timestamp: int,
    ) -> None:
        """Persist QQ At components using their stable target user ID.

        A target may never have sent a message. We still create its platform
        user and group member identity here, so the observed event is not
        silently lost merely because the target has no existing profile.
        """
        for target_external_user_id, target_name in mention_targets:
            target_user_id = self._upsert_user(
                connection,
                platform_id=platform_id,
                platform_name=platform_name,
                external_user_id=target_external_user_id,
                nickname=target_name or None,
            )
            connection.execute(
                'INSERT OR IGNORE INTO "profiles" (user_id) VALUES (?)',
                (target_user_id,),
            )
            target_member_id = self._ensure_member(
                connection,
                group_id=group_id,
                user_id=target_user_id,
                canonical_name=target_name or None,
                member_status="mentioned_only",
            )
            target_member_id = self._canonical_member_id(
                connection, target_member_id
            )
            if target_name:
                self._upsert_member_alias(
                    connection,
                    member_id=target_member_id,
                    alias=target_name,
                    alias_type="mention",
                    confidence=1.0,
                    source_type="observed",
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO "relationship_events" (
                    group_id, source_member_id, target_member_id, event_type,
                    content, message_id, platform_message_id,
                    mention_target_user_id, event_timestamp, confidence, source_type
                ) VALUES (?, ?, ?, 'mention', ?, ?, ?, ?, ?, 1.0, 'observed')
                """,
                (
                    group_id,
                    source_member_id,
                    target_member_id,
                    content,
                    message_id,
                    platform_message_id,
                    target_external_user_id,
                    event_timestamp,
                ),
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
    def _ensure_version_4_schema(connection: sqlite3.Connection) -> None:
        """Create v4 identity, evidence and layered-tag tables idempotently."""
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "members" (
                id INTEGER PRIMARY KEY,
                group_id INTEGER NOT NULL REFERENCES "groups"(id),
                user_id INTEGER NOT NULL REFERENCES "users"(id),
                canonical_name TEXT NOT NULL DEFAULT '',
                merged_into_member_id INTEGER REFERENCES "members"(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_members_group_user
            ON "members" (group_id, user_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_members_merged_into
            ON "members" (merged_into_member_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "member_aliases" (
                id INTEGER PRIMARY KEY,
                member_id INTEGER NOT NULL REFERENCES "members"(id),
                alias TEXT NOT NULL,
                alias_type TEXT NOT NULL,
                confidence REAL NOT NULL,
                source_type TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK(confidence >= 0.0 AND confidence <= 1.0)
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_member_aliases_member_alias
            ON "member_aliases" (member_id, alias COLLATE NOCASE)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_member_aliases_alias
            ON "member_aliases" (alias COLLATE NOCASE)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "identity_merge_history" (
                id INTEGER PRIMARY KEY,
                source_member_id INTEGER NOT NULL REFERENCES "members"(id),
                target_member_id INTEGER NOT NULL REFERENCES "members"(id),
                reason TEXT NOT NULL DEFAULT '',
                operator_type TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_identity_merge_history_source
            ON "identity_merge_history" (source_member_id, id DESC)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "tag_definitions" (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tag_definitions_name
            ON "tag_definitions" (name COLLATE NOCASE)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "member_tags" (
                id INTEGER PRIMARY KEY,
                member_id INTEGER NOT NULL REFERENCES "members"(id),
                tag_definition_id INTEGER NOT NULL REFERENCES "tag_definitions"(id),
                layer TEXT NOT NULL,
                confidence REAL NOT NULL,
                source_type TEXT NOT NULL,
                evidence_event_id INTEGER REFERENCES "relationship_events"(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK(confidence >= 0.0 AND confidence <= 1.0),
                UNIQUE(member_id, tag_definition_id, layer, source_type)
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_member_tags_identity
            ON "member_tags" (member_id, tag_definition_id, layer, source_type)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_member_tags_member
            ON "member_tags" (member_id, layer)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS "relationship_events" (
                id INTEGER PRIMARY KEY,
                group_id INTEGER NOT NULL REFERENCES "groups"(id),
                source_member_id INTEGER NOT NULL REFERENCES "members"(id),
                target_member_id INTEGER REFERENCES "members"(id),
                event_type TEXT NOT NULL,
                content TEXT NOT NULL,
                message_id INTEGER REFERENCES "messages"(id),
                event_timestamp INTEGER NOT NULL,
                confidence REAL NOT NULL,
                source_type TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK(confidence >= 0.0 AND confidence <= 1.0)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_relationship_events_group_time
            ON "relationship_events" (group_id, event_timestamp DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_relationship_events_source_time
            ON "relationship_events" (source_member_id, event_timestamp DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_relationship_events_target_time
            ON "relationship_events" (target_member_id, event_timestamp DESC)
            """
        )

    @staticmethod
    def _ensure_version_5_schema(connection: sqlite3.Connection) -> None:
        """Add v5 member state and automatic-mention idempotency fields."""
        member_columns = {
            str(row[1])
            for row in connection.execute('PRAGMA table_info("members")')
        }
        if "member_status" not in member_columns:
            connection.execute(
                """
                ALTER TABLE "members"
                ADD COLUMN member_status TEXT NOT NULL DEFAULT 'normal'
                """
            )

        event_columns = {
            str(row[1])
            for row in connection.execute('PRAGMA table_info("relationship_events")')
        }
        if "platform_message_id" not in event_columns:
            connection.execute(
                """
                ALTER TABLE "relationship_events"
                ADD COLUMN platform_message_id TEXT NOT NULL DEFAULT ''
                """
            )
        if "mention_target_user_id" not in event_columns:
            connection.execute(
                """
                ALTER TABLE "relationship_events"
                ADD COLUMN mention_target_user_id TEXT NOT NULL DEFAULT ''
                """
            )

    @staticmethod
    def _ensure_version_6_schema(connection: sqlite3.Connection) -> None:
        """Create read-optimised indexes for live relationship aggregation."""
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_relationship_events_group_type_source_time
            ON "relationship_events" (
                group_id, event_type, source_type, event_timestamp DESC, id DESC
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_relationship_events_group_source_target_type_time
            ON "relationship_events" (
                group_id, source_member_id, target_member_id, event_type,
                event_timestamp DESC, id DESC
            )
            """
        )

    @classmethod
    def _backfill_version_5_schema(
        cls,
        connection: sqlite3.Connection,
        *,
        reconstruct_member_status: bool,
    ) -> None:
        """Repair v5 data derived from prior message and mention evidence."""
        connection.execute(
            """
            UPDATE "relationship_events"
            SET platform_message_id = COALESCE((
                SELECT msg.platform_message_id
                FROM "messages" AS msg
                WHERE msg.id = "relationship_events".message_id
            ), '')
            WHERE platform_message_id = ''
            """
        )
        connection.execute(
            """
            UPDATE "relationship_events"
            SET mention_target_user_id = COALESCE((
                SELECT user.external_user_id
                FROM "members" AS member
                JOIN "users" AS user ON user.id = member.user_id
                WHERE member.id = "relationship_events".target_member_id
            ), '')
            WHERE mention_target_user_id = ''
              AND event_type = 'mention'
              AND source_type = 'observed'
            """
        )

        if reconstruct_member_status:
            # v4 had no explicit member state. Start with pure observed mention
            # targets, then promote known senders and manual merge targets.
            connection.execute(
                """
                UPDATE "members" AS member
                SET member_status = 'mentioned_only', updated_at = CURRENT_TIMESTAMP
                WHERE NOT EXISTS (
                    SELECT 1 FROM "messages" AS msg
                    WHERE msg.group_id = member.group_id AND msg.user_id = member.user_id
                )
                  AND EXISTS (
                    SELECT 1 FROM "relationship_events" AS event
                    WHERE event.target_member_id = member.id
                      AND event.event_type = 'mention'
                      AND event.source_type = 'observed'
                )
                """
            )
            connection.execute(
                """
                UPDATE "members" AS member
                SET member_status = 'normal', updated_at = CURRENT_TIMESTAMP
                WHERE EXISTS (
                    SELECT 1 FROM "messages" AS msg
                    WHERE msg.group_id = member.group_id AND msg.user_id = member.user_id
                )
                """
            )
            connection.execute(
                """
                UPDATE "members"
                SET member_status = 'normal', updated_at = CURRENT_TIMESTAMP
                WHERE id IN (
                    SELECT target_member_id FROM "identity_merge_history"
                )
                """
            )

        # Existing v4 rows can contain repeated observations. Keep the oldest
        # evidence before creating the partial uniqueness constraint.
        connection.execute(
            """
            DELETE FROM "relationship_events"
            WHERE id IN (
                SELECT duplicate.id
                FROM "relationship_events" AS duplicate
                JOIN "relationship_events" AS original
                  ON original.group_id = duplicate.group_id
                 AND original.platform_message_id = duplicate.platform_message_id
                 AND original.mention_target_user_id = duplicate.mention_target_user_id
                 AND original.event_type = 'mention'
                 AND original.source_type = 'observed'
                 AND original.id < duplicate.id
                WHERE duplicate.event_type = 'mention'
                  AND duplicate.source_type = 'observed'
                  AND duplicate.platform_message_id <> ''
                  AND duplicate.mention_target_user_id <> ''
            )
            """
        )
        connection.execute(
            'DROP INDEX IF EXISTS idx_relationship_events_observed_mention_dedupe'
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX idx_relationship_events_observed_mention_dedupe
            ON "relationship_events" (
                group_id, platform_message_id, mention_target_user_id
            )
            WHERE event_type = 'mention'
              AND source_type = 'observed'
              AND platform_message_id <> ''
              AND mention_target_user_id <> ''
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

    @staticmethod
    def _backfill_members(connection: sqlite3.Connection) -> None:
        """Create a group-scoped identity for every previously recorded sender."""
        connection.execute(
            """
            INSERT OR IGNORE INTO "members" (group_id, user_id, canonical_name)
            SELECT DISTINCT m.group_id, m.user_id, COALESCE(u.nickname, '')
            FROM "messages" AS m
            JOIN "users" AS u ON u.id = m.user_id
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO "member_aliases" (
                member_id, alias, alias_type, confidence, source_type
            )
            SELECT mem.id, u.nickname, 'nickname', 1.0, 'observed'
            FROM "members" AS mem
            JOIN "users" AS u ON u.id = mem.user_id
            WHERE TRIM(COALESCE(u.nickname, '')) <> ''
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

    @classmethod
    def _validate_version_4_schema(cls, connection: sqlite3.Connection) -> None:
        cls._validate_required_columns(
            connection,
            {
                "members": {
                    "id", "group_id", "user_id", "canonical_name",
                    "merged_into_member_id", "created_at", "updated_at",
                },
                "member_aliases": {
                    "id", "member_id", "alias", "alias_type", "confidence",
                    "source_type", "created_at", "updated_at",
                },
                "identity_merge_history": {
                    "id", "source_member_id", "target_member_id", "reason",
                    "operator_type", "created_at",
                },
                "tag_definitions": {"id", "name", "created_at", "updated_at"},
                "member_tags": {
                    "id", "member_id", "tag_definition_id", "layer", "confidence",
                    "source_type", "evidence_event_id", "created_at", "updated_at",
                },
                "relationship_events": {
                    "id", "group_id", "source_member_id", "target_member_id",
                    "event_type", "content", "message_id", "event_timestamp",
                    "confidence", "source_type", "created_at",
                },
            },
        )
        cls._validate_foreign_keys(
            connection,
            "members",
            {
                ("group_id", "groups", "id"),
                ("user_id", "users", "id"),
                ("merged_into_member_id", "members", "id"),
            },
        )
        cls._validate_foreign_keys(
            connection, "member_aliases", {("member_id", "members", "id")}
        )
        cls._validate_foreign_keys(
            connection,
            "identity_merge_history",
            {
                ("source_member_id", "members", "id"),
                ("target_member_id", "members", "id"),
            },
        )
        cls._validate_foreign_keys(
            connection,
            "member_tags",
            {
                ("member_id", "members", "id"),
                ("tag_definition_id", "tag_definitions", "id"),
                ("evidence_event_id", "relationship_events", "id"),
            },
        )
        cls._validate_foreign_keys(
            connection,
            "relationship_events",
            {
                ("group_id", "groups", "id"),
                ("source_member_id", "members", "id"),
                ("target_member_id", "members", "id"),
                ("message_id", "messages", "id"),
            },
        )
        for table_name, columns in {
            "members": ("group_id", "user_id"),
            "member_aliases": ("member_id", "alias"),
            "tag_definitions": ("name",),
            "member_tags": ("member_id", "tag_definition_id", "layer", "source_type"),
        }.items():
            if not cls._has_unique_index(connection, table_name, columns):
                raise ValueError(
                    f"Database {table_name} table is missing its unique identity key."
                )
        cls._validate_named_indexes(
            connection,
            {
                "idx_members_merged_into": ("members", ("merged_into_member_id",)),
                "idx_member_aliases_alias": ("member_aliases", ("alias",)),
                "idx_member_tags_member": ("member_tags", ("member_id", "layer")),
                "idx_relationship_events_group_time": (
                    "relationship_events", ("group_id", "event_timestamp")
                ),
                "idx_relationship_events_source_time": (
                    "relationship_events", ("source_member_id", "event_timestamp")
                ),
                "idx_relationship_events_target_time": (
                    "relationship_events", ("target_member_id", "event_timestamp")
                ),
            },
        )

    @classmethod
    def _validate_version_5_schema(cls, connection: sqlite3.Connection) -> None:
        cls._validate_required_columns(
            connection,
            {
                "members": {"member_status"},
                "relationship_events": {
                    "platform_message_id", "mention_target_user_id",
                },
            },
        )
        invalid_status = connection.execute(
            """
            SELECT 1 FROM "members"
            WHERE member_status NOT IN ('normal', 'mentioned_only')
            LIMIT 1
            """
        ).fetchone()
        if invalid_status is not None:
            raise ValueError("Database members table has an invalid member status.")
        cls._validate_observed_mention_dedupe_index(connection)

    @classmethod
    def _validate_version_6_schema(cls, connection: sqlite3.Connection) -> None:
        cls._validate_named_indexes(
            connection,
            {
                "idx_relationship_events_group_type_source_time": (
                    "relationship_events",
                    ("group_id", "event_type", "source_type", "event_timestamp", "id"),
                ),
                "idx_relationship_events_group_source_target_type_time": (
                    "relationship_events",
                    (
                        "group_id", "source_member_id", "target_member_id",
                        "event_type", "event_timestamp", "id",
                    ),
                ),
            },
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
    def _validate_observed_mention_dedupe_index(
        connection: sqlite3.Connection,
    ) -> None:
        index_name = "idx_relationship_events_observed_mention_dedupe"
        index_row = next(
            (
                row
                for row in connection.execute(
                    'PRAGMA index_list("relationship_events")'
                )
                if row[1] == index_name
            ),
            None,
        )
        index_columns = (
            tuple(
                row[2]
                for row in connection.execute(f'PRAGMA index_info("{index_name}")')
            )
            if index_row is not None
            else ()
        )
        sql_row = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'index' AND name = ?
            """,
            (index_name,),
        ).fetchone()
        sql = "" if sql_row is None or sql_row[0] is None else str(sql_row[0]).lower()
        required_terms = (
            "where", "event_type = 'mention'", "source_type = 'observed'",
            "platform_message_id <> ''", "mention_target_user_id <> ''",
        )
        if (
            index_row is None
            or not bool(index_row[2])
            or not bool(index_row[4])
            or index_columns != (
                "group_id", "platform_message_id", "mention_target_user_id"
            )
            or not all(term in sql for term in required_terms)
        ):
            raise ValueError(
                "Database observed mention deduplication index is missing or incompatible."
            )

    @staticmethod
    def _validate_named_indexes(
        connection: sqlite3.Connection,
        expected_indexes: dict[str, tuple[str, tuple[str, ...]]],
    ) -> None:
        for index_name, (table_name, expected_columns) in expected_indexes.items():
            indexes = {
                row[1] for row in connection.execute(f'PRAGMA index_list("{table_name}")')
            }
            actual_columns = (
                tuple(
                    row[2]
                    for row in connection.execute(f'PRAGMA index_info("{index_name}")')
                )
                if index_name in indexes
                else ()
            )
            if actual_columns != expected_columns:
                raise ValueError(
                    f"Database index {index_name} is missing or incompatible."
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

    @staticmethod
    def _normalize_reference(value: object) -> str:
        return "".join(str(value).strip().casefold().split())

    @classmethod
    def _normalize_mention_targets(
        cls, value: object
    ) -> list[tuple[str, str]]:
        """Accept only stable, de-duplicated target IDs from the event layer."""
        if not isinstance(value, (list, tuple)):
            return []
        normalized_targets: list[tuple[str, str]] = []
        known_ids: set[str] = set()
        for item in value:
            if not isinstance(item, (list, tuple)) or not item:
                continue
            target_id = cls._optional_text(item[0])
            target_name = cls._optional_text(item[1]) if len(item) > 1 else None
            if target_id is None or target_id.lower() == "all" or target_id in known_ids:
                continue
            known_ids.add(target_id)
            normalized_targets.append((target_id, target_name or ""))
        return normalized_targets

    @staticmethod
    def _normalize_choices(value: object, allowed: set[str]) -> list[str]:
        if not isinstance(value, (list, tuple, set)):
            return []
        return sorted(
            {
                normalized
                for item in value
                if (normalized := str(item).strip().lower()) in allowed
            }
        )

    @staticmethod
    def _normalize_confidence(value: object) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError("confidence must be a number between 0 and 1") from error
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return confidence

    @staticmethod
    def _require_positive_int(field_name: str, value: object) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{field_name} must be a positive integer") from error
        if result <= 0:
            raise ValueError(f"{field_name} must be a positive integer")
        return result

    @staticmethod
    def _validate_choice(field_name: str, value: object, allowed: set[str]) -> str:
        normalized = str(value).strip().lower()
        if normalized not in allowed:
            raise ValueError(f"{field_name} is invalid")
        return normalized
