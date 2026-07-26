const bridge = window.AstrBotPluginPage;
const refreshButton = document.getElementById("refresh-button");
const searchInput = document.getElementById("search-input");
const summary = document.getElementById("summary");
const table = document.getElementById("member-table");
const body = document.getElementById("member-body");
const emptyState = document.getElementById("empty-state");
const dialog = document.getElementById("member-dialog");
const dialogClose = document.getElementById("dialog-close");
const detailStatus = document.getElementById("detail-status");
const detailUserId = document.getElementById("detail-user-id");
const detailNickname = document.getElementById("detail-nickname");
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

let members = [];
let selectedMember = null;

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
  button.append(name, id);
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
    ].join(" ").toLocaleLowerCase();
    return !query || searchable.includes(query);
  });
  body.replaceChildren();
  for (const member of filtered) {
    const row = document.createElement("tr");
    row.append(
      createGroupCell(member), createMemberCell(member),
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
  const target = event.target_nickname || event.target_user_id;
  return target
    ? `${event.source_nickname || event.source_user_id} → ${target}`
    : `${event.source_nickname || event.source_user_id}（无目标成员）`;
}

function renderEvents(member) {
  relationshipEventList.replaceChildren();
  const events = Array.isArray(member.relationship_events) ? member.relationship_events : [];
  if (!events.length) {
    relationshipEventList.append(recordRow({ title: "暂无关系事件", meta: "可人工记录，也会保存唯一明确的 @提及" }));
    return;
  }
  events.forEach((event) => relationshipEventList.append(recordRow({
    title: `${event.event_type} · ${eventLabel(event)}`,
    meta: `${event.content} · ${Math.round(Number(event.confidence || 0) * 100)}% · ${event.source_type} · ${formatTimestamp(event.event_timestamp)}`,
  })));
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
loadMembers();
