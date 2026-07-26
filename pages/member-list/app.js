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
const networkStatus = document.getElementById("network-status");
const networkCanvas = document.getElementById("network-canvas");
const networkEmpty = document.getElementById("network-empty");
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
let activeAggregate = null;
let activeAggregateIdentity = null;
let evidenceCursor = null;

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
  aggregates.forEach((aggregate) => {
    const row = recordRow({
      title: `${eventTypeLabel(aggregate.event_type)} · ${aggregateLabel(aggregate)}`,
      meta: `来源：${sourceCountsLabel(aggregate.source_counts)}；首次：${formatTimestamp(aggregate.first_time)}；最近：${formatTimestamp(aggregate.last_time)}；最后证据：${text(aggregate.last_evidence, "暂无")}`,
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
    relationshipEventList.append(row);
  });
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
  detailUserId.textContent = member.user_id || member.external_user_id || "-";
  detailNickname.textContent = member.nickname || "未获取昵称";
  detailMemberStatus.textContent = memberStatusLabel(member.member_status);
  detailGroup.textContent = groupLabel(member);
  detailMessageCount.textContent = String(member.message_count || 0);
  detailLastMessage.textContent = formatTimestamp(member.last_message_timestamp);
  detailProfile.textContent = member.summary || "暂无";
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
  networkCenter = { ...memberIdentity(member), member_id: Number(member.member_id || 0) };
  networkCenterInput.value = member.nickname || member.user_id || member.external_user_id || "";
  networkData = null;
  networkExpanded = false;
  networkCenterResults.hidden = true;
  setView("network");
  loadNetwork();
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
    return;
  }
  networkLoadButton.disabled = true;
  networkStatus.textContent = "正在加载关系网…";
  try {
    const parameters = {
      ...networkCenter,
      scope: networkScopeInput.value,
      node_limit: networkExpanded ? 100 : 30,
      edge_limit: networkExpanded ? 200 : 50,
    };
    if (networkTypeInput.value) parameters.event_type = networkTypeInput.value;
    if (networkSourceInput.value) parameters.source_type = networkSourceInput.value;
    networkData = await bridge.apiGet("relationship-network", parameters);
    renderNetwork(networkData);
  } catch (error) {
    networkData = null;
    networkCanvas.replaceChildren();
    networkEmpty.hidden = false;
    networkStatus.textContent = error.message || "读取关系网失败";
  } finally {
    networkLoadButton.disabled = false;
  }
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
  return element;
}

function nodePositions(nodes, centerMemberId) {
  const width = 980;
  const height = 620;
  const center = nodes.find((node) => Number(node.member_id) === Number(centerMemberId));
  const positions = new Map();
  if (center) positions.set(Number(center.member_id), { x: width / 2, y: height / 2 });
  const others = nodes.filter((node) => Number(node.member_id) !== Number(centerMemberId));
  others.forEach((node, index) => {
    const angle = (-Math.PI / 2) + ((Math.PI * 2 * index) / Math.max(others.length, 1));
    const radius = Math.min(225, 95 + others.length * 7);
    positions.set(Number(node.member_id), {
      x: width / 2 + Math.cos(angle) * radius,
      y: height / 2 + Math.sin(angle) * radius,
    });
  });
  return positions;
}

function renderNetwork(network) {
  const nodes = Array.isArray(network.nodes) ? network.nodes : [];
  const edges = Array.isArray(network.edges) ? network.edges : [];
  networkCanvas.replaceChildren();
  networkEmpty.hidden = nodes.length > 0;
  networkExpandButton.hidden = !(network.has_more_nodes || network.has_more_edges) || networkExpanded;
  networkStatus.textContent = nodes.length
    ? `显示 ${nodes.length} 个成员、${edges.length} 条聚合关系${network.has_more_nodes || network.has_more_edges ? "；可展开更多" : ""}。`
    : "该范围内暂无带明确目标成员的关系事件。";
  if (!nodes.length) return;

  const defs = svgElement("defs");
  const marker = svgElement("marker", { id: "relation-arrow", viewBox: "0 0 10 10", refX: 8, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse" });
  marker.append(svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", class: "network-arrow" }));
  defs.append(marker);
  networkCanvas.append(defs);
  const positions = nodePositions(nodes, network.center_member_id);

  edges.forEach((edge) => {
    const from = positions.get(Number(edge.source_member_id));
    const to = positions.get(Number(edge.target_member_id));
    if (!from || !to) return;
    const group = svgElement("g", { class: "network-edge", tabindex: 0, role: "button" });
    const width = Math.min(8, 1.5 + Math.sqrt(Number(edge.count || 1)));
    group.append(svgElement("line", {
      x1: from.x, y1: from.y, x2: to.x, y2: to.y,
      "stroke-width": width, "marker-end": "url(#relation-arrow)",
    }));
    const label = svgElement("text", { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 - 7, class: "network-edge-label" });
    label.textContent = `${eventTypeLabel(edge.event_type)} x${edge.count}`;
    group.append(label);
    group.addEventListener("click", () => openAggregate(edge));
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openAggregate(edge); }
    });
    networkCanvas.append(group);
  });

  nodes.forEach((node) => {
    const position = positions.get(Number(node.member_id));
    if (!position) return;
    const group = svgElement("g", {
      class: `network-node ${Number(node.member_id) === Number(network.center_member_id) ? "center" : ""} ${node.member_status === "mentioned_only" ? "mentioned-only" : ""}`,
      tabindex: 0, role: "button",
    });
    group.append(svgElement("circle", { cx: position.x, cy: position.y, r: Number(node.member_id) === Number(network.center_member_id) ? 36 : 28 }));
    const label = svgElement("text", { x: position.x, y: position.y + 5, class: "network-node-label" });
    label.textContent = String(node.label).slice(0, 8);
    group.append(label);
    group.addEventListener("click", () => openMember(node));
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openMember(node); }
    });
    networkCanvas.append(group);
  });
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
  networkExpanded = true;
  loadNetwork();
});
networkScopeInput.addEventListener("change", () => { networkExpanded = false; loadNetwork(); });
networkTypeInput.addEventListener("change", () => { networkExpanded = false; loadNetwork(); });
networkSourceInput.addEventListener("change", () => { networkExpanded = false; loadNetwork(); });
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
loadMembers();
