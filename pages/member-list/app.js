import {
  RELATIONSHIP_WINDOW_SECONDS,
  deriveRelationshipSemantics,
  intensityLabel,
  pendingRelationshipSemantics,
  semanticLabel,
} from "./relationship-semantics.mjs";

const bridge = window.AstrBotPluginPage;
const refreshButton = document.getElementById("refresh-button");
const searchInput = document.getElementById("search-input");
const summary = document.getElementById("summary");
const membersViewButton = document.getElementById("members-view-button");
const networkViewButton = document.getElementById("network-view-button");
const membersView = document.getElementById("members-view");
const networkView = document.getElementById("network-view");
const table = document.getElementById("member-table");
const body = document.getElementById("member-body");
const emptyState = document.getElementById("empty-state");
const dialog = document.getElementById("member-dialog");
const dialogClose = document.getElementById("dialog-close");
const detailStatus = document.getElementById("detail-status");
const detailUserId = document.getElementById("detail-user-id");
const detailNickname = document.getElementById("detail-nickname");
const detailMemberStatus = document.getElementById("detail-member-status");
const detailGroup = document.getElementById("detail-group");
const detailMessageCount = document.getElementById("detail-message-count");
const detailLastMessage = document.getElementById("detail-last-message");
const detailProfile = document.getElementById("detail-profile");
const detailNoteSummary = document.getElementById("detail-note-summary");
const detailTagsSummary = document.getElementById("detail-tags-summary");
const detailRelationshipCount = document.getElementById("detail-relationship-count");
const detailRecentInteraction = document.getElementById("detail-recent-interaction");
const noteInput = document.getElementById("note-input");
const saveNoteButton = document.getElementById("save-note-button");
const detailTagList = document.getElementById("detail-tag-list");
const tagInput = document.getElementById("tag-input");
const addTagButton = document.getElementById("add-tag-button");
const aliasList = document.getElementById("alias-list");
const aliasInput = document.getElementById("alias-input");
const aliasTypeInput = document.getElementById("alias-type-input");
const addAliasButton = document.getElementById("add-alias-button");
const mergeTargetInput = document.getElementById("merge-target-input");
const mergeReasonInput = document.getElementById("merge-reason-input");
const mergeMemberButton = document.getElementById("merge-member-button");
const layeredTagList = document.getElementById("layered-tag-list");
const layeredTagInput = document.getElementById("layered-tag-input");
const tagLayerInput = document.getElementById("tag-layer-input");
const tagConfidenceInput = document.getElementById("tag-confidence-input");
const addLayeredTagButton = document.getElementById("add-layered-tag-button");
const relationshipEventList = document.getElementById("relationship-event-list");
const eventTypeInput = document.getElementById("event-type-input");
const eventTargetInput = document.getElementById("event-target-input");
const eventConfidenceInput = document.getElementById("event-confidence-input");
const eventContentInput = document.getElementById("event-content-input");
const addEventButton = document.getElementById("add-event-button");
const openNetworkButton = document.getElementById("open-network-button");
const networkCenterInput = document.getElementById("network-center-input");
const networkCenterResults = document.getElementById("network-center-results");
const networkScopeInput = document.getElementById("network-scope-input");
const networkTypeInput = document.getElementById("network-type-input");
const networkSourceInput = document.getElementById("network-source-input");
const networkLoadButton = document.getElementById("network-load-button");
const networkExpandButton = document.getElementById("network-expand-button");
const networkLowRelevanceButton = document.getElementById("network-low-relevance-button");
const networkResetViewButton = document.getElementById("network-reset-view-button");
const networkStatus = document.getElementById("network-status");
const networkCanvas = document.getElementById("network-canvas");
const networkEmpty = document.getElementById("network-empty");
const networkTooltip = document.getElementById("network-tooltip");
const relationshipDialog = document.getElementById("relationship-dialog");
const relationshipClose = document.getElementById("relationship-close");
const relationshipSummary = document.getElementById("relationship-summary");
const relationshipEvidenceList = document.getElementById("relationship-evidence-list");
const relationshipMoreButton = document.getElementById("relationship-more-button");

let members = [];
let selectedMember = null;
let networkCenter = null;
let networkData = null;
let networkExpanded = false;
let networkLowRelevanceVisible = false;
let activeAggregate = null;
let activeAggregateIdentity = null;
let evidenceCursor = null;
let networkGraph = null;
let networkViewport = { scale: 1, x: 0, y: 0 };
let networkPointerState = null;
let networkLoadToken = 0;
let networkLayoutSnapshot = null;
let suppressNetworkNodeClickUntil = 0;
let memberRelationshipAnalysisToken = 0;

const NETWORK_WIDTH = 980;
const NETWORK_HEIGHT = 620;
const NETWORK_MIN_SCALE = 0.82;
const NETWORK_MAX_SCALE = 2.2;
const NETWORK_DRAG_THRESHOLD_PX = 6;
const NETWORK_SECOND_LAYER_LIMIT = 12;

function text(value, fallback = "") {
  return value === undefined || value === null ? fallback : String(value);
}

function formatTimestamp(timestamp) {
  if (!timestamp) return "暂无";
  const date = new Date(Number(timestamp) * 1000);
  if (Number.isNaN(date.getTime())) return "未知";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date);
}

function memberIdentity(member) {
  return {
    platform_id: text(member.platform_id),
    group_id: text(member.group_id || member.external_group_id),
    user_id: text(member.user_id || member.external_user_id),
  };
}

function tagsFor(member) {
  if (Array.isArray(member.tags)) return member.tags;
  return text(member.tags).split(",").map((tag) => tag.trim()).filter(Boolean);
}

function memberStatusLabel(status) {
  return text(status) === "mentioned_only" ? "仅被提及" : "正常成员";
}

function eventTypeLabel(eventType) {
  const labels = {
    mention: "提及", evaluation: "评价", praise: "夸赞",
    complaint: "抱怨", reported: "传闻/转述", confirmation: "确认行为",
  };
  return labels[text(eventType)] || text(eventType, "未知事件");
}

function eventSourceLabel(sourceType) {
  const labels = { observed: "机器人观察", manual: "人工记录", reported: "他人转述" };
  return labels[text(sourceType)] || text(sourceType, "未知来源");
}

function aggregateLabel(aggregate) {
  const source = aggregate.source?.nickname || aggregate.source?.user_id || "未知成员";
  const target = aggregate.target?.nickname || aggregate.target?.user_id || "无目标成员";
  return `${source} → ${target} x${aggregate.count}`;
}

function sourceCountsLabel(sourceCounts) {
  const entries = Object.entries(sourceCounts || {});
  if (!entries.length) return "暂无来源";
  return entries.map(([source, count]) => `${eventSourceLabel(source)} ${count}`).join("；");
}

function sameMember(left, right) {
  const leftId = memberIdentity(left);
  const rightId = memberIdentity(right);
  return leftId.platform_id === rightId.platform_id
    && leftId.group_id === rightId.group_id
    && leftId.user_id === rightId.user_id;
}

function groupLabel(member) {
  const groupId = member.group_id || member.external_group_id || "未知群号";
  return member.group_name ? `${member.group_name} (${groupId})` : `群号 ${groupId}`;
}

function createTextCell(value, className = "") {
  const cell = document.createElement("td");
  cell.className = className;
  cell.textContent = value || "-";
  return cell;
}

function createGroupCell(member) {
  const cell = document.createElement("td");
  cell.className = "group-cell";
  const name = document.createElement("strong");
  name.textContent = member.group_name || "未命名群";
  const id = document.createElement("span");
  id.textContent = `群号 ${member.group_id || member.external_group_id || "未知"}`;
  cell.append(name, id);
  return cell;
}

function createMemberCell(member) {
  const cell = document.createElement("td");
  const button = document.createElement("button");
  button.className = "member-link";
  button.type = "button";
  button.title = `查看 ${member.nickname || member.user_id || member.external_user_id} 的详情`;
  const name = document.createElement("strong");
  name.textContent = member.nickname || `成员 ${member.user_id || member.external_user_id}`;
  const id = document.createElement("span");
  id.textContent = `QQ ${member.user_id || member.external_user_id || "未知"}`;
  button.append(name);
  if (text(member.member_status) === "mentioned_only") {
    const badge = document.createElement("span");
    badge.className = "member-status-badge mentioned-only";
    badge.textContent = "仅被提及";
    button.append(badge);
  }
  button.append(id);
  button.addEventListener("click", () => openMember(member));
  cell.append(button);
  return cell;
}

