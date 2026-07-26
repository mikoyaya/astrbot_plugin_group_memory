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
let activeAggregate = null;
let activeAggregateIdentity = null;
let evidenceCursor = null;
let networkGraph = null;
let networkViewport = { scale: 1, x: 0, y: 0 };
let networkPointerState = null;
let suppressNetworkNodeClickUntil = 0;

const NETWORK_WIDTH = 980;
const NETWORK_HEIGHT = 620;
const NETWORK_MIN_SCALE = 0.55;
const NETWORK_MAX_SCALE = 2.4;

function text(value, fallback = "") {
  return value === undefined || value === null ? fallback : String(value);
}

function formatTimestamp(timestamp) {
  if (!timestamp) return "??";
  const date = new Date(Number(timestamp) * 1000);
  if (Number.isNaN(date.getTime())) return "??";
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
  return text(status) === "mentioned_only" ? "????" : "????";
}

function eventTypeLabel(eventType) {
  const labels = {
    mention: "??", evaluation: "??", praise: "??",
    complaint: "??", reported: "??/??", confirmation: "????",
  };
  return labels[text(eventType)] || text(eventType, "????");
}

function eventSourceLabel(sourceType) {
  const labels = { observed: "?????", manual: "????", reported: "????" };
  return labels[text(sourceType)] || text(sourceType, "????");
}

function aggregateLabel(aggregate) {
  const source = aggregate.source?.nickname || aggregate.source?.user_id || "????";
  const target = aggregate.target?.nickname || aggregate.target?.user_id || "?????";
  return `${source} ? ${target} x${aggregate.count}`;
}

function sourceCountsLabel(sourceCounts) {
  const entries = Object.entries(sourceCounts || {});
  if (!entries.length) return "????";
  return entries.map(([source, count]) => `${eventSourceLabel(source)} ${count}`).join("?");
}

function sameMember(left, right) {
  const leftId = memberIdentity(left);
  const rightId = memberIdentity(right);
  return leftId.platform_id === rightId.platform_id
    && leftId.group_id === rightId.group_id
    && leftId.user_id === rightId.user_id;
}

function groupLabel(member) {
  const groupId = member.group_id || member.external_group_id || "????";
  return member.group_name ? `${member.group_name} (${groupId})` : `?? ${groupId}`;
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
  name.textContent = member.group_name || "????";
  const id = document.createElement("span");
  id.textContent = `?? ${member.group_id || member.external_group_id || "??"}`;
  cell.append(name, id);
  return cell;
}

function createMemberCell(member) {
  const cell = document.createElement("td");
  const button = document.createElement("button");
  button.className = "member-link";
  button.type = "button";
  button.title = `?? ${member.nickname || member.user_id || member.external_user_id} ???`;
  const name = document.createElement("strong");
  name.textContent = member.nickname || `?? ${member.user_id || member.external_user_id}`;
  const id = document.createElement("span");
  id.textContent = `QQ ${member.user_id || member.external_user_id || "??"}`;
  button.append(name);
  if (text(member.member_status) === "mentioned_only") {
    const badge = document.createElement("span");
    badge.className = "member-status-badge mentioned-only";
    badge.textContent = "????";
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
      createTextCell(tagsFor(member).join("?") || "??", "tag-cell"),
      createTextCell(member.note || "??", "note-cell"),
    );
    body.append(row);
  }
  table.hidden = filtered.length === 0;
  emptyState.hidden = filtered.length !== 0;
  summary.textContent = members.length === 0
    ? "???????" : `?? ${filtered.length} / ${members.length} ???`;
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
    remove.textContent = "?";
    remove.addEventListener("click", onRemove);
    row.append(remove);
  }
  return row;
}

function renderAliases(member) {
  aliasList.replaceChildren();
  const aliases = Array.isArray(member.aliases) ? member.aliases : [];
  if (!aliases.length) {
    aliasList.append(recordRow({ title: "????", meta: "???????????" }));
    return;
  }
  aliases.forEach((alias) => aliasList.append(recordRow({
    title: alias.alias,
    meta: `${alias.alias_type} ? ${Math.round(Number(alias.confidence || 0) * 100)}% ? ${alias.source_type}`,
    removeTitle: `???? ${alias.alias}`,
    onRemove: () => removeAlias(alias.id),
  })));
}

