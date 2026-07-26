export const RELATIONSHIP_WINDOW_SECONDS = 90 * 24 * 60 * 60;

const POSITIVE_EVENT_TYPES = new Set(["praise", "confirmation"]);
const NEGATIVE_EVENT_TYPES = new Set(["complaint"]);
const QUALIFYING_SOURCES = new Set(["manual", "observed"]);

const SEMANTIC_LABELS = {
  friend: "朋友",
  ordinary: "普通",
  distant: "冷淡",
  bickering: "互喷",
  hostile: "对立",
  caring: "关心",
  stranger: "路人",
  pending: "待判断",
};

function asNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function memberName(member, fallback) {
  return member?.label || member?.nickname || member?.user_id || fallback;
}

function emptyCounts() {
  return { aToB: 0, bToA: 0 };
}

function directionName(memberA, memberB, sourceMemberId) {
  return Number(sourceMemberId) === Number(memberA.member_id)
    ? `${memberName(memberA, "成员 A")} → ${memberName(memberB, "成员 B")}`
    : `${memberName(memberB, "成员 B")} → ${memberName(memberA, "成员 A")}`;
}

function intensityFor(semantic, stats) {
  if (semantic === "pending") return "weak";
  if (semantic === "friend") {
    return stats.positive.aToB >= 2 && stats.positive.bToA >= 2
      && stats.positive.total >= 5 ? "strong" : "medium";
  }
  if (semantic === "bickering") {
    return stats.negative.aToB >= 3 && stats.negative.bToA >= 3
      && stats.negative.total >= 7 ? "strong" : "medium";
  }
  if (semantic === "ordinary") {
    return !stats.mixed && stats.interactions.total >= 6 ? "strong" : "medium";
  }
  return "weak";
}

function reasonLines(semantic, stats, memberA, memberB) {
  const reasons = [];
  const aName = memberName(memberA, "成员 A");
  const bName = memberName(memberB, "成员 B");
  if (semantic === "friend") {
    reasons.push(`双方都有正向结构化互动：${aName} ${stats.positive.aToB} 条、${bName} ${stats.positive.bToA} 条。`);
    reasons.push(`近 90 天正向事件共 ${stats.positive.total} 条，未发现可参与判断的负向事件。`);
  } else if (semantic === "bickering") {
    reasons.push(`双方都有负向结构化互动：${aName} ${stats.negative.aToB} 条、${bName} ${stats.negative.bToA} 条。`);
    reasons.push(`近 90 天负向事件共 ${stats.negative.total} 条，达到互喷的保守阈值。`);
  } else if (semantic === "ordinary") {
    reasons.push(`双方均有互动：${aName} → ${bName} ${stats.interactions.aToB} 条，反向 ${stats.interactions.bToA} 条。`);
    if (stats.mixed) reasons.push("正负结构化信号混合，按保守规则不推断为朋友或互喷。");
    else reasons.push(`近 90 天双向结构化互动共 ${stats.interactions.total} 条，未满足强语义阈值。`);
  } else {
    reasons.push(`近 90 天仅检测到单向或不足量互动：${aName} → ${bName} ${stats.interactions.aToB} 条，反向 ${stats.interactions.bToA} 条。`);
    reasons.push("证据不足以推断明确关系，保持待判断。" );
  }
  if (stats.reported.total) {
    reasons.push(`另有 ${stats.reported.total} 条他人转述，仅作辅助参考，不参与自动结论。`);
  }
  return reasons.slice(0, 3);
}

export function semanticLabel(semantic) {
  return SEMANTIC_LABELS[semantic] || SEMANTIC_LABELS.pending;
}

export function intensityLabel(intensity) {
  return { weak: "弱", medium: "中", strong: "强" }[intensity] || "弱";
}

export function pendingRelationshipSemantics() {
  return {
    status: "analyzing",
    semantic: "pending",
    intensity: "weak",
    label: "待判断 · 弱",
    is_bidirectional: false,
    evidence_count: 0,
    recent_timestamp: 0,
    recent_content: "",
    reasons: ["正在读取近 90 天结构化证据。"],
    directional_counts: emptyCounts(),
  };
}

export function deriveRelationshipSemantics({ memberA, memberB, directionalEvents, nowSeconds }) {
  const cutoff = asNumber(nowSeconds) - RELATIONSHIP_WINDOW_SECONDS;
  const stats = {
    interactions: { ...emptyCounts(), total: 0 },
    positive: { ...emptyCounts(), total: 0 },
    negative: { ...emptyCounts(), total: 0 },
    reported: { ...emptyCounts(), total: 0 },
    evidenceCount: 0,
    recentTimestamp: 0,
    recentContent: "",
    mixed: false,
  };

  for (const aggregate of directionalEvents || []) {
    const sourceIsA = Number(aggregate.source_member_id) === Number(memberA.member_id);
    const direction = sourceIsA ? "aToB" : "bToA";
    for (const event of aggregate.events || []) {
      const timestamp = asNumber(event.event_timestamp);
      if (!timestamp || timestamp < cutoff) continue;
      const sourceType = String(event.source_type || "");
      const eventType = String(event.event_type || aggregate.event_type || "");
      if (sourceType === "reported") {
        stats.reported[direction] += 1;
        stats.reported.total += 1;
        stats.evidenceCount += 1;
        continue;
      }
      if (!QUALIFYING_SOURCES.has(sourceType)) continue;
      stats.evidenceCount += 1;
      stats.interactions[direction] += 1;
      stats.interactions.total += 1;
      if (POSITIVE_EVENT_TYPES.has(eventType)) {
        stats.positive[direction] += 1;
        stats.positive.total += 1;
      }
      if (NEGATIVE_EVENT_TYPES.has(eventType)) {
        stats.negative[direction] += 1;
        stats.negative.total += 1;
      }
      if (timestamp > stats.recentTimestamp) {
        stats.recentTimestamp = timestamp;
        stats.recentContent = String(event.content || "");
      }
    }
  }

  const isBidirectional = stats.interactions.aToB > 0 && stats.interactions.bToA > 0;
  stats.mixed = stats.positive.total > 0 && stats.negative.total > 0;
  let semantic = "pending";
  if (!stats.positive.total
    && stats.negative.aToB >= 2 && stats.negative.bToA >= 2 && stats.negative.total >= 4) {
    semantic = "bickering";
  } else if (!stats.negative.total
    && stats.positive.aToB >= 1 && stats.positive.bToA >= 1 && stats.positive.total >= 2) {
    semantic = "friend";
  } else if (isBidirectional) {
    semantic = "ordinary";
  }
  const intensity = intensityFor(semantic, stats);
  return {
    status: "complete",
    semantic,
    intensity,
    label: `${semanticLabel(semantic)} · ${intensityLabel(intensity)}`,
    is_bidirectional: isBidirectional,
    evidence_count: stats.evidenceCount,
    recent_timestamp: stats.recentTimestamp,
    recent_content: stats.recentContent,
    reasons: reasonLines(semantic, stats, memberA, memberB),
    directional_counts: stats.interactions,
    positive_counts: stats.positive,
    negative_counts: stats.negative,
    reported_count: stats.reported.total,
  };
}

export function relationshipDirectionLabel(memberA, memberB, sourceMemberId) {
  return directionName(memberA, memberB, sourceMemberId);
}