function render() {
  const query = searchInput.value.trim().toLocaleLowerCase();
  const filtered = members.filter((member) => {
    const searchable = [
      member.group_name, member.group_id, member.external_group_id,
      member.nickname, member.user_id, member.external_user_id,
      member.tags, member.note,
      ...(Array.isArray(member.aliases) ? member.aliases : []),
    ].join(" ").toLocaleLowerCase();
    return !query || searchable.includes(query);
  });
  body.replaceChildren();
  for (const member of filtered) {
    const row = document.createElement("tr");
    row.append(
      createGroupCell(member), createMemberCell(member),
      createTextCell(memberStatusLabel(member.member_status),
        text(member.member_status) === "mentioned_only" ? "status-cell mentioned-only" : "status-cell"),
      createTextCell(String(member.message_count || 0)),
      createTextCell(formatTimestamp(member.last_message_timestamp)),
      createTextCell(tagsFor(member).join("、") || "暂无", "tag-cell"),
      createTextCell(member.note || "暂无", "note-cell"),
    );
    body.append(row);
  }
  table.hidden = filtered.length === 0;
  emptyState.hidden = filtered.length !== 0;
  summary.textContent = members.length === 0
    ? "暂无已记录成员" : `显示 ${filtered.length} / ${members.length} 名成员`;
}

function controls() {
  return [
    saveNoteButton, addTagButton, noteInput, tagInput,
    aliasInput, aliasTypeInput, addAliasButton, mergeTargetInput,
    mergeReasonInput, mergeMemberButton, layeredTagInput, tagLayerInput,
    tagConfidenceInput, addLayeredTagButton, eventTypeInput, eventTargetInput,
    eventConfidenceInput, eventContentInput, addEventButton,
  ];
}

function setDialogBusy(busy, message = "") {
  dialog.dataset.busy = busy ? "true" : "false";
  controls().forEach((element) => { element.disabled = busy; });
  detailStatus.textContent = message;
}

function recordRow({ title, meta = "", removeTitle, onRemove }) {
  const row = document.createElement("div");
  row.className = "record-row";
  const copy = document.createElement("div");
  const strong = document.createElement("strong");
  strong.textContent = title;
  const small = document.createElement("span");
  small.textContent = meta;
  copy.append(strong, small);
  row.append(copy);
  if (onRemove) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "record-remove";
    remove.title = removeTitle;
    remove.setAttribute("aria-label", removeTitle);
    remove.textContent = "×";
    remove.addEventListener("click", onRemove);
    row.append(remove);
  }
  return row;
}

function renderAliases(member) {
  aliasList.replaceChildren();
  const aliases = Array.isArray(member.aliases) ? member.aliases : [];
  if (!aliases.length) {
    aliasList.append(recordRow({ title: "暂无别名", meta: "收到新昵称后会自动记录" }));
    return;
  }
  aliases.forEach((alias) => aliasList.append(recordRow({
    title: alias.alias,
    meta: `${alias.alias_type} · ${Math.round(Number(alias.confidence || 0) * 100)}% · ${alias.source_type}`,
    removeTitle: `删除别名 ${alias.alias}`,
    onRemove: () => removeAlias(alias.id),
  })));
}

function renderLayeredTags(member) {
  layeredTagList.replaceChildren();
  const tags = Array.isArray(member.layered_tags) ? member.layered_tags : [];
  if (!tags.length) {
    layeredTagList.append(recordRow({ title: "暂无分层标签", meta: "人工标签与机器人观察会明确区分" }));
    return;
  }
  tags.forEach((tag) => layeredTagList.append(recordRow({
    title: tag.name,
    meta: `${tag.layer} · ${Math.round(Number(tag.confidence || 0) * 100)}% · ${tag.source_type}`,
    removeTitle: `删除标签 ${tag.name}`,
    onRemove: tag.id ? () => removeLayeredTag(tag.id) : null,
  })));
}

function eventLabel(event) {
  const source = event.source_nickname || event.source_user_id || "未知成员";
  const target = event.target_nickname || event.target_user_id || "无目标成员";
  return `发起人：${source}；被提及人：${target}`;
}

function renderEvents(member) {
  relationshipEventList.replaceChildren();
  const aggregates = Array.isArray(member.relationship_aggregates)
    ? member.relationship_aggregates : [];
  if (!aggregates.length) {
    relationshipEventList.append(recordRow({ title: "暂无关系事件", meta: "可人工记录，也会保存唯一明确的 @提及" }));
    return;
  }
  const pairMap = new Map();
  aggregates.forEach((aggregate) => {
    if (aggregate.target_member_id === null || aggregate.target_member_id === undefined) {
      const key = `unpaired:${aggregate.source_member_id}:${aggregate.event_type}`;
      pairMap.set(key, { aggregates: [aggregate], unpaired: true });
      return;
    }
    const key = pairKey(aggregate.source_member_id, aggregate.target_member_id);
    const entry = pairMap.get(key) || { aggregates: [], unpaired: false };
    entry.aggregates.push(aggregate);
    pairMap.set(key, entry);
  });
  const pairs = [];
  [...pairMap.values()].forEach((entry) => {
    if (entry.unpaired) {
      const aggregate = entry.aggregates[0];
      const row = recordRow({
        title: `${eventTypeLabel(aggregate.event_type)} · ${aggregateLabel(aggregate)}`,
        meta: `来源：${sourceCountsLabel(aggregate.source_counts)}；最近：${formatTimestamp(aggregate.last_time)}；无明确目标成员`,
      });
      row.classList.add("interactive-record");
      row.tabIndex = 0;
      row.addEventListener("click", () => openAggregate(aggregate));
      relationshipEventList.append(row);
      return;
    }
    const source = entry.aggregates[0].source || selectedMember;
    const target = entry.aggregates[0].target || { member_id: entry.aggregates[0].target_member_id };
    const pair = {
      id: `detail:${pairKey(source.member_id, target.member_id)}`,
      memberA: Number(source.member_id) < Number(target.member_id) ? source : target,
      memberB: Number(source.member_id) < Number(target.member_id) ? target : source,
      aggregates: entry.aggregates,
      analysis: pendingRelationshipSemantics(),
    };
    pairs.push(pair);
    const row = recordRow({
      title: `待判断 · 弱 · ${memberDisplayName(pair.memberA)} ↔ ${memberDisplayName(pair.memberB)}`,
      meta: `正在按成员对分析近 90 天结构化证据；聚合事件 ${entry.aggregates.length} 类。`,
    });
    row.dataset.pairId = pair.id;
    row.classList.add("interactive-record");
    row.tabIndex = 0;
    row.addEventListener("click", () => openRelationshipPair(pair));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openRelationshipPair(pair);
      }
    });
    relationshipEventList.append(row);
  });
  analyzeMemberRelationshipPairs(pairs, member);
}

async function analyzeMemberRelationshipPairs(pairs, member) {
  const identity = memberIdentity(member);
  const token = ++memberRelationshipAnalysisToken;
  const nowSeconds = Math.floor(Date.now() / 1000);
  const cutoffTimestamp = nowSeconds - RELATIONSHIP_WINDOW_SECONDS;
  try {
    await mapConcurrent(pairs, 1, async (pair) => {
      const directionalEvents = await mapConcurrent(pair.aggregates, 3,
        (aggregate) => loadAggregateWindowEvents(aggregate, identity, cutoffTimestamp));
      if (token !== memberRelationshipAnalysisToken || !selectedMember || !sameMember(selectedMember, member)) return;
      pair.analysis = deriveRelationshipSemantics({
        memberA: pair.memberA,
        memberB: pair.memberB,
        directionalEvents,
        nowSeconds,
      });
      const row = [...relationshipEventList.children].find((item) => item.dataset.pairId === pair.id);
      if (!row) return;
      row.querySelector("strong").textContent = `${pair.analysis.label} · ${memberDisplayName(pair.memberA)} ↔ ${memberDisplayName(pair.memberB)}`;
      row.querySelector("span").textContent = `近 90 天证据 ${pair.analysis.evidence_count} 条；最近：${formatTimestamp(pair.analysis.recent_timestamp)}；${pair.analysis.reasons.join(" ")}`;
    });
  } catch {
    // The existing relationship rows remain available as a safe fallback.
  }
}

