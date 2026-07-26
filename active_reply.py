"""Small, dependency-free policy helpers for optional proactive replies.

This module intentionally contains no AstrBot objects or database connections so
the eligibility rules can be exercised independently from the plugin runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
import re
from typing import Any, Callable


DEFAULT_ACTIVE_REPLY_SETTINGS: dict[str, object] = {
    "enabled": False,
    "base_reply_rate": 0.12,
    "anti_spam_enabled": True,
    "consecutive_trigger_threshold": 3,
    "blacklist_member_ids": [],
    "priority_member_ids": [],
    "member_overrides": {},
    "bot_message_participation": False,
    "bot_message_weight": 0.15,
    "debug_log_enabled": True,
}

MAX_MEMBER_RULES = 100
MAX_LIST_MEMBERS = 500
_PUNCTUATION_PATTERN = re.compile(r"[\s\W_]+", re.UNICODE)


def _as_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _bounded_float(value: object, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, minimum), maximum)


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, minimum), maximum)


def _member_id_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    member_ids: set[int] = set()
    for raw_value in value:
        try:
            member_id = int(raw_value)
        except (TypeError, ValueError):
            continue
        if member_id > 0:
            member_ids.add(member_id)
        if len(member_ids) >= MAX_LIST_MEMBERS:
            break
    return sorted(member_ids)


def normalize_active_reply_settings(value: object) -> dict[str, object]:
    """Validate the compact, group-scoped settings object before use or save."""
    source = value if isinstance(value, dict) else {}
    defaults = DEFAULT_ACTIVE_REPLY_SETTINGS
    overrides: dict[str, dict[str, float]] = {}
    raw_overrides = source.get("member_overrides")
    if isinstance(raw_overrides, dict):
        for raw_member_id, raw_override in raw_overrides.items():
            if len(overrides) >= MAX_MEMBER_RULES:
                break
            try:
                member_id = int(raw_member_id)
            except (TypeError, ValueError):
                continue
            if member_id <= 0 or not isinstance(raw_override, dict):
                continue
            overrides[str(member_id)] = {
                "reply_rate_multiplier": _bounded_float(
                    raw_override.get("reply_rate_multiplier"), 1.0, 0.0, 3.0
                ),
                "anti_spam_sensitivity": _bounded_float(
                    raw_override.get("anti_spam_sensitivity"), 1.0, 0.5, 2.0
                ),
            }

    return {
        "enabled": _as_bool(source.get("enabled"), bool(defaults["enabled"])),
        "base_reply_rate": _bounded_float(
            source.get("base_reply_rate"), float(defaults["base_reply_rate"]), 0.0, 0.8
        ),
        "anti_spam_enabled": _as_bool(
            source.get("anti_spam_enabled"), bool(defaults["anti_spam_enabled"])
        ),
        "consecutive_trigger_threshold": _bounded_int(
            source.get("consecutive_trigger_threshold"),
            int(defaults["consecutive_trigger_threshold"]),
            2,
            12,
        ),
        "blacklist_member_ids": _member_id_list(source.get("blacklist_member_ids")),
        "priority_member_ids": _member_id_list(source.get("priority_member_ids")),
        "member_overrides": overrides,
        "bot_message_participation": _as_bool(
            source.get("bot_message_participation"),
            bool(defaults["bot_message_participation"]),
        ),
        "bot_message_weight": _bounded_float(
            source.get("bot_message_weight"),
            float(defaults["bot_message_weight"]),
            0.0,
            0.5,
        ),
        "debug_log_enabled": _as_bool(
            source.get("debug_log_enabled"), bool(defaults["debug_log_enabled"])
        ),
    }


@dataclass
class SenderActivity:
    last_timestamp: int = 0
    last_fingerprint: str = ""
    consecutive_count: int = 0
    question_streak: int = 0
    mention_streak: int = 0


@dataclass
class GroupReplyActivity:
    senders: dict[str, SenderActivity] = field(default_factory=dict)
    last_bot_reply_at: int = 0


@dataclass(frozen=True)
class ActiveReplyDecision:
    should_reply: bool
    reason: str
    effective_rate: float
    protection_reasons: tuple[str, ...]
    is_blacklisted: bool
    is_prioritized: bool
    member_id: int | None


def _fingerprint(content: str) -> str:
    return _PUNCTUATION_PATTERN.sub("", content.lower())[:160]


def _is_question(content: str) -> bool:
    return "?" in content or "？" in content or content.rstrip().endswith("吗")


def decide_active_reply(
    *,
    settings: dict[str, object],
    activity: GroupReplyActivity,
    sender_key: str,
    member_id: int | None,
    content: str,
    timestamp: int,
    is_bot_message: bool,
    is_direct_mention: bool,
    is_command: bool,
    random_value: Callable[[], float],
) -> ActiveReplyDecision:
    """Apply response-rate first, with temporary spam and loop suppression.

    The state is deliberately bounded by the caller. This function does not use
    a fixed post-reply cooldown for human messages: each new message has its own
    rate sample after temporary protection factors are applied.
    """
    normalized = normalize_active_reply_settings(settings)
    if not normalized["enabled"]:
        return ActiveReplyDecision(False, "主动回复已关闭", 0.0, (), False, False, member_id)
    if is_command:
        return ActiveReplyDecision(False, "命令消息不参与主动回复", 0.0, (), False, False, member_id)

    blacklisted = member_id is not None and member_id in normalized["blacklist_member_ids"]
    prioritized = member_id is not None and member_id in normalized["priority_member_ids"]
    if blacklisted:
        return ActiveReplyDecision(False, "命中黑名单", 0.0, (), True, prioritized, member_id)
    if is_bot_message and not normalized["bot_message_participation"]:
        return ActiveReplyDecision(False, "机器人消息默认不参与", 0.0, (), False, prioritized, member_id)
    if is_bot_message and activity.last_bot_reply_at and timestamp - activity.last_bot_reply_at < 120:
        return ActiveReplyDecision(False, "机器人互聊保护中", 0.0, ("机器人互聊保护",), False, prioritized, member_id)

    # Reinsert the active sender so the bounded group state maintained by the
    # caller can evict the least-recently-active sender instead of whichever
    # member happened to speak first after startup.
    sender = activity.senders.pop(sender_key, None)
    if sender is None:
        sender = SenderActivity()
    activity.senders[sender_key] = sender
    fingerprint = _fingerprint(content)
    within_burst = sender.last_timestamp > 0 and timestamp - sender.last_timestamp <= 90
    sender.consecutive_count = sender.consecutive_count + 1 if within_burst else 1
    sender.question_streak = (
        sender.question_streak + 1 if within_burst and _is_question(content) else int(_is_question(content))
    )
    sender.mention_streak = (
        sender.mention_streak + 1 if within_burst and is_direct_mention else int(is_direct_mention)
    )
    repeated = bool(fingerprint and fingerprint == sender.last_fingerprint and within_burst)
    sender.last_timestamp = timestamp
    sender.last_fingerprint = fingerprint

    rate = float(normalized["base_reply_rate"])
    override = (normalized["member_overrides"] or {}).get(str(member_id), {})
    if isinstance(override, dict):
        rate *= float(override.get("reply_rate_multiplier", 1.0))
        sensitivity = float(override.get("anti_spam_sensitivity", 1.0))
    else:
        sensitivity = 1.0
    if prioritized:
        rate *= 1.6
    if is_bot_message:
        rate *= float(normalized["bot_message_weight"])

    protection_reasons: list[str] = []
    if normalized["anti_spam_enabled"]:
        threshold = max(2, ceil(int(normalized["consecutive_trigger_threshold"]) / sensitivity))
        burst_level = max(sender.consecutive_count, sender.question_streak, sender.mention_streak)
        if burst_level >= threshold:
            rate *= max(0.08, 0.55 ** (burst_level - threshold + 1))
            if sender.mention_streak >= threshold:
                protection_reasons.append("连续 @")
            elif sender.question_streak >= threshold:
                protection_reasons.append("连续追问")
            else:
                protection_reasons.append("短时连续发言")
        if repeated:
            rate *= 0.25
            protection_reasons.append("重复内容")

    rate = min(max(rate, 0.0), 0.85)
    should_reply = random_value() < rate
    if should_reply and is_bot_message:
        activity.last_bot_reply_at = timestamp
    reason = "命中回复率" if should_reply else "本轮未命中回复率"
    return ActiveReplyDecision(
        should_reply,
        reason,
        rate,
        tuple(protection_reasons),
        False,
        prioritized,
        member_id,
    )
