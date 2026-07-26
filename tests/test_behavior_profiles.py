"""Standard-library regression tests for v7 internal behaviour profiles."""

from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from storage.database import GroupMemoryDatabase


class BehaviorProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self._temporary_directory.name) / "group_memory.db"
        self.database = GroupMemoryDatabase(self.database_path)
        self.database.initialize()
        self.now = int(time.time())

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def _record(
        self,
        *,
        user_id: str,
        message_id: str,
        content: str,
        day_offset: int,
    ) -> bool:
        return self.database.record_group_message(
            platform_id="qq",
            platform_name="QQ",
            external_group_id="group-1",
            group_name="Test group",
            external_user_id=user_id,
            user_nickname=f"member-{user_id}",
            platform_message_id=message_id,
            content=content,
            message_timestamp=self.now - day_offset * 24 * 60 * 60,
        )

    def _profile(self, user_id: str, *, internal: bool = True) -> dict[str, object]:
        profile = self.database.get_profile_overview(
            platform_id="qq",
            external_group_id="group-1",
            external_user_id=user_id,
            include_behavior_profile=internal,
        )
        self.assertIsNotNone(profile)
        return profile or {}

    def test_rules_manual_data_and_duplicate_messages(self) -> None:
        for index in range(12):
            self.assertTrue(
                self._record(
                    user_id="10001",
                    message_id=f"message-{index}",
                    content="请问怎么用？ [图片] [表情]",
                    day_offset=index % 3,
                )
            )

        profile = self._profile("10001")
        behavior = profile["behavior_profile"]
        self.assertEqual(behavior["state"], "ready")
        self.assertTrue(behavior["summary"])
        auto_tags = {tag["name"] for tag in behavior["auto_tags"]}
        self.assertTrue(
            {"持续互动", "爱提问", "常发图片", "常发表情包"} <= auto_tags
        )

        self.database.set_note(
            platform_id="qq",
            external_group_id="group-1",
            external_user_id="10001",
            content="人工备注",
        )
        self.database.add_tag(
            platform_id="qq",
            external_group_id="group-1",
            external_user_id="10001",
            tag_name="人工标签",
        )
        self.assertTrue(
            self._record(
                user_id="10001",
                message_id="dedupe-message",
                content="普通消息",
                day_offset=0,
            )
        )
        self.assertFalse(
            self._record(
                user_id="10001",
                message_id="dedupe-message",
                content="重复消息",
                day_offset=0,
            )
        )
        connection = sqlite3.connect(self.database_path)
        try:
            pending = connection.execute(
                "SELECT pending_message_count FROM member_behavior_profiles"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(int(pending[0]), 1)

        after = self._profile("10001")
        self.assertEqual(after["note"], "人工备注")
        self.assertIn("人工标签", after["tags"])
        public_profile = self._profile("10001", internal=False)
        self.assertNotIn("behavior_profile", public_profile)

    def test_merge_rebuilds_the_canonical_internal_profile(self) -> None:
        for index in range(6):
            self._record(
                user_id="source",
                message_id=f"source-{index}",
                content="普通群消息",
                day_offset=index % 3,
            )
            self._record(
                user_id="target",
                message_id=f"target-{index}",
                content="普通群消息",
                day_offset=index % 3,
            )

        self.database.merge_members(
            platform_id="qq",
            external_group_id="group-1",
            source_external_user_id="source",
            target_external_user_id="target",
            reason="regression test",
        )
        target = self._profile("target")
        behavior = target["behavior_profile"]
        self.assertEqual(behavior["state"], "ready")
        self.assertEqual(behavior["message_count"], 12)
        self.assertIn(
            "持续互动", {tag["name"] for tag in behavior["auto_tags"]}
        )

    def test_incremental_refresh_respects_cooldown_and_detects_high_frequency(self) -> None:
        for index in range(12):
            self._record(
                user_id="10003",
                message_id=f"initial-{index}",
                content="普通群消息",
                day_offset=index % 3,
            )
        initial = self._profile("10003")["behavior_profile"]
        initial_analyzed_at = initial["last_analyzed_at"]

        for index in range(6):
            self._record(
                user_id="10003",
                message_id=f"cooldown-{index}",
                content="普通群消息",
                day_offset=index % 7,
            )
        connection = sqlite3.connect(self.database_path)
        try:
            during_cooldown = connection.execute(
                "SELECT pending_message_count, last_analyzed_at "
                "FROM member_behavior_profiles"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(int(during_cooldown[0]), 6)
        self.assertEqual(int(during_cooldown[1]), initial_analyzed_at)

        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                "UPDATE member_behavior_profiles SET last_analyzed_at = ?",
                (self.now - GroupMemoryDatabase.BEHAVIOR_PROFILE_COOLDOWN_SECONDS - 1,),
            )
            connection.commit()
        finally:
            connection.close()
        for index in range(12):
            self._record(
                user_id="10003",
                message_id=f"high-frequency-{index}",
                content="普通群消息",
                day_offset=index % 7,
            )
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                "UPDATE member_behavior_profiles SET last_analyzed_at = ?",
                (self.now - GroupMemoryDatabase.BEHAVIOR_PROFILE_COOLDOWN_SECONDS - 1,),
            )
            connection.commit()
        finally:
            connection.close()
        self._record(
            user_id="10003",
            message_id="high-frequency-final",
            content="普通群消息",
            day_offset=0,
        )

        tags = {
            tag["name"]
            for tag in self._profile("10003")["behavior_profile"]["auto_tags"]
        }
        self.assertIn("高频互动", tags)

    def test_v6_database_upgrades_without_losing_manual_data(self) -> None:
        self._record(
            user_id="10002",
            message_id="legacy-message",
            content="旧消息",
            day_offset=0,
        )
        self.database.set_note(
            platform_id="qq",
            external_group_id="group-1",
            external_user_id="10002",
            content="保留的人工备注",
        )
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                "DROP INDEX IF EXISTS idx_member_behavior_profiles_last_analyzed"
            )
            connection.execute(
                "DROP INDEX IF EXISTS idx_member_behavior_profiles_member"
            )
            connection.execute("DROP TABLE member_behavior_profiles")
            connection.execute(
                "UPDATE plugin_metadata SET value = '6' WHERE key = 'schema_version'"
            )
            connection.commit()
        finally:
            connection.close()

        self.database.initialize()
        connection = sqlite3.connect(self.database_path)
        try:
            schema_version = connection.execute(
                "SELECT value FROM plugin_metadata WHERE key = 'schema_version'"
            ).fetchone()
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'member_behavior_profiles'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(schema_version[0], "7")
        self.assertIsNotNone(table)
        self.assertEqual(self._profile("10002")["note"], "保留的人工备注")


if __name__ == "__main__":
    unittest.main()