function renderLegacyTags(member) {
  detailTagList.replaceChildren();
  const tags = tagsFor(member);
  if (!tags.length) {
    const empty = document.createElement("span");
    empty.className = "muted-text";
    empty.textContent = "暂无标签";
    detailTagList.append(empty);
    return;
  }
  tags.forEach((tagName) => {
    const tag = document.createElement("span");
    tag.className = "tag-chip";
    const label = document.createElement("span");
    label.textContent = tagName;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.title = `删除标签 ${tagName}`;
    remove.setAttribute("aria-label", `删除标签 ${tagName}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => removeTag(tagName));
    tag.append(label, remove);
    detailTagList.append(tag);
  });
}

function renderDetail(member) {
  const aggregates = Array.isArray(member.relationship_aggregates)
    ? member.relationship_aggregates : [];
  const totalInteractions = aggregates.reduce(
    (total, aggregate) => total + Number(aggregate.count || 0), 0,
  );
  const mostRecent = [...aggregates].sort(
    (left, right) => Number(right.last_time || 0) - Number(left.last_time || 0),
  )[0];
  detailUserId.textContent = member.user_id || member.external_user_id || "-";
  detailNickname.textContent = member.nickname || "未获取昵称";
  detailMemberStatus.textContent = memberStatusLabel(member.member_status);
  detailGroup.textContent = groupLabel(member);
  detailMessageCount.textContent = String(member.message_count || 0);
  detailLastMessage.textContent = formatTimestamp(member.last_message_timestamp);
  detailProfile.textContent = member.summary || "暂无";
  detailNoteSummary.textContent = member.note || "暂无";
  detailTagsSummary.textContent = tagsFor(member).join("、") || "暂无";
  detailRelationshipCount.textContent = aggregates.length
    ? `${aggregates.length} 条聚合关系 · ${totalInteractions} 次互动`
    : "暂无";
  detailRecentInteraction.textContent = mostRecent
    ? `${eventTypeLabel(mostRecent.event_type)} · ${aggregateLabel(mostRecent)} · ${formatTimestamp(mostRecent.last_time)}${mostRecent.last_evidence ? ` · ${text(mostRecent.last_evidence).slice(0, 48)}` : ""}`
    : "暂无";
  noteInput.value = member.note || "";
  renderLegacyTags(member);
  renderAliases(member);
  renderLayeredTags(member);
  renderEvents(member);
}

function setView(view) {
  const isNetwork = view === "network";
  membersView.hidden = isNetwork;
  networkView.hidden = !isNetwork;
  membersViewButton.classList.toggle("is-active", !isNetwork);
  networkViewButton.classList.toggle("is-active", isNetwork);
  if (isNetwork && networkCenter && !networkData) loadNetwork();
}

function chooseNetworkCenter(member) {
  networkLoadToken += 1;
  networkLayoutSnapshot = null;
  networkCenter = { ...memberIdentity(member), member_id: Number(member.member_id || 0) };
  networkCenterInput.value = member.nickname || member.user_id || member.external_user_id || "";
  networkData = null;
  networkExpanded = false;
  networkLowRelevanceVisible = false;
  networkPointerState = null;
  suppressNetworkNodeClickUntil = 0;
  document.body.classList.remove("is-network-dragging");
  networkCanvas.classList.remove("is-dragging-node", "is-panning");
  networkGraph = null;
  networkCanvas.replaceChildren();
  hideNetworkTooltip();
  resetNetworkViewport();
  networkLowRelevanceButton.hidden = true;
  networkLowRelevanceButton.textContent = "显示低相关节点";
  networkLowRelevanceButton.setAttribute("aria-pressed", "false");
  networkCenterResults.hidden = true;
  setView("network");
}

function filteredCenterMembers(query) {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return members.slice(0, 8);
  return members.filter((member) => [
    member.nickname, member.user_id, member.external_user_id,
    member.group_id, member.group_name, member.note, member.tags,
    ...(Array.isArray(member.aliases) ? member.aliases : []),
  ].join(" ").toLocaleLowerCase().includes(normalized)).slice(0, 8);
}

function renderCenterResults() {
  const matches = filteredCenterMembers(networkCenterInput.value);
  networkCenterResults.replaceChildren();
  matches.forEach((member) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${member.nickname || "未命名成员"} · QQ ${member.user_id || member.external_user_id}`;
    button.addEventListener("click", () => chooseNetworkCenter(member));
    networkCenterResults.append(button);
  });
  networkCenterResults.hidden = matches.length === 0;
}

async function loadNetwork() {
  if (!networkCenter) {
    networkStatus.textContent = "请选择一名成员作为关系网中心。";
    networkEmpty.hidden = false;
    networkCanvas.replaceChildren();
    networkGraph = null;
    hideNetworkTooltip();
    return;
  }
  const loadToken = ++networkLoadToken;
  const center = { ...networkCenter };
  networkLoadButton.disabled = true;
  networkStatus.textContent = "正在加载关系网…";
  try {
    const parameters = {
      ...center,
      scope: networkScopeInput.value,
      node_limit: networkExpanded ? 100 : 30,
      edge_limit: networkExpanded ? 200 : 50,
    };
    if (networkTypeInput.value) parameters.event_type = networkTypeInput.value;
    if (networkSourceInput.value) parameters.source_type = networkSourceInput.value;
    const loadedNetwork = await bridge.apiGet("relationship-network", parameters);
    if (loadToken !== networkLoadToken) return;
    networkData = loadedNetwork;
    renderNetwork(networkData);
  } catch (error) {
    if (loadToken !== networkLoadToken) return;
    networkData = null;
    networkCanvas.replaceChildren();
    networkGraph = null;
    hideNetworkTooltip();
    networkEmpty.hidden = false;
    networkStatus.textContent = error.message || "读取关系网失败";
  } finally {
    if (loadToken === networkLoadToken) networkLoadButton.disabled = false;
  }
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
  return element;
}

function memberDisplayName(member) {
  return member?.label || member?.nickname || member?.user_id || member?.external_user_id || "未命名成员";
}

function semanticColor(semantic) {
  const colors = {
    friend: "#55dfae",
    ordinary: "#83a9d8",
    distant: "#8b99aa",
    bickering: "#ff855f",
    hostile: "#bc3e50",
    caring: "#8ce9a7",
    stranger: "#77869a",
    pending: "#91a6c2",
  };
  return colors[semantic] || colors.pending;
}

function semanticClass(semantic) {
  return `semantic-${text(semantic, "pending")}`;
}

function aggregateKey(aggregate) {
  return [
    Number(aggregate.source_member_id),
    Number(aggregate.target_member_id),
    text(aggregate.event_type),
  ].join(":");
}

function pairKey(firstMemberId, secondMemberId) {
  return [Number(firstMemberId), Number(secondMemberId)].sort((left, right) => left - right).join(":");
}

function aggregateMember(aggregate, role, nodesById) {
  const member = aggregate[role];
  if (member && typeof member === "object") return member;
  const memberId = role === "source" ? aggregate.source_member_id : aggregate.target_member_id;
  return nodesById.get(Number(memberId)) || {
    member_id: Number(memberId),
    label: role === "source" ? aggregate.source_user_id : aggregate.target_user_id,
  };
}

function buildRelationshipPairs(aggregates, nodes = []) {
  const nodesById = new Map(nodes.map((node) => [Number(node.member_id), node]));
  const pairs = new Map();
  (aggregates || []).forEach((aggregate) => {
    if (aggregate.target_member_id === null || aggregate.target_member_id === undefined) return;
    const source = aggregateMember(aggregate, "source", nodesById);
    const target = aggregateMember(aggregate, "target", nodesById);
    const key = pairKey(source.member_id, target.member_id);
    let pair = pairs.get(key);
    if (!pair) {
      const [firstMemberId] = key.split(":").map(Number);
      const memberA = Number(source.member_id) === firstMemberId ? source : target;
      const memberB = Number(source.member_id) === firstMemberId ? target : source;
      pair = {
        id: `pair:${key}`,
        key,
        memberA,
        memberB,
        aggregates: [],
        weight: 0,
        last_time: 0,
        analysis: pendingRelationshipSemantics(),
        level: 3,
      };
      pairs.set(key, pair);
    }
    pair.aggregates.push(aggregate);
    pair.weight += Number(aggregate.count || 0);
    pair.last_time = Math.max(pair.last_time, Number(aggregate.last_time || 0));
  });
  return [...pairs.values()];
}

function sortByWeight(items) {
  return [...items].sort((left, right) => Number(right.weight || 0) - Number(left.weight || 0)
    || Number(right.last_time || 0) - Number(left.last_time || 0)
    || Number(left.member_id || left.memberA?.member_id || 0) - Number(right.member_id || right.memberA?.member_id || 0));
}

function networkLevelForMember(levels, memberId) {
  return levels.get(Number(memberId)) ?? 3;
}

function rankDirectNetworkMembers(pairs, centerMemberId) {
  const centerId = Number(centerMemberId);
  const direct = new Map();
  pairs.forEach((pair) => {
    const memberIds = [Number(pair.memberA.member_id), Number(pair.memberB.member_id)];
    if (!memberIds.includes(centerId)) return;
    const otherMemberId = memberIds.find((memberId) => memberId !== centerId);
    if (otherMemberId === undefined) return;
    const current = direct.get(otherMemberId) || { member_id: otherMemberId, weight: 0, last_time: 0 };
    current.weight += Number(pair.weight || 0);
    current.last_time = Math.max(current.last_time, Number(pair.last_time || 0));
    direct.set(otherMemberId, current);
  });
  return sortByWeight([...direct.values()]);
}

function deriveNetworkLevels(nodes, pairs, centerMemberId) {
  const centerId = Number(centerMemberId);
  const directMemberIds = new Set(
    rankDirectNetworkMembers(pairs, centerId).map((item) => item.member_id),
  );
  const related = new Map();
  pairs.forEach((pair) => {
    const memberIds = [Number(pair.memberA.member_id), Number(pair.memberB.member_id)];
    memberIds.forEach((memberId) => {
      if (memberId === centerId || directMemberIds.has(memberId)) return;
      const current = related.get(memberId) || { member_id: memberId, weight: 0, last_time: 0, direct: false };
      current.weight += pair.weight;
      current.last_time = Math.max(current.last_time, pair.last_time);
      related.set(memberId, current);
    });
  });
  const secondCandidates = sortByWeight([...related.values()]
    .filter((item) => !directMemberIds.has(item.member_id)));
  const secondLayerIds = new Set(secondCandidates
    .slice(0, NETWORK_SECOND_LAYER_LIMIT).map((item) => item.member_id));
  const levels = new Map([[centerId, 0]]);
  nodes.forEach((node) => {
    const memberId = Number(node.member_id);
    if (memberId === centerId) return;
    levels.set(memberId, directMemberIds.has(memberId) ? 1 : secondLayerIds.has(memberId) ? 2 : 3);
  });
  pairs.forEach((pair) => {
    pair.level = Math.max(
      networkLevelForMember(levels, pair.memberA.member_id),
      networkLevelForMember(levels, pair.memberB.member_id),
    );
  });
  return levels;
}

function positionLayer(nodes, radiusX, radiusY, positions) {
  const centerX = NETWORK_WIDTH / 2;
  const centerY = NETWORK_HEIGHT / 2;
  nodes.forEach((node, index) => {
    const angle = (-Math.PI / 2) + ((Math.PI * 2 * index) / Math.max(nodes.length, 1));
    positions.set(Number(node.member_id), {
      x: centerX + Math.cos(angle) * radiusX,
      y: centerY + Math.sin(angle) * radiusY,
    });
  });
}

function nodePositions(nodes, centerMemberId, levels, pairs) {
  const positions = new Map();
  const centerId = Number(centerMemberId);
  const directOrder = new Map(
    rankDirectNetworkMembers(pairs, centerId)
      .map((item, index) => [Number(item.member_id), index]),
  );
  positions.set(centerId, { x: NETWORK_WIDTH / 2, y: NETWORK_HEIGHT / 2 });
  [1, 2, 3].forEach((level) => {
    const layerNodes = nodes.filter((node) => Number(node.member_id) !== centerId
      && levels.get(Number(node.member_id)) === level)
      .sort((left, right) => {
        if (level === 1) {
          return (directOrder.get(Number(left.member_id)) ?? Number.MAX_SAFE_INTEGER)
            - (directOrder.get(Number(right.member_id)) ?? Number.MAX_SAFE_INTEGER);
        }
        const leftWeight = pairs.filter((pair) => Number(pair.memberA.member_id) === Number(left.member_id)
          || Number(pair.memberB.member_id) === Number(left.member_id)).reduce((sum, pair) => sum + pair.weight, 0);
        const rightWeight = pairs.filter((pair) => Number(pair.memberA.member_id) === Number(right.member_id)
          || Number(pair.memberB.member_id) === Number(right.member_id)).reduce((sum, pair) => sum + pair.weight, 0);
        return rightWeight - leftWeight || Number(left.member_id) - Number(right.member_id);
      });
    const radii = {
      1: [
        Math.min(430, 235 + Math.max(0, layerNodes.length - 6) * 9),
        Math.min(260, 145 + Math.max(0, layerNodes.length - 6) * 6),
      ],
      2: [365, 225],
      3: [445, 270],
    }[level];
    positionLayer(layerNodes, radii[0], radii[1], positions);
  });
  return positions;
}

function pairIncludesMember(pair, memberId) {
  return Number(pair.memberA.member_id) === Number(memberId)
    || Number(pair.memberB.member_id) === Number(memberId);
}

function pairTooltip(pair) {
  const analysis = pair.analysis || pendingRelationshipSemantics();
  const [aToB, bToA] = [analysis.directional_counts?.aToB || 0, analysis.directional_counts?.bToA || 0];
  return [
    `${memberDisplayName(pair.memberA)} ↔ ${memberDisplayName(pair.memberB)}`,
    `关系：${analysis.label}`,
    `双向互动：${analysis.is_bidirectional ? "是" : "否"}（${aToB}/${bToA}）`,
    `近 90 天证据：${analysis.evidence_count || 0} 条`,
    `最近互动：${formatTimestamp(analysis.recent_timestamp)}`,
    ...(analysis.reasons || []).slice(0, 3),
  ].join("\n");
}

function nodeTooltip(node) {
  const identity = node.user_id || node.external_user_id || "暂无";
  const pairs = networkGraph?.pairs.filter((pair) => pairIncludesMember(pair, node.member_id)) || [];
  const strongest = sortByWeight(pairs)[0];
  return [
    memberDisplayName(node),
    `QQ：${identity}`,
    `状态：${memberStatusLabel(node.member_status)}`,
    `关联成员对：${pairs.length} 个`,
    strongest ? `最强关系：${strongest.analysis.label}` : "暂无关系证据",
  ].join("\n");
}

function setNetworkTooltip(content, event) {
  if (!content) return hideNetworkTooltip();
  networkTooltip.textContent = content;
  networkTooltip.hidden = false;
  positionNetworkTooltip(event);
}

function positionNetworkTooltip(event) {
  if (networkTooltip.hidden) return;
  const container = networkCanvas.parentElement;
  const bounds = container.getBoundingClientRect();
  const offsetX = Math.min(Math.max(event.clientX - bounds.left + 14, 12), bounds.width - 230);
  const offsetY = Math.min(Math.max(event.clientY - bounds.top + 14, 12), bounds.height - 118);
  networkTooltip.style.left = `${offsetX}px`;
  networkTooltip.style.top = `${offsetY}px`;
}

function hideNetworkTooltip() {
  networkTooltip.hidden = true;
  networkTooltip.textContent = "";
}

function updateNetworkViewport() {
  if (!networkGraph?.viewport) return;
  networkGraph.viewport.setAttribute(
    "transform",
    `translate(${networkViewport.x} ${networkViewport.y}) scale(${networkViewport.scale})`,
  );
}

function resetNetworkViewport() {
  networkViewport = { scale: 1, x: 0, y: 0 };
  updateNetworkViewport();
}

function resetNetworkLayout() {
  if (!networkGraph) return;
  networkGraph.positions = nodePositions(
    networkGraph.nodes,
    networkGraph.centerMemberId,
    networkGraph.levels,
    networkGraph.pairs,
  );
  networkGraph.nodeElements.forEach((_, memberId) => updateNodeGeometry(memberId));
  const centerPosition = networkGraph.positions.get(Number(networkGraph.centerMemberId));
  if (centerPosition) {
    centerPosition.x = NETWORK_WIDTH / 2;
    centerPosition.y = NETWORK_HEIGHT / 2;
    updateNodeGeometry(networkGraph.centerMemberId);
  }
  applyNetworkVisibility();
}

function resetNetworkView() {
  networkLowRelevanceVisible = false;
  resetNetworkViewport();
  resetNetworkLayout();
}

function updateEdgeGeometry(edgeId) {
  if (!networkGraph) return;
  const pair = networkGraph.pairs.find((item) => item.id === edgeId);
  if (!pair) return;
  const from = networkGraph.positions.get(Number(pair.memberA.member_id));
  const to = networkGraph.positions.get(Number(pair.memberB.member_id));
  const element = networkGraph.pairElements.get(edgeId);
  if (!from || !to || !element) return;
  const line = element.querySelector("line");
  const label = element.querySelector("text");
  line.setAttribute("x1", from.x);
  line.setAttribute("y1", from.y);
  line.setAttribute("x2", to.x);
  line.setAttribute("y2", to.y);
  label.setAttribute("x", (from.x + to.x) / 2);
  label.setAttribute("y", (from.y + to.y) / 2 - 9);
}

function updateNodeGeometry(memberId) {
  if (!networkGraph) return;
  const position = networkGraph.positions.get(Number(memberId));
  const element = networkGraph.nodeElements.get(Number(memberId));
  if (!position || !element) return;
  element.querySelectorAll("circle").forEach((circle) => {
    circle.setAttribute("cx", position.x);
    circle.setAttribute("cy", position.y);
  });
  const label = element.querySelector("text");
  label.setAttribute("x", position.x);
  label.setAttribute("y", position.y + 5);
  networkGraph.pairs.forEach((pair) => {
    if (pairIncludesMember(pair, memberId)) {
      updateEdgeGeometry(pair.id);
    }
  });
}

function setNetworkFocus(memberId = null, edgeId = null) {
  if (!networkGraph) return;
  networkGraph.nodeElements.forEach((element, id) => {
    const connected = !memberId || Number(id) === Number(memberId)
      || networkGraph.pairs.some((pair) => pairIncludesMember(pair, memberId) && pairIncludesMember(pair, id));
    element.classList.toggle("is-dimmed", Boolean(memberId) && !connected);
    element.classList.toggle("is-highlighted", Boolean(memberId) && Number(id) === Number(memberId));
  });
  networkGraph.pairElements.forEach((element, id) => {
    const pair = networkGraph.pairs.find((item) => item.id === id);
    const connected = edgeId ? id === edgeId : !memberId
      || pairIncludesMember(pair, memberId);
    element.classList.toggle("is-dimmed", !connected);
    element.classList.toggle("is-highlighted", Boolean(edgeId) && id === edgeId);
  });
}

function clearNetworkFocus() {
  setNetworkFocus();
  if (!networkGraph) return;
  networkGraph.nodeElements.forEach((element) => {
    element.classList.remove("is-dimmed", "is-highlighted");
  });
  networkGraph.pairElements.forEach((element) => {
    element.classList.remove("is-dimmed", "is-highlighted");
  });
}

function graphPointFromEvent(event) {
  const point = networkCanvas.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  const matrix = networkCanvas.getScreenCTM();
  if (!matrix) return { x: 0, y: 0 };
  return point.matrixTransform(matrix.inverse());
}

function graphPositionFromEvent(event) {
  const point = graphPointFromEvent(event);
  return {
    x: (point.x - networkViewport.x) / networkViewport.scale,
    y: (point.y - networkViewport.y) / networkViewport.scale,
  };
}

function screenDistance(pointerState, event) {
  return Math.hypot(event.clientX - pointerState.startClientX, event.clientY - pointerState.startClientY);
}

function networkContextKey() {
  if (!networkCenter) return "";
  return [
    networkCenter.platform_id,
    networkCenter.group_id,
    networkCenter.member_id,
    networkScopeInput.value,
    networkTypeInput.value,
    networkSourceInput.value,
  ].join("|");
}

function captureNetworkLayoutSnapshot() {
  if (!networkGraph) return;
  const directMemberIds = networkGraph.collapsedDirectMemberIds || new Set();
  const retainedMemberIds = new Set([
    Number(networkGraph.centerMemberId),
    ...directMemberIds,
  ]);
  const positions = new Map();
  retainedMemberIds.forEach((memberId) => {
    const position = networkGraph.positions.get(memberId);
    if (position) positions.set(memberId, { ...position });
  });
  networkLayoutSnapshot = {
    key: networkContextKey(),
    directMemberIds: new Set(directMemberIds),
    positions,
  };
}

function applyNetworkVisibility() {
  if (!networkGraph) return;
  const centerNodeId = Number(networkGraph.centerMemberId);
  const directMemberIds = networkGraph.directMemberIds || new Set();
  const retainedDirectMemberIds = networkGraph.collapsedDirectMemberIds || new Set();
  const hiddenNodeIds = new Set();
  directMemberIds.forEach((memberId) => {
    if (!retainedDirectMemberIds.has(memberId)) hiddenNodeIds.add(memberId);
  });
  if (!networkLowRelevanceVisible) {
    networkGraph.nodeElements.forEach((_, memberId) => {
      const normalizedMemberId = Number(memberId);
      if (normalizedMemberId !== centerNodeId && !directMemberIds.has(normalizedMemberId)) {
        hiddenNodeIds.add(normalizedMemberId);
      }
    });
  }
  hiddenNodeIds.delete(centerNodeId);
  const visibleNodeIds = new Set();
  networkGraph.nodeElements.forEach((_, memberId) => {
    const normalizedMemberId = Number(memberId);
    if (!hiddenNodeIds.has(normalizedMemberId)) visibleNodeIds.add(normalizedMemberId);
  });
  visibleNodeIds.add(centerNodeId);
  networkGraph.hiddenNodeIds = hiddenNodeIds;
  networkGraph.nodeElements.forEach((element, memberId) => {
    const visible = visibleNodeIds.has(Number(memberId));
    element.hidden = !visible;
    element.style.display = visible ? "" : "none";
    element.setAttribute("aria-hidden", String(!visible));
  });
  networkGraph.pairElements.forEach((element, pairId) => {
    const pair = networkGraph.pairs.find((item) => item.id === pairId);
    const visible = Boolean(pair)
      && !hiddenNodeIds.has(Number(pair.memberA.member_id))
      && !hiddenNodeIds.has(Number(pair.memberB.member_id));
    element.hidden = !visible;
    element.style.display = visible ? "" : "none";
    element.setAttribute("aria-hidden", String(!visible));
  });
  const outerNodeCount = [...networkGraph.nodeElements.keys()]
    .filter((memberId) => Number(memberId) !== centerNodeId && !directMemberIds.has(Number(memberId))).length;
  networkLowRelevanceButton.hidden = outerNodeCount === 0;
  const directSummary = `保留 ${retainedDirectMemberIds.size} 个直连`;
  networkLowRelevanceButton.textContent = networkLowRelevanceVisible
    ? `收起 ${outerNodeCount} 个外围节点（${directSummary}）`
    : `显示 ${outerNodeCount} 个外围节点（${directSummary}）`;
  networkLowRelevanceButton.setAttribute("aria-pressed", String(networkLowRelevanceVisible));
}

function addNetworkPointerInteractions() {
  networkCanvas.addEventListener("wheel", (event) => {
    if (!networkGraph) return;
    event.preventDefault();
    const point = graphPointFromEvent(event);
    const previousScale = networkViewport.scale;
    const factor = event.deltaY < 0 ? 1.12 : 0.89;
    const nextScale = Math.min(NETWORK_MAX_SCALE, Math.max(NETWORK_MIN_SCALE, previousScale * factor));
    if (nextScale === previousScale) return;
    networkViewport.x = point.x - ((point.x - networkViewport.x) * nextScale / previousScale);
    networkViewport.y = point.y - ((point.y - networkViewport.y) * nextScale / previousScale);
    networkViewport.scale = nextScale;
    updateNetworkViewport();
  }, { passive: false });

  networkCanvas.addEventListener("pointerdown", (event) => {
    if (!networkGraph || event.button !== 0) return;
    const nodeElement = event.target.closest(".network-node");
    if (!nodeElement && event.target.closest(".network-edge")) return;
    const point = nodeElement ? graphPositionFromEvent(event) : graphPointFromEvent(event);
    const memberId = Number(nodeElement?.dataset.memberId);
    const isCenter = nodeElement && memberId === Number(networkGraph.centerMemberId);
    networkPointerState = nodeElement && !isCenter
      ? {
        kind: "node", memberId, point,
        startClientX: event.clientX, startClientY: event.clientY,
        moved: false,
      }
      : nodeElement
        ? {
          kind: "center", memberId, point,
          startClientX: event.clientX, startClientY: event.clientY,
          moved: false,
        }
      : {
        kind: "pan", point, startX: networkViewport.x, startY: networkViewport.y,
        startClientX: event.clientX, startClientY: event.clientY,
        moved: false,
    };
    event.preventDefault();
    if (networkPointerState.kind === "node") document.body.classList.add("is-network-dragging");
    networkCanvas.setPointerCapture(event.pointerId);
    networkCanvas.classList.toggle("is-dragging-node", networkPointerState.kind === "node");
    networkCanvas.classList.toggle("is-panning", networkPointerState.kind === "pan");
  });

  networkCanvas.addEventListener("pointermove", (event) => {
    if (!networkPointerState) return;
    const point = networkPointerState.kind === "node" || networkPointerState.kind === "center"
      ? graphPositionFromEvent(event) : graphPointFromEvent(event);
    if (screenDistance(networkPointerState, event) > NETWORK_DRAG_THRESHOLD_PX) {
      networkPointerState.moved = true;
    }
    if (networkPointerState.moved) event.preventDefault();
    if (networkPointerState.kind === "node") {
      if (!networkPointerState.moved) return;
      const position = networkGraph.positions.get(networkPointerState.memberId);
      position.x = Math.min(NETWORK_WIDTH - 42, Math.max(42, point.x));
      position.y = Math.min(NETWORK_HEIGHT - 42, Math.max(42, point.y));
      updateNodeGeometry(networkPointerState.memberId);
      return;
    }
    if (networkPointerState.kind === "pan" && networkPointerState.moved) {
      networkViewport.x = networkPointerState.startX + point.x - networkPointerState.point.x;
      networkViewport.y = networkPointerState.startY + point.y - networkPointerState.point.y;
      updateNetworkViewport();
    }
  });

  networkCanvas.addEventListener("pointerup", (event) => {
    if (!networkPointerState) return;
    const pointerState = networkPointerState;
    if ((pointerState.kind === "node" || pointerState.kind === "center") && !pointerState.moved) {
      const node = networkGraph.nodes.find((item) => Number(item.member_id) === pointerState.memberId);
      suppressNetworkNodeClickUntil = Date.now() + 250;
      if (node) openMember(node);
    } else if (pointerState.kind === "node" && pointerState.moved) {
      suppressNetworkNodeClickUntil = Date.now() + 250;
    }
    networkPointerState = null;
    document.body.classList.remove("is-network-dragging");
    networkCanvas.classList.remove("is-dragging-node", "is-panning");
    if (networkCanvas.hasPointerCapture(event.pointerId)) networkCanvas.releasePointerCapture(event.pointerId);
  });

  networkCanvas.addEventListener("pointercancel", () => {
    networkPointerState = null;
    document.body.classList.remove("is-network-dragging");
    networkCanvas.classList.remove("is-dragging-node", "is-panning");
  });
}

function renderNetwork(network) {
  const nodes = Array.isArray(network.nodes) ? network.nodes : [];
  const aggregates = Array.isArray(network.edges) ? network.edges : [];
  const layoutSnapshot = networkLayoutSnapshot?.key === networkContextKey()
    ? networkLayoutSnapshot : null;
  networkCanvas.replaceChildren();
  networkGraph = null;
  hideNetworkTooltip();
  resetNetworkViewport();
  networkLowRelevanceVisible = false;
  networkEmpty.hidden = nodes.length > 0;
  networkExpandButton.hidden = !(network.has_more_nodes || network.has_more_edges) || networkExpanded;
  networkStatus.textContent = nodes.length
    ? `显示 ${nodes.length} 个成员、正在分析关系语义${network.has_more_nodes || network.has_more_edges ? "；可展开更多" : ""}。`
    : "该范围内暂无带明确目标成员的关系事件。";
  if (!nodes.length) return;

  const defs = svgElement("defs");
  const grid = svgElement("pattern", { id: "relation-grid", width: 32, height: 32, patternUnits: "userSpaceOnUse" });
  grid.append(svgElement("path", { d: "M 32 0 L 0 0 0 32", class: "network-grid-line" }));
  const glow = svgElement("filter", { id: "node-glow", x: "-80%", y: "-80%", width: "260%", height: "260%" });
  glow.append(svgElement("feGaussianBlur", { stdDeviation: 5, result: "blur" }));
  glow.append(svgElement("feMerge", {}));
  glow.lastElementChild.append(svgElement("feMergeNode", { in: "blur" }));
  glow.lastElementChild.append(svgElement("feMergeNode", { in: "SourceGraphic" }));
  const marker = svgElement("marker", { id: "relation-arrow", viewBox: "0 0 10 10", refX: 8, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse" });
  marker.append(svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", class: "network-arrow" }));
  defs.append(grid, glow, marker);
  networkCanvas.append(defs);
  const pairs = buildRelationshipPairs(aggregates, nodes);
  const levels = deriveNetworkLevels(nodes, pairs, network.center_member_id);
  const positions = nodePositions(nodes, network.center_member_id, levels, pairs);
  const directMembers = rankDirectNetworkMembers(pairs, network.center_member_id);
  const directMemberIds = new Set(directMembers.map((item) => Number(item.member_id)));
  const defaultDirectCapacity = Math.max(0, Number(network.node_limit || 30) - 1);
  const collapsedDirectMemberIds = layoutSnapshot
    ? new Set([...layoutSnapshot.directMemberIds].filter((memberId) => directMemberIds.has(memberId)))
    : new Set(directMembers.slice(0, defaultDirectCapacity).map((item) => Number(item.member_id)));
  if (layoutSnapshot) {
    layoutSnapshot.positions.forEach((position, memberId) => {
      if (Number(memberId) === Number(network.center_member_id)
        || collapsedDirectMemberIds.has(Number(memberId))) {
        positions.set(Number(memberId), { ...position });
      }
    });
  }
  const background = svgElement("rect", { x: 0, y: 0, width: NETWORK_WIDTH, height: NETWORK_HEIGHT, class: "network-svg-background" });
  const viewport = svgElement("g", { class: "network-viewport" });
  const edgeLayer = svgElement("g", { class: "network-edge-layer" });
  const nodeLayer = svgElement("g", { class: "network-node-layer" });
  viewport.append(edgeLayer, nodeLayer);
  networkCanvas.append(background, viewport);
  networkGraph = {
    nodes, aggregates, pairs, levels, positions, viewport,
    centerMemberId: Number(network.center_member_id),
    directMemberIds, collapsedDirectMemberIds,
    nodeElements: new Map(), pairElements: new Map(),
  };

  pairs.forEach((pair) => {
    if (Number(pair.memberA.member_id) !== Number(network.center_member_id)
      && Number(pair.memberB.member_id) !== Number(network.center_member_id)) {
      pair.analysis = {
        ...pendingRelationshipSemantics(),
        reasons: ["两跳关系默认保守展示；请点击查看已有结构化证据。"],
      };
    }
  });

  pairs.forEach((pair) => {
    const from = positions.get(Number(pair.memberA.member_id));
    const to = positions.get(Number(pair.memberB.member_id));
    if (!from || !to) return;
    const group = svgElement("g", { class: `network-edge ${semanticClass(pair.analysis.semantic)}`, tabindex: 0, role: "button", "data-edge-id": pair.id });
    const width = Math.min(9, 1.8 + Math.sqrt(Number(pair.weight || 1)) * 1.35);
    const color = semanticColor(pair.analysis.semantic);
    group.append(svgElement("line", {
      x1: from.x, y1: from.y, x2: to.x, y2: to.y,
      "stroke-width": width, stroke: color,
    }));
    const label = svgElement("text", { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 - 9, class: "network-edge-label", fill: color });
    label.textContent = pair.analysis.label;
    group.append(label);
    group.addEventListener("click", () => openRelationshipPair(pair));
    group.addEventListener("mouseenter", (event) => {
      setNetworkFocus(null, pair.id);
      setNetworkTooltip(pairTooltip(pair), event);
    });
    group.addEventListener("mousemove", positionNetworkTooltip);
    group.addEventListener("mouseleave", () => { clearNetworkFocus(); hideNetworkTooltip(); });
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openRelationshipPair(pair); }
    });
    edgeLayer.append(group);
    networkGraph.pairElements.set(pair.id, group);
  });

  nodes.forEach((node) => {
    const position = positions.get(Number(node.member_id));
    if (!position) return;
    const isCenter = Number(node.member_id) === Number(network.center_member_id);
    const level = networkLevelForMember(levels, node.member_id);
    const group = svgElement("g", {
      class: `network-node ${isCenter ? "center" : ""} level-${level} ${node.member_status === "mentioned_only" ? "mentioned-only" : ""}`,
      tabindex: 0, role: "button", "data-member-id": Number(node.member_id),
    });
    if (isCenter) group.append(svgElement("circle", { cx: position.x, cy: position.y, r: 51, class: "network-node-halo" }));
    group.append(svgElement("circle", { cx: position.x, cy: position.y, r: isCenter ? 37 : 29, class: "network-node-core" }));
    const label = svgElement("text", { x: position.x, y: position.y + 5, class: "network-node-label" });
    label.textContent = String(node.label).slice(0, 8);
    group.append(label);
    group.addEventListener("click", () => {
      if (Date.now() < suppressNetworkNodeClickUntil) return;
    });
    group.addEventListener("mouseenter", (event) => {
      setNetworkFocus(node.member_id);
      setNetworkTooltip(nodeTooltip(node), event);
    });
    group.addEventListener("mousemove", positionNetworkTooltip);
    group.addEventListener("mouseleave", () => { clearNetworkFocus(); hideNetworkTooltip(); });
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openMember(node); }
    });
    nodeLayer.append(group);
    networkGraph.nodeElements.set(Number(node.member_id), group);
  });
  applyNetworkVisibility();
  analyzeRelationshipPairs(networkGraph);
}