function renderLayeredTags(member) {
  layeredTagList.replaceChildren();
  const tags = Array.isArray(member.layered_tags) ? member.layered_tags : [];
  if (!tags.length) {
    layeredTagList.append(recordRow({ title: "??????", meta: "???????????????" }));
    return;
  }
  tags.forEach((tag) => layeredTagList.append(recordRow({
    title: tag.name,
    meta: `${tag.layer} ? ${Math.round(Number(tag.confidence || 0) * 100)}% ? ${tag.source_type}`,
    removeTitle: `???? ${tag.name}`,
    onRemove: tag.id ? () => removeLayeredTag(tag.id) : null,
  })));
}

function eventLabel(event) {
  const source = event.source_nickname || event.source_user_id || "????";
  const target = event.target_nickname || event.target_user_id || "?????";
  return `????${source}??????${target}`;
}

function renderEvents(member) {
  relationshipEventList.replaceChildren();
  const aggregates = Array.isArray(member.relationship_aggregates)
    ? member.relationship_aggregates : [];
  if (!aggregates.length) {
    relationshipEventList.append(recordRow({ title: "??????", meta: "??????????????? @??" }));
    return;
  }
  aggregates.forEach((aggregate) => {
    const row = recordRow({
      title: `${eventTypeLabel(aggregate.event_type)} ? ${aggregateLabel(aggregate)}`,
      meta: `???${sourceCountsLabel(aggregate.source_counts)}????${formatTimestamp(aggregate.first_time)}????${formatTimestamp(aggregate.last_time)}??????${text(aggregate.last_evidence, "??")}`,
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
    empty.textContent = "????";
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
    remove.title = `???? ${tagName}`;
    remove.setAttribute("aria-label", `???? ${tagName}`);
    remove.textContent = "?";
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
  detailNickname.textContent = member.nickname || "?????";
  detailMemberStatus.textContent = memberStatusLabel(member.member_status);
  detailGroup.textContent = groupLabel(member);
  detailMessageCount.textContent = String(member.message_count || 0);
  detailLastMessage.textContent = formatTimestamp(member.last_message_timestamp);
  detailProfile.textContent = member.summary || "??";
  detailNoteSummary.textContent = member.note || "??";
  detailTagsSummary.textContent = tagsFor(member).join("?") || "??";
  detailRelationshipCount.textContent = aggregates.length
    ? `${aggregates.length} ????? ? ${totalInteractions} ???`
    : "??";
  detailRecentInteraction.textContent = mostRecent
    ? `${eventTypeLabel(mostRecent.event_type)} ? ${aggregateLabel(mostRecent)} ? ${formatTimestamp(mostRecent.last_time)}${mostRecent.last_evidence ? ` ? ${text(mostRecent.last_evidence).slice(0, 48)}` : ""}`
    : "??";
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
    button.textContent = `${member.nickname || "?????"} ? QQ ${member.user_id || member.external_user_id}`;
    button.addEventListener("click", () => chooseNetworkCenter(member));
    networkCenterResults.append(button);
  });
  networkCenterResults.hidden = matches.length === 0;
}

async function loadNetwork() {
  if (!networkCenter) {
    networkStatus.textContent = "???????????????";
    networkEmpty.hidden = false;
    networkCanvas.replaceChildren();
    networkGraph = null;
    hideNetworkTooltip();
    return;
  }
  networkLoadButton.disabled = true;
  networkStatus.textContent = "????????";
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
    networkGraph = null;
    hideNetworkTooltip();
    networkEmpty.hidden = false;
    networkStatus.textContent = error.message || "???????";
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
  const width = NETWORK_WIDTH;
  const height = NETWORK_HEIGHT;
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

function relationshipColor(eventType) {
  const colors = {
    mention: "#57d1ff",
    evaluation: "#ab8cff",
    praise: "#ffd166",
    complaint: "#ff7a8a",
    reported: "#ffad66",
    confirmation: "#5ee6a8",
  };
  return colors[text(eventType)] || "#75dcc8";
}

function escapeSelectorValue(value) {
  return String(value).replace(/([\\"'\[\]#.:])/g, "\\$1");
}

function memberDisplayName(member) {
  return member?.label || member?.nickname || member?.user_id || member?.external_user_id || "?????";
}

function edgeMember(edge, role) {
  const member = edge?.[role];
  if (member && typeof member === "object") return member;
  const memberId = role === "source" ? edge?.source_member_id : edge?.target_member_id;
  return networkGraph?.nodes.find((node) => Number(node.member_id) === Number(memberId)) || null;
}

function memberRelationshipCount(memberId, edges) {
  return edges.filter((edge) => Number(edge.source_member_id) === Number(memberId)
    || Number(edge.target_member_id) === Number(memberId))
    .reduce((total, edge) => total + Number(edge.count || 0), 0);
}

function edgeTooltip(edge) {
  const source = edgeMember(edge, "source");
  const target = edgeMember(edge, "target");
  return [
    `${eventTypeLabel(edge.event_type)} ? x${edge.count || 0}`,
    `${memberDisplayName(source)} ? ${memberDisplayName(target)}`,
    `???${formatTimestamp(edge.last_time)}`,
    `???${sourceCountsLabel(edge.source_counts)}`,
  ].join("\n");
}

function nodeTooltip(node, edges) {
  const identity = node.user_id || node.external_user_id || "??";
  return [
    memberDisplayName(node),
    `QQ?${identity}`,
    `???${memberStatusLabel(node.member_status)}`,
    `?????${memberRelationshipCount(node.member_id, edges)} ?`,
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

function updateEdgeGeometry(edgeId) {
  if (!networkGraph) return;
  const edge = networkGraph.edges.find((item) => item.id === edgeId);
  if (!edge) return;
  const from = networkGraph.positions.get(Number(edge.source_member_id));
  const to = networkGraph.positions.get(Number(edge.target_member_id));
  const element = networkGraph.edgeElements.get(edgeId);
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
  networkGraph.edges.forEach((edge) => {
    if (Number(edge.source_member_id) === Number(memberId)
      || Number(edge.target_member_id) === Number(memberId)) {
      updateEdgeGeometry(edge.id);
    }
  });
}

function setNetworkFocus(memberId = null, edgeId = null) {
  if (!networkGraph) return;
  networkGraph.nodeElements.forEach((element, id) => {
    const connected = !memberId || Number(id) === Number(memberId)
      || networkGraph.edges.some((edge) => (Number(edge.source_member_id) === Number(memberId)
        || Number(edge.target_member_id) === Number(memberId))
        && (Number(edge.source_member_id) === Number(id) || Number(edge.target_member_id) === Number(id)));
    element.classList.toggle("is-dimmed", Boolean(memberId) && !connected);
    element.classList.toggle("is-highlighted", Boolean(memberId) && Number(id) === Number(memberId));
  });
  networkGraph.edgeElements.forEach((element, id) => {
    const edge = networkGraph.edges.find((item) => item.id === id);
    const connected = edgeId ? id === edgeId : !memberId
      || Number(edge.source_member_id) === Number(memberId)
      || Number(edge.target_member_id) === Number(memberId);
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
  networkGraph.edgeElements.forEach((element) => {
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
    networkPointerState = nodeElement
      ? { kind: "node", memberId: Number(nodeElement.dataset.memberId), point, moved: false }
      : { kind: "pan", point, startX: networkViewport.x, startY: networkViewport.y, moved: false };
    networkCanvas.setPointerCapture(event.pointerId);
    networkCanvas.classList.toggle("is-dragging-node", networkPointerState.kind === "node");
    networkCanvas.classList.toggle("is-panning", networkPointerState.kind === "pan");
  });

  networkCanvas.addEventListener("pointermove", (event) => {
    if (!networkPointerState) return;
    const point = networkPointerState.kind === "node"
      ? graphPositionFromEvent(event) : graphPointFromEvent(event);
    const movement = Math.hypot(point.x - networkPointerState.point.x, point.y - networkPointerState.point.y);
    if (movement > 3) networkPointerState.moved = true;
    if (networkPointerState.kind === "node") {
      const position = networkGraph.positions.get(networkPointerState.memberId);
      position.x = Math.min(NETWORK_WIDTH - 42, Math.max(42, point.x));
      position.y = Math.min(NETWORK_HEIGHT - 42, Math.max(42, point.y));
      updateNodeGeometry(networkPointerState.memberId);
      return;
    }
    networkViewport.x = networkPointerState.startX + point.x - networkPointerState.point.x;
    networkViewport.y = networkPointerState.startY + point.y - networkPointerState.point.y;
    updateNetworkViewport();
  });

  networkCanvas.addEventListener("pointerup", (event) => {
    if (!networkPointerState) return;
    if (networkPointerState.kind === "node" && networkPointerState.moved) {
      suppressNetworkNodeClickUntil = Date.now() + 180;
    }
    networkPointerState = null;
    networkCanvas.classList.remove("is-dragging-node", "is-panning");
    if (networkCanvas.hasPointerCapture(event.pointerId)) networkCanvas.releasePointerCapture(event.pointerId);
  });

  networkCanvas.addEventListener("pointercancel", () => {
    networkPointerState = null;
    networkCanvas.classList.remove("is-dragging-node", "is-panning");
  });
}

function renderNetwork(network) {
  const nodes = Array.isArray(network.nodes) ? network.nodes : [];
  const edges = Array.isArray(network.edges) ? network.edges : [];
  networkCanvas.replaceChildren();
  networkGraph = null;
  hideNetworkTooltip();
  resetNetworkViewport();
  networkEmpty.hidden = nodes.length > 0;
  networkExpandButton.hidden = !(network.has_more_nodes || network.has_more_edges) || networkExpanded;
  networkStatus.textContent = nodes.length
    ? `?? ${nodes.length} ????${edges.length} ?????${network.has_more_nodes || network.has_more_edges ? "??????" : ""}?`
    : "???????????????????";
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
  const positions = nodePositions(nodes, network.center_member_id);
  const background = svgElement("rect", { x: 0, y: 0, width: NETWORK_WIDTH, height: NETWORK_HEIGHT, class: "network-svg-background" });
  const viewport = svgElement("g", { class: "network-viewport" });
  const edgeLayer = svgElement("g", { class: "network-edge-layer" });
  const nodeLayer = svgElement("g", { class: "network-node-layer" });
  viewport.append(edgeLayer, nodeLayer);
  networkCanvas.append(background, viewport);
  networkGraph = {
    nodes, edges, positions, viewport,
    nodeElements: new Map(), edgeElements: new Map(),
  };

  edges.forEach((edge, index) => {
    const edgeId = `${edge.source_member_id}:${edge.target_member_id}:${edge.event_type}:${index}`;
    edge.id = edgeId;
    const from = positions.get(Number(edge.source_member_id));
    const to = positions.get(Number(edge.target_member_id));
    if (!from || !to) return;
    const group = svgElement("g", { class: "network-edge", tabindex: 0, role: "button", "data-edge-id": edgeId });
    const width = Math.min(9, 1.8 + Math.sqrt(Number(edge.count || 1)) * 1.35);
    const color = relationshipColor(edge.event_type);
    group.append(svgElement("line", {
      x1: from.x, y1: from.y, x2: to.x, y2: to.y,
      "stroke-width": width, stroke: color, "marker-end": "url(#relation-arrow)",
    }));
    const label = svgElement("text", { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 - 9, class: "network-edge-label", fill: color });
    label.textContent = `${eventTypeLabel(edge.event_type)} x${edge.count}`;
    group.append(label);
    group.addEventListener("click", () => openAggregate(edge));
    group.addEventListener("mouseenter", (event) => {
      setNetworkFocus(null, edgeId);
      setNetworkTooltip(edgeTooltip(edge), event);
    });
    group.addEventListener("mousemove", positionNetworkTooltip);
    group.addEventListener("mouseleave", () => { clearNetworkFocus(); hideNetworkTooltip(); });
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openAggregate(edge); }
    });
    edgeLayer.append(group);
    networkGraph.edgeElements.set(edgeId, group);
  });

  nodes.forEach((node) => {
    const position = positions.get(Number(node.member_id));
    if (!position) return;
    const isCenter = Number(node.member_id) === Number(network.center_member_id);
    const group = svgElement("g", {
      class: `network-node ${Number(node.member_id) === Number(network.center_member_id) ? "center" : ""} ${node.member_status === "mentioned_only" ? "mentioned-only" : ""}`,
      tabindex: 0, role: "button", "data-member-id": Number(node.member_id),
    });
    if (isCenter) group.append(svgElement("circle", { cx: position.x, cy: position.y, r: 51, class: "network-node-halo" }));
    group.append(svgElement("circle", { cx: position.x, cy: position.y, r: isCenter ? 37 : 29, class: "network-node-core" }));
    const label = svgElement("text", { x: position.x, y: position.y + 5, class: "network-node-label" });
    label.textContent = String(node.label).slice(0, 8);
    group.append(label);
    group.addEventListener("click", () => {
      if (Date.now() < suppressNetworkNodeClickUntil) return;
      openMember(node);
    });
    group.addEventListener("mouseenter", (event) => {
      setNetworkFocus(node.member_id);
      setNetworkTooltip(nodeTooltip(node, edges), event);
    });
    group.addEventListener("mousemove", positionNetworkTooltip);
    group.addEventListener("mouseleave", () => { clearNetworkFocus(); hideNetworkTooltip(); });
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openMember(node); }
    });
    nodeLayer.append(group);
    networkGraph.nodeElements.set(Number(node.member_id), group);
  });
}

function renderAggregateSummary(aggregate) {
  relationshipSummary.replaceChildren();
  const fields = [
    ["??", `${aggregate.source?.nickname || aggregate.source?.user_id || "????"} ? ${aggregate.target?.nickname || aggregate.target?.user_id || "?????"}`],
    ["??", eventTypeLabel(aggregate.event_type)],
    ["??", `x${aggregate.count}`],
    ["??", formatTimestamp(aggregate.first_time)],
    ["??", formatTimestamp(aggregate.last_time)],
    ["??", sourceCountsLabel(aggregate.source_counts)],
    ["????", text(aggregate.last_evidence, "??")],
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
      title: `${eventTypeLabel(event.event_type)} ? ${event.source_nickname || event.source_user_id} ? ${event.target_nickname || event.target_user_id || "?????"}`,
      meta: `???${eventSourceLabel(event.source_type)}????${formatTimestamp(event.event_timestamp)}?????${Math.round(Number(event.confidence || 0) * 100)}%????${event.content}`,
    })));
    if (!events.length && !append) relationshipEvidenceList.append(recordRow({ title: "??????????" }));
    evidenceCursor = result.next_cursor || null;
    relationshipMoreButton.hidden = !evidenceCursor;
  } catch (error) {
    if (!append) relationshipEvidenceList.replaceChildren(recordRow({ title: "????????", meta: error.message || "?????" }));
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
  setDialogBusy(true, "?????????");
  try {
    const result = await requestMemberDetail(member);
    syncMember(result.member);
    detailStatus.textContent = "";
  } catch (error) {
    detailStatus.textContent = error.message || "????????";
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
    detailStatus.textContent = error.message || "????";
  } finally {
    setDialogBusy(false, detailStatus.textContent);
  }
}

function readConfidence(input) {
  const value = Number(input.value);
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    throw new Error("?????? 0 ? 1 ??");
  }
  return value;
}

