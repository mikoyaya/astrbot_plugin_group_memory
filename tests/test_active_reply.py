"""Regression coverage for the dependency-free proactive reply v1 policy."""

from __future__ import annotations

import unittest

from active_reply import (
    GroupReplyActivity,
    decide_active_reply,
    normalize_active_reply_settings,
)


class ActiveReplyPolicyTests(unittest.TestCase):
    def _settings(self, **changes: object) -> dict[str, object]:
        value = {
            "enabled": True,
            "base_reply_rate": 0.5,
            "anti_spam_enabled": True,
            "consecutive_trigger_threshold": 3,
            "blacklist_member_ids": [],
            "priority_member_ids": [],
            "member_overrides": {},
            "bot_message_participation": False,
            "bot_message_weight": 0.15,
            "debug_log_enabled": True,
        }
        value.update(changes)
        return normalize_active_reply_settings(value)

    def _decide(
        self,
        *,
        settings: dict[str, object],
        activity: GroupReplyActivity | None = None,
        timestamp: int = 1_000,
        content: str = "hello",
        member_id: int | None = 1,
        is_bot_message: bool = False,
        is_direct_mention: bool = False,
        random_value: float = 0.0,
    ):
        return decide_active_reply(
            settings=settings,
            activity=activity or GroupReplyActivity(),
            sender_key="sender",
            member_id=member_id,
            content=content,
            timestamp=timestamp,
            is_bot_message=is_bot_message,
            is_direct_mention=is_direct_mention,
            is_command=False,
            random_value=lambda: random_value,
        )

    def test_blacklist_wins_and_priority_remains_rate_based(self) -> None:
        blocked = self._decide(
            settings=self._settings(blacklist_member_ids=[1], priority_member_ids=[1])
        )
        self.assertFalse(blocked.should_reply)
        self.assertEqual(blocked.reason, "命中黑名单")
        self.assertTrue(blocked.is_blacklisted)

        prioritized = self._decide(
            settings=self._settings(priority_member_ids=[1]), random_value=0.79
        )
        self.assertTrue(prioritized.should_reply)
        self.assertTrue(prioritized.is_prioritized)
        self.assertAlmostEqual(prioritized.effective_rate, 0.8)

    def test_repeated_burst_reduces_rate_without_fixed_human_cooldown(self) -> None:
        activity = GroupReplyActivity()
        settings = self._settings(base_reply_rate=0.5, consecutive_trigger_threshold=3)
        first = self._decide(settings=settings, activity=activity, timestamp=1_000)
        second = self._decide(settings=settings, activity=activity, timestamp=1_010)
        protected = self._decide(settings=settings, activity=activity, timestamp=1_020)
        self.assertTrue(first.should_reply)
        self.assertTrue(second.should_reply)
        self.assertLess(protected.effective_rate, 0.5)
        self.assertIn("短时连续发言", protected.protection_reasons)

        repeated = self._decide(
            settings=settings, activity=activity, timestamp=1_030, content="hello"
        )
        self.assertIn("重复内容", repeated.protection_reasons)

    def test_bot_messages_are_opt_in_and_loop_limited(self) -> None:
        excluded = self._decide(settings=self._settings(), is_bot_message=True)
        self.assertEqual(excluded.reason, "机器人消息默认不参与")

        activity = GroupReplyActivity(last_bot_reply_at=950)
        guarded = self._decide(
            settings=self._settings(bot_message_participation=True),
            activity=activity,
            timestamp=1_000,
            is_bot_message=True,
        )
        self.assertEqual(guarded.reason, "机器人互聊保护中")

    def test_normalization_bounds_member_overrides(self) -> None:
        settings = normalize_active_reply_settings({
            "enabled": "yes",
            "base_reply_rate": 9,
            "member_overrides": {
                "7": {"reply_rate_multiplier": 9, "anti_spam_sensitivity": 0},
                "bad": {"reply_rate_multiplier": 1},
            },
            "blacklist_member_ids": [1, "2", -1, "bad"],
        })
        self.assertFalse(settings["enabled"])
        self.assertEqual(settings["base_reply_rate"], 0.8)
        self.assertEqual(settings["blacklist_member_ids"], [1, 2])
        self.assertEqual(settings["member_overrides"], {
            "7": {"reply_rate_multiplier": 3.0, "anti_spam_sensitivity": 0.5}
        })


if __name__ == "__main__":
    unittest.main()