function updatePairPresentation(pair) {
  if (!networkGraph) return;
  const element = networkGraph.pairElements.get(pair.id);
  if (!element) return;
  element.className.baseVal = `network-edge ${semanticClass(pair.analysis.semantic)}`;
  const color = semanticColor(pair.analysis.semantic);
  const line = element.querySelector("line");
  const label = element.querySelector("text");
  line.setAttribute("stroke", color);
  label.setAttribute("fill", color);
  label.textContent = pair.analysis.label;
}

function relationshipSummaryFields(pair) {
  const analysis = pair.analysis || pendingRelationshipSemantics();
  return [
    ["关系", `${memberDisplayName(pair.memberA)} ↔ ${memberDisplayName(pair.memberB)}`],
    ["当前判断", analysis.label],
    ["双向互动", analysis.is_bidirectional ? "是" : "否"],
    ["近 90 天证据", `${analysis.evidence_count || 0} 条（${analysis.directional_counts?.aToB || 0}/${analysis.directional_counts?.bToA || 0}）`],
    ["最近互动", formatTimestamp(analysis.recent_timestamp)],
    ["关键理由", (analysis.reasons || ["正在读取近 90 天结构化证据。"]).join("\n")],
    ["转述辅助", analysis.reported_count ? `${analysis.reported_count} 条，仅作参考` : "暂无"],
  ];
}