async function saveNote() {
  const content = noteInput.value.trim();
  if (!content) return void (detailStatus.textContent = "??????");
  await runMutation("???????", () => bridge.apiPost("member/note", {
    ...memberIdentity(selectedMember), content,
  }), "?????");
}

async function addTag() {
  const tagName = tagInput.value.trim();
  if (!tagName) return void (detailStatus.textContent = "?????");
  await runMutation("???????", async () => {
    await bridge.apiPost("member/tags/add", { ...memberIdentity(selectedMember), tag_name: tagName });
    tagInput.value = "";
  }, "?????");
}

async function removeTag(tagName) {
  await runMutation("???????", () => bridge.apiPost("member/tags/remove", {
    ...memberIdentity(selectedMember), tag_name: tagName,
  }), "?????");
}

async function addAlias() {
  const alias = aliasInput.value.trim();
  if (!alias) return void (detailStatus.textContent = "?????");
  await runMutation("???????", async () => {
    await bridge.apiPost("member/aliases/add", {
      ...memberIdentity(selectedMember), alias, alias_type: aliasTypeInput.value, confidence: 1,
    });
    aliasInput.value = "";
  }, "?????");
}

async function removeAlias(aliasId) {
  await runMutation("???????", () => bridge.apiPost("member/aliases/remove", {
    ...memberIdentity(selectedMember), alias_id: aliasId,
  }), "?????");
}

