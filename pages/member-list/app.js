const bridge = window.AstrBotPluginPage;
const refreshButton = document.getElementById("refresh-button");
const searchInput = document.getElementById("search-input");
const summary = document.getElementById("summary");
const table = document.getElementById("member-table");
const body = document.getElementById("member-body");
const emptyState = document.getElementById("empty-state");

let members = [];

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

function textCell(value, className = "") {
  const cell = document.createElement("td");
  cell.className = className;
  cell.textContent = value || "-";
  return cell;
}

function render() {
  const query = searchInput.value.trim().toLocaleLowerCase();
  const filtered = members.filter((member) => {
    const searchable = [
      member.group_name,
      member.external_group_id,
      member.nickname,
      member.external_user_id,
      member.tags,
      member.note,
    ]
      .join(" ")
      .toLocaleLowerCase();
    return !query || searchable.includes(query);
  });

  body.replaceChildren();
  for (const member of filtered) {
    const row = document.createElement("tr");
    row.append(
      textCell(member.group_name || `群 ${member.external_group_id}`, "primary-cell"),
      textCell(member.nickname || `成员 ${member.external_user_id}`, "primary-cell"),
      textCell(String(member.message_count)),
      textCell(formatTimestamp(member.last_message_timestamp)),
      textCell(member.tags || "暂无", "tag-cell"),
      textCell(member.note || "暂无", "note-cell"),
    );
    body.append(row);
  }

  table.hidden = filtered.length === 0;
  emptyState.hidden = filtered.length !== 0;
  if (members.length === 0) {
    summary.textContent = "暂无已记录成员";
  } else {
    summary.textContent = `显示 ${filtered.length} / ${members.length} 名成员`;
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
    emptyState.innerHTML = "<strong>无法读取成员数据</strong><p>请检查插件数据库状态后重新刷新。</p>";
    summary.textContent = error.message || "读取成员数据失败";
  } finally {
    refreshButton.disabled = false;
  }
}

await bridge.ready();
refreshButton.addEventListener("click", loadMembers);
searchInput.addEventListener("input", render);
loadMembers();