function renderPairSummary(pair) {
  relationshipSummary.replaceChildren();
  relationshipSummaryFields(pair).forEach(([label, value]) => {
    const item = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = value;
    item.append(term, detail);
    relationshipSummary.append(item);
  });
}

function renderPairEvidenceLinks(pair) {
  relationshipEvidenceList.replaceChildren();
  const heading = recordRow({
    title: "按方向查看原始证据",
    meta: "选择一项聚合后，将继续使用现有证据分页接口。",
  });
  relationshipEvidenceList.append(heading);
  pair.aggregates.forEach((aggregate) => {
    const row = recordRow({
      title: `${eventTypeLabel(aggregate.event_type)} · ${aggregateLabel(aggregate)}`,
      meta: `来源：${sourceCountsLabel(aggregate.source_counts)}；最近：${formatTimestamp(aggregate.last_time)}；x${aggregate.count}`,
    });
    row.classList.add("interactive-record");
    row.tabIndex = 0;
    row.addEventListener("click", () => openAggregate(aggregate));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openAggregate(aggregate);
      }
    });
    relationshipEvidenceList.append(row);
  });
  relationshipMoreButton.hidden = true;
}

function openRelationshipPair(pair) {
  activeAggregate = null;
  activeAggregateIdentity = networkCenter || selectedMember;
  evidenceCursor = null;
  relationshipSummary.dataset.pairId = pair.id;
  renderPairSummary(pair);
  renderPairEvidenceLinks(pair);
  if (!relationshipDialog.open) relationshipDialog.showModal();
}