async function mergeMember() {
  const targetUserId = mergeTargetInput.value.trim();
  if (!targetUserId) return void (detailStatus.textContent = "??????? QQ ?");
  if (!window.confirm("???????????????????????????????")) return;
  setDialogBusy(true, "?????????");
  try {
    await bridge.apiPost("member/merge", {
      ...memberIdentity(selectedMember), target_user_id: targetUserId, reason: mergeReasonInput.value.trim(),
    });
    mergeTargetInput.value = "";
    mergeReasonInput.value = "";
    await loadMembers();
    await refreshSelectedMember("?????????????????");
  } catch (error) {
    detailStatus.textContent = error.message || "????????";
  } finally {
    setDialogBusy(false, detailStatus.textContent);
  }
}

async function addLayeredTag() {
  const tagName = layeredTagInput.value.trim();
  if (!tagName) return void (detailStatus.textContent = "???????");
  let confidence;
  try { confidence = readConfidence(tagConfidenceInput); }
  catch (error) { detailStatus.textContent = error.message; return; }
  await runMutation("?????????", async () => {
    await bridge.apiPost("member/layered-tags/add", {
      ...memberIdentity(selectedMember), tag_name: tagName, layer: tagLayerInput.value,
      confidence, source_type: "manual",
    });
    layeredTagInput.value = "";
  }, "???????");
}

