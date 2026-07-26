"""Storage regression coverage for proactive-reply configuration scope."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from storage.database import GroupMemoryDatabase


class ActiveReplyStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.database = GroupMemoryDatabase(
            Path(self._temporary_directory.name) / "group_memory.db"
        )
        self.database.initialize()

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def _record(self, user_id: str, message_id: str) -> None:
        self.assertTrue(
            self.database.record_group_message(
                platform_id="qq",
                platform_name="QQ",
                external_group_id="group-1",
                group_name="Test group",
                external_user_id=user_id,
                user_nickname=user_id,
                platform_message_id=message_id,
                content="ordinary group message",
                message_timestamp=int(time.time()),
            )
        )

    def test_group_scoped_settings_and_canonical_member_id(self) -> None:
        self._record("source", "source-1")
        self._record("target", "target-1")
        self.database.set_config_value(
            "active_reply.v1:qq:group-1", '{"enabled":true}'
        )
        self.assertEqual(
            self.database.get_config_value("active_reply.v1:qq:group-1"),
            '{"enabled":true}',
        )

        self.database.merge_members(
            platform_id="qq",
            external_group_id="group-1",
            source_external_user_id="source",
            target_external_user_id="target",
            reason="test canonical member configuration",
        )
        source_id = self.database.get_member_id(
            platform_id="qq",
            external_group_id="group-1",
            external_user_id="source",
        )
        target_id = self.database.get_member_id(
            platform_id="qq",
            external_group_id="group-1",
            external_user_id="target",
        )
        self.assertEqual(source_id, target_id)


if __name__ == "__main__":
    unittest.main()