async function mapConcurrent(items, limit, operation) {
  if (!items.length) return [];
  const results = new Array(items.length);
  let cursor = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      results[index] = await operation(items[index]);
    }
  });
  await Promise.all(workers);
  return results;
}

async function loadAggregateWindowEvents(aggregate, identity, cutoffTimestamp) {
  const events = [];
  let cursor = null;
  let completed = false;
  while (!completed) {
    const parameters = {
      platform_id: identity.platform_id,
      group_id: identity.group_id,
      source_member_id: aggregate.source_member_id,
      event_type: aggregate.event_type,
    };
    if (aggregate.target_member_id !== null && aggregate.target_member_id !== undefined) {
      parameters.target_member_id = aggregate.target_member_id;
    }
    if (cursor) {
      parameters.before_timestamp = cursor.before_timestamp;
      parameters.before_id = cursor.before_id;
    }
    const result = await bridge.apiGet("relationship-aggregate-events", parameters);
    const page = Array.isArray(result.events) ? result.events : [];
    events.push(...page.filter((event) => Number(event.event_timestamp || 0) >= cutoffTimestamp));
    const oldestTimestamp = page.length
      ? Math.min(...page.map((event) => Number(event.event_timestamp || 0))) : 0;
    cursor = result.next_cursor || null;
    completed = !cursor || !page.length || oldestTimestamp < cutoffTimestamp;
  }
  return { ...aggregate, events };
}

