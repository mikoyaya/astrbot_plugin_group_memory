import assert from "node:assert/strict";
import test from "node:test";
import { deriveRelationshipSemantics } from "./relationship-semantics.mjs";

const now = 2_000_000_000;
const memberA = { member_id: 1, label: "甲" };
const memberB = { member_id: 2, label: "乙" };

function event(eventType, sourceType = "observed", secondsAgo = 60) {
  return { event_type: eventType, source_type: sourceType, event_timestamp: now - secondsAgo, content: eventType };
}

function direction(sourceMemberId, eventType, events) {
  return { source_member_id: sourceMemberId, target_member_id: sourceMemberId === 1 ? 2 : 1, event_type: eventType, events };
}

test("双向正向结构化事件判定朋友强", () => {
  const result = deriveRelationshipSemantics({
    memberA, memberB, nowSeconds: now,
    directionalEvents: [
      direction(1, "praise", [event("praise"), event("confirmation")]),
      direction(2, "praise", [event("praise"), event("praise"), event("confirmation")]),
    ],
  });
  assert.equal(result.semantic, "friend");
  assert.equal(result.intensity, "strong");
});

test("双方负向事件判定互喷强", () => {
  const result = deriveRelationshipSemantics({
    memberA, memberB, nowSeconds: now,
    directionalEvents: [
      direction(1, "complaint", [event("complaint"), event("complaint"), event("complaint")]),
      direction(2, "complaint", [event("complaint"), event("complaint"), event("complaint"), event("complaint")]),
    ],
  });
  assert.equal(result.semantic, "bickering");
  assert.equal(result.intensity, "strong");
});

test("正负混合的双向互动保守判定普通", () => {
  const result = deriveRelationshipSemantics({
    memberA, memberB, nowSeconds: now,
    directionalEvents: [
      direction(1, "praise", [event("praise"), event("mention")]),
      direction(2, "complaint", [event("complaint"), event("mention")]),
    ],
  });
  assert.equal(result.semantic, "ordinary");
  assert.equal(result.intensity, "medium");
});

test("达到互喷数量但混入正向信号时仍保守判定普通", () => {
  const result = deriveRelationshipSemantics({
    memberA, memberB, nowSeconds: now,
    directionalEvents: [
      direction(1, "complaint", [event("complaint"), event("complaint"), event("praise")]),
      direction(2, "complaint", [event("complaint"), event("complaint")]),
    ],
  });
  assert.equal(result.semantic, "ordinary");
});

test("单向提及与转述不能触发明确结论，转述不参与最近互动", () => {
  const result = deriveRelationshipSemantics({
    memberA, memberB, nowSeconds: now,
    directionalEvents: [
      direction(1, "mention", [event("mention", "observed", 300), event("reported", "reported", 10)]),
    ],
  });
  assert.equal(result.semantic, "pending");
  assert.equal(result.intensity, "weak");
  assert.equal(result.recent_timestamp, now - 300);
  assert.equal(result.reported_count, 1);
});