async function removeLayeredTag(tagId) {
  await runMutation("?????????", () => bridge.apiPost("member/layered-tags/remove", {
    ...memberIdentity(selectedMember), tag_id: tagId,
  }), "???????");
}

async function addRelationshipEvent() {
  const content = eventContentInput.value.trim();
  if (!content) return void (detailStatus.textContent = "???????");
  let confidence;
  try { confidence = readConfidence(eventConfidenceInput); }
  catch (error) { detailStatus.textContent = error.message; return; }
  await runMutation("?????????", async () => {
    await bridge.apiPost("relationship-events", {
      ...memberIdentity(selectedMember), target_user_id: eventTargetInput.value.trim(),
      event_type: eventTypeInput.value, content, confidence, source_type: "manual",
    });
    eventTargetInput.value = "";
    eventContentInput.value = "";
  }, "???????");
  networkData = null;
  if (!networkView.hidden && networkCenter) loadNetwork();
}

async function loadMembers() {
  refreshButton.disabled = true;
  summary.textContent = "?????????";
  try {
    const result = await bridge.apiGet("members");
    members = Array.isArray(result.members) ? result.members : [];
    render();
  } catch (error) {
    members = [];
    table.hidden = true;
    emptyState.hidden = false;
    summary.textContent = error.message || "????????";
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
networkResetViewButton.addEventListener("click", resetNetworkViewport);
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
addNetworkPointerInteractions();
loadMembers();