async function analyzeRelationshipPairs(graph) {
  const identity = networkCenter;
  if (!identity || graph !== networkGraph) return;
  const nowSeconds = Math.floor(Date.now() / 1000);
  const cutoffTimestamp = nowSeconds - RELATIONSHIP_WINDOW_SECONDS;
  try {
    const centerPairs = graph.pairs.filter((pair) => pairIncludesMember(pair, graph.centerMemberId));
    await mapConcurrent(centerPairs, 1, async (pair) => {
      const directionalEvents = await mapConcurrent(pair.aggregates, 3,
        (aggregate) => loadAggregateWindowEvents(aggregate, identity, cutoffTimestamp));
      if (graph !== networkGraph) return;
      pair.analysis = deriveRelationshipSemantics({
        memberA: pair.memberA,
        memberB: pair.memberB,
        directionalEvents,
        nowSeconds,
      });
      updatePairPresentation(pair);
      if (!relationshipDialog.open) return;
      const visiblePair = relationshipSummary.dataset.pairId;
      if (visiblePair === pair.id) {
        renderPairSummary(pair);
        renderPairEvidenceLinks(pair);
      }
    });
    if (graph === networkGraph) {
      networkStatus.textContent = `显示 ${graph.nodes.length} 个成员、${graph.pairs.length} 条成员对关系；中心成员的一跳关系已完成近 90 天语义分析。`;
    }
  } catch (error) {
    if (graph === networkGraph) {
      networkStatus.textContent = `关系网已显示，但部分语义分析失败：${error.message || "请稍后刷新"}`;
    }
  }
}

function renderAggregateSummary(aggregate) {
  relationshipSummary.replaceChildren();
  const fields = [
    ["关系", `${aggregate.source?.nickname || aggregate.source?.user_id || "未知成员"} → ${aggregate.target?.nickname || aggregate.target?.user_id || "无目标成员"}`],
    ["类型", eventTypeLabel(aggregate.event_type)],
    ["数量", `x${aggregate.count}`],
    ["首次", formatTimestamp(aggregate.first_time)],
    ["最近", formatTimestamp(aggregate.last_time)],
    ["来源", sourceCountsLabel(aggregate.source_counts)],
    ["最后证据", text(aggregate.last_evidence, "暂无")],
  ];
  fields.forEach(([label, value]) => {
    const item = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = value;
    item.append(term, detail);
    relationshipSummary.append(item);
  });
}

async function loadAggregateEvidence(append = false) {
  if (!activeAggregate || !activeAggregateIdentity) return;
  relationshipMoreButton.disabled = true;
  try {
    const cursor = append ? evidenceCursor : null;
    const parameters = {
      platform_id: activeAggregateIdentity.platform_id,
      group_id: activeAggregateIdentity.group_id,
      source_member_id: activeAggregate.source_member_id,
      event_type: activeAggregate.event_type,
    };
    if (activeAggregate.target_member_id !== null && activeAggregate.target_member_id !== undefined) {
      parameters.target_member_id = activeAggregate.target_member_id;
    }
    if (cursor) {
      parameters.before_timestamp = cursor.before_timestamp;
      parameters.before_id = cursor.before_id;
    }
    const result = await bridge.apiGet("relationship-aggregate-events", parameters);
    if (!append) relationshipEvidenceList.replaceChildren();
    const events = Array.isArray(result.events) ? result.events : [];
    events.forEach((event) => relationshipEvidenceList.append(recordRow({
      title: `${eventTypeLabel(event.event_type)} · ${event.source_nickname || event.source_user_id} → ${event.target_nickname || event.target_user_id || "无目标成员"}`,
      meta: `来源：${eventSourceLabel(event.source_type)}；时间：${formatTimestamp(event.event_timestamp)}；置信度：${Math.round(Number(event.confidence || 0) * 100)}%；证据：${event.content}`,
    })));
    if (!events.length && !append) relationshipEvidenceList.append(recordRow({ title: "暂无可读取的原始证据" }));
    evidenceCursor = result.next_cursor || null;
    relationshipMoreButton.hidden = !evidenceCursor;
  } catch (error) {
    if (!append) relationshipEvidenceList.replaceChildren(recordRow({ title: "读取原始证据失败", meta: error.message || "请稍后重试" }));
  } finally {
    relationshipMoreButton.disabled = false;
  }
}

