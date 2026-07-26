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

let members = [];
let selectedMember = null;

function formatTimestamp(timestamp) {
  if (!timestamp) {
    return "暂无";
  }
  const date = new Date(Number(timestamp) * 1000);
  if (Number.isNaN(date.getTime())) {
    return "未知";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function memberIdentity(member) {
  return {
    platform_id: member.platform_id || "",
    group_id: member.group_id || member.external_group_id || "",
    user_id: member.user_id || member.external_user_id || "",
  };
}

function tagsFor(member) {
  if (Array.isArray(member.tags)) {
    return member.tags;
  }
  return String(member.tags || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
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
      member.group_name,
      member.group_id,
      member.external_group_id,
      member.nickname,
      member.user_id,
      member.external_user_id,
      member.tags,
      member.note,
    ].join(" ").toLocaleLowerCase();
    return !query || searchable.includes(query);
  });

  body.replaceChildren();
  for (const member of filtered) {
    const row = document.createElement("tr");
    row.append(
      createGroupCell(member),
      createMemberCell(member),
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
    ? "暂无已记录成员"
    : `显示 ${filtered.length} / ${members.length} 名成员`;
}

function setDialogBusy(busy, message = "") {
  dialog.dataset.busy = busy ? "true" : "false";
  saveNoteButton.disabled = busy;
  addTagButton.disabled = busy;
  noteInput.disabled = busy;
  tagInput.disabled = busy;
  detailStatus.textContent = message;
}

function renderDetail(member) {
  detailUserId.textContent = member.user_id || member.external_user_id || "-";
  detailNickname.textContent = member.nickname || "未获取昵称";
  detailGroup.textContent = groupLabel(member);
  detailMessageCount.textContent = String(member.message_count || 0);
  detailLastMessage.textContent = formatTimestamp(member.last_message_timestamp);
  detailProfile.textContent = member.summary || "暂无";
  noteInput.value = member.note || "";
  detailTagList.replaceChildren();

  const tags = tagsFor(member);
  if (tags.length === 0) {
    const empty = document.createElement("span");
    empty.className = "muted-text";
    empty.textContent = "暂无标签";
    detailTagList.append(empty);
    return;
  }
  for (const tagName of tags) {
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
  }
}

function syncMember(member) {
  selectedMember = member;
  const index = members.findIndex((item) => sameMember(item, member));
  const listMember = {
    ...member,
    tags: tagsFor(member).join(", "),
  };
  if (index === -1) {
    members = [listMember, ...members];
  } else {
    members[index] = { ...members[index], ...listMember };
  }
  render();
  renderDetail(member);
}

async function requestMemberDetail(member) {
  return bridge.apiGet("member", memberIdentity(member));
}

async function openMember(member) {
  selectedMember = member;
  renderDetail(member);
  detailStatus.textContent = "正在读取成员详情…";
  if (!dialog.open) {
    dialog.showModal();
  }
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

async function saveNote() {
  if (!selectedMember) return;
  const content = noteInput.value.trim();
  if (!content) {
    detailStatus.textContent = "备注不能为空";
    noteInput.focus();
    return;
  }
  setDialogBusy(true, "正在保存备注…");
  try {
    const result = await bridge.apiPost("member/note", {
      ...memberIdentity(selectedMember),
      content,
    });
    syncMember(result.member);
    detailStatus.textContent = "备注已保存";
  } catch (error) {
    detailStatus.textContent = error.message || "保存备注失败";
  } finally {
    setDialogBusy(false, detailStatus.textContent);
  }
}

async function addTag() {
  if (!selectedMember) return;
  const tagName = tagInput.value.trim();
  if (!tagName) {
    detailStatus.textContent = "请输入标签";
    tagInput.focus();
    return;
  }
  setDialogBusy(true, "正在添加标签…");
  try {
    const result = await bridge.apiPost("member/tags/add", {
      ...memberIdentity(selectedMember),
      tag_name: tagName,
    });
    tagInput.value = "";
    syncMember(result.member);
    detailStatus.textContent = "标签已添加";
  } catch (error) {
    detailStatus.textContent = error.message || "添加标签失败";
  } finally {
    setDialogBusy(false, detailStatus.textContent);
  }
}

async function removeTag(tagName) {
  if (!selectedMember) return;
  setDialogBusy(true, "正在删除标签…");
  try {
    const result = await bridge.apiPost("member/tags/remove", {
      ...memberIdentity(selectedMember),
      tag_name: tagName,
    });
    syncMember(result.member);
    detailStatus.textContent = "标签已删除";
  } catch (error) {
    detailStatus.textContent = error.message || "删除标签失败";
  } finally {
    setDialogBusy(false, detailStatus.textContent);
  }
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
tagInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    addTag();
  }
});
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});
loadMembers();