async function openAggregate(aggregate) {
  activeAggregate = aggregate;
  activeAggregateIdentity = networkCenter || selectedMember;
  evidenceCursor = null;
  delete relationshipSummary.dataset.pairId;
  renderAggregateSummary(aggregate);
  if (!relationshipDialog.open) relationshipDialog.showModal();
  await loadAggregateEvidence();
}

function syncMember(member) {
  selectedMember = member;
  const index = members.findIndex((item) => sameMember(item, member));
  const listMember = { ...member, tags: tagsFor(member).join(", ") };
  if (index === -1) members = [listMember, ...members];
  else members[index] = { ...members[index], ...listMember };
  render();
  renderDetail(member);
}

async function requestMemberDetail(member) {
  return bridge.apiGet("member", memberIdentity(member));
}

async function openMember(member) {
  selectedMember = member;
  renderDetail(member);
  if (!dialog.open) dialog.showModal();
  setDialogBusy(true, "正在读取成员详情…");
  try {
    const result = await requestMemberDetail(member);
    syncMember(result.member);
    detailStatus.textContent = "";
  } catch (error) {
    detailStatus.textContent = error.message || "读取成员详情失败";
  } finally {
    setDialogBusy(false, detailStatus.textContent);
  }
}

async function refreshSelectedMember(successMessage = "") {
  if (!selectedMember) return;
  const result = await requestMemberDetail(selectedMember);
  syncMember(result.member);
  detailStatus.textContent = successMessage;
}

async function runMutation(message, operation, successMessage) {
  if (!selectedMember) return;
  setDialogBusy(true, message);
  try {
    await operation();
    await refreshSelectedMember(successMessage);
  } catch (error) {
    detailStatus.textContent = error.message || "保存失败";
  } finally {
    setDialogBusy(false, detailStatus.textContent);
  }
}

function readConfidence(input) {
  const value = Number(input.value);
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    throw new Error("置信度必须在 0 到 1 之间");
  }
  return value;
}

async function saveNote() {
  const content = noteInput.value.trim();
  if (!content) return void (detailStatus.textContent = "备注不能为空");
  await runMutation("正在保存备注…", () => bridge.apiPost("member/note", {
    ...memberIdentity(selectedMember), content,
  }), "备注已保存");
}

async function addTag() {
  const tagName = tagInput.value.trim();
  if (!tagName) return void (detailStatus.textContent = "请输入标签");
  await runMutation("正在添加标签…", async () => {
    await bridge.apiPost("member/tags/add", { ...memberIdentity(selectedMember), tag_name: tagName });
    tagInput.value = "";
  }, "标签已添加");
}

async function removeTag(tagName) {
  await runMutation("正在删除标签…", () => bridge.apiPost("member/tags/remove", {
    ...memberIdentity(selectedMember), tag_name: tagName,
  }), "标签已删除");
}

async function addAlias() {
  const alias = aliasInput.value.trim();
  if (!alias) return void (detailStatus.textContent = "请输入别名");
  await runMutation("正在添加别名…", async () => {
    await bridge.apiPost("member/aliases/add", {
      ...memberIdentity(selectedMember), alias, alias_type: aliasTypeInput.value, confidence: 1,
    });
    aliasInput.value = "";
  }, "别名已添加");
}

async function removeAlias(aliasId) {
  await runMutation("正在删除别名…", () => bridge.apiPost("member/aliases/remove", {
    ...memberIdentity(selectedMember), alias_id: aliasId,
  }), "别名已删除");
}

async function mergeMember() {
  const targetUserId = mergeTargetInput.value.trim();
  if (!targetUserId) return void (detailStatus.textContent = "请输入目标成员 QQ 号");
  if (!window.confirm("合并后来源身份会重定向到目标身份，历史消息不会删除。确认继续？")) return;
  setDialogBusy(true, "正在合并成员身份…");
  try {
    await bridge.apiPost("member/merge", {
      ...memberIdentity(selectedMember), target_user_id: targetUserId, reason: mergeReasonInput.value.trim(),
    });
    mergeTargetInput.value = "";
    mergeReasonInput.value = "";
    await loadMembers();
    await refreshSelectedMember("身份已合并，历史消息已归入目标身份");
  } catch (error) {
    detailStatus.textContent = error.message || "合并成员身份失败";
  } finally {
    setDialogBusy(false, detailStatus.textContent);
  }
}

async function addLayeredTag() {
  const tagName = layeredTagInput.value.trim();
  if (!tagName) return void (detailStatus.textContent = "请输入分层标签");
  let confidence;
  try { confidence = readConfidence(tagConfidenceInput); }
  catch (error) { detailStatus.textContent = error.message; return; }
  await runMutation("正在添加分层标签…", async () => {
    await bridge.apiPost("member/layered-tags/add", {
      ...memberIdentity(selectedMember), tag_name: tagName, layer: tagLayerInput.value,
      confidence, source_type: "manual",
    });
    layeredTagInput.value = "";
  }, "分层标签已保存");
}

async function removeLayeredTag(tagId) {
  await runMutation("正在删除分层标签…", () => bridge.apiPost("member/layered-tags/remove", {
    ...memberIdentity(selectedMember), tag_id: tagId,
  }), "分层标签已删除");
}

async function addRelationshipEvent() {
  const content = eventContentInput.value.trim();
  if (!content) return void (detailStatus.textContent = "请输入事件内容");
  let confidence;
  try { confidence = readConfidence(eventConfidenceInput); }
  catch (error) { detailStatus.textContent = error.message; return; }
  await runMutation("正在记录关系事件…", async () => {
    await bridge.apiPost("relationship-events", {
      ...memberIdentity(selectedMember), target_user_id: eventTargetInput.value.trim(),
      event_type: eventTypeInput.value, content, confidence, source_type: "manual",
    });
    eventTargetInput.value = "";
    eventContentInput.value = "";
  }, "关系事件已记录");
  networkData = null;
  if (!networkView.hidden && networkCenter) loadNetwork();
}

async function loadMembers() {
  refreshButton.disabled = true;
  summary.textContent = "正在刷新成员数据…";
  try {
    const result = await bridge.apiGet("members");
    members = Array.isArray(result.members) ? result.members : [];
    render();
  } catch (error) {
    members = [];
    table.hidden = true;
    emptyState.hidden = false;
    summary.textContent = error.message || "读取成员数据失败";
  } finally {
    refreshButton.disabled = false;
  }
}

await bridge.ready();
refreshButton.addEventListener("click", loadMembers);
searchInput.addEventListener("input", render);
membersViewButton.addEventListener("click", () => setView("members"));
networkViewButton.addEventListener("click", () => setView("network"));
openNetworkButton.addEventListener("click", () => {
  if (selectedMember) chooseNetworkCenter(selectedMember);
});
networkCenterInput.addEventListener("input", renderCenterResults);
networkCenterInput.addEventListener("focus", renderCenterResults);
networkLoadButton.addEventListener("click", () => {
  networkExpanded = false;
  loadNetwork();
});
networkExpandButton.addEventListener("click", () => {
  captureNetworkLayoutSnapshot();
  networkExpanded = true;
  loadNetwork();
});
networkLowRelevanceButton.addEventListener("click", () => {
  networkLowRelevanceVisible = !networkLowRelevanceVisible;
  applyNetworkVisibility();
});
networkResetViewButton.addEventListener("click", resetNetworkView);
function reloadNetworkForNewContext() {
  networkExpanded = false;
  networkLayoutSnapshot = null;
  loadNetwork();
}
networkScopeInput.addEventListener("change", reloadNetworkForNewContext);
networkTypeInput.addEventListener("change", reloadNetworkForNewContext);
networkSourceInput.addEventListener("change", reloadNetworkForNewContext);
relationshipClose.addEventListener("click", () => relationshipDialog.close());
relationshipMoreButton.addEventListener("click", () => loadAggregateEvidence(true));
dialogClose.addEventListener("click", () => dialog.close());
saveNoteButton.addEventListener("click", saveNote);
addTagButton.addEventListener("click", addTag);
addAliasButton.addEventListener("click", addAlias);
mergeMemberButton.addEventListener("click", mergeMember);
addLayeredTagButton.addEventListener("click", addLayeredTag);
addEventButton.addEventListener("click", addRelationshipEvent);
tagInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") { event.preventDefault(); addTag(); }
});
aliasInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") { event.preventDefault(); addAlias(); }
});
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});
relationshipDialog.addEventListener("click", (event) => {
  if (event.target === relationshipDialog) relationshipDialog.close();
});
addNetworkPointerInteractions();
loadMembers();
