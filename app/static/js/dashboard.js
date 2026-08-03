// app/static/js/dashboard.js
// 대시보드 상호작용: WebSocket 실시간 상태 반영 + 제어 명령 fetch 호출.
// UX_SPEC.md 5절 인터랙션 플로우 기준.

function connectStatusSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/status`);
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    updateCard(msg.device_id, msg.status);
    updateStatBar();
  };
  ws.onclose = () => setTimeout(connectStatusSocket, 3000);
}

function updateCard(deviceId, status) {
  const card = document.querySelector(`[data-device-id="${deviceId}"]`);
  if (!card) return;

  card.classList.remove("status-online", "status-call", "status-offline");
  card.classList.add(!status.online ? "status-offline" : status.in_call ? "status-call" : "status-online");

  const statusText = card.querySelector("[data-field=status-text]");
  if (statusText) {
    statusText.textContent = !status.online ? "오프라인" : status.in_call ? "통화중" : "온라인";
  }

  const muteText = card.querySelector("[data-field=mute-text]");
  if (muteText) muteText.textContent = status.muted ? "음소거됨" : "음소거 안됨";

  const muteBtn = card.querySelector('[data-field="mute-icon-btn"]');
  if (muteBtn) {
    muteBtn.dataset.muted = status.muted ? "1" : "0";
    muteBtn.classList.toggle("on", status.in_call && !status.muted);
    muteBtn.classList.toggle("muted", status.muted);
    const tip = muteBtn.querySelector(".tip");
    if (tip) tip.textContent = status.muted ? "음소거 해제" : "음소거";
  }

  const hangupBtn = card.querySelector('[data-field="hangup-icon-btn"]');
  if (hangupBtn) {
    hangupBtn.classList.toggle("on", status.in_call);
    hangupBtn.classList.toggle("disabled", !status.in_call);
  }

  const rebootBtn = card.querySelector('[data-field="reboot-icon-btn"]');
  if (rebootBtn) rebootBtn.classList.toggle("on", status.online);

  const modelText = card.querySelector('[data-field="model-text"]');
  if (modelText && status.model) {
    const rest = modelText.textContent.split(" · ").slice(1).join(" · ");
    modelText.textContent = `${status.model} · ${rest}`;
  }

  const rebootText = card.querySelector('[data-field="reboot-text"]');
  if (rebootText) rebootText.textContent = formatLastReboot(status.uptime_seconds);

  const callSubject = card.querySelector('[data-field="call-subject"]');
  if (callSubject) {
    const subject = status.in_call ? findActiveMeetingSubject(deviceId, status.call_peer) : null;
    callSubject.textContent = subject ? ` — "${subject}"` : "";
  }

  const errorText = card.querySelector("[data-field=error-text]");
  if (errorText) {
    errorText.textContent = status.error || "";
    errorText.style.display = status.error ? "block" : "none";
  }

  const lastUpdated = card.querySelector("[data-field=last-updated]");
  if (lastUpdated) lastUpdated.textContent = "방금 갱신됨";

  card.dataset.online = status.online ? "1" : "0";
  card.dataset.inCall = status.in_call ? "1" : "0";
}

function updateStatBar() {
  const cards = document.querySelectorAll(".device-card");
  let online = 0;
  let offline = 0;
  let inCall = 0;
  cards.forEach((card) => {
    if (card.dataset.online === "1") online += 1;
    else offline += 1;
    if (card.dataset.inCall === "1") inCall += 1;
  });
  const set = (field, value) => {
    const el = document.querySelector(`[data-stat=${field}]`);
    if (el) el.textContent = value;
  };
  set("total", cards.length);
  set("online", online);
  set("offline", offline);
  set("call", inCall);

  const banner = document.getElementById("alert-banner");
  const alertText = document.getElementById("alert-text");
  if (banner && alertText) {
    if (offline > 0) {
      alertText.textContent = `응답 없는 장비 ${offline}개`;
      banner.style.display = "";
    } else {
      banner.style.display = "none";
    }
  }
}

function filterGroup(group, btn) {
  document.querySelectorAll("#group-tabs .tab").forEach((t) => t.classList.remove("active"));
  btn.classList.add("active");

  document.querySelectorAll(".device-card").forEach((card) => {
    const match = group === "__all__" || card.dataset.group === group;
    card.style.display = match ? "" : "none";
  });
}

async function callControl(deviceId, action, body) {
  const resp = await fetch(`/api/devices/${deviceId}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await resp.json().catch(() => ({}));
  // resp.ok(HTTP 상태)만 보면 안 된다 — 서버가 200과 함께 {ok:false}를 돌려주는
  // 경로도 있어서(예: 드라이버가 예외 없이 실패만 반환), 그 경우 실제로는 실패인데
  // "완료" 토스트가 뜨던 버그가 있었다(2026-07-31 VDI 검증).
  if (!resp.ok || data.ok === false) {
    showToast(`실패: ${data.detail || resp.status}`);
    return false;
  }
  return true;
}

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2500);
}

async function refreshStatus(deviceId) {
  const resp = await fetch(`/api/devices/${deviceId}/status`);
  if (resp.ok) {
    updateCard(deviceId, await resp.json());
    updateStatBar();
  }
}

async function toggleMute(deviceId, btn) {
  const currentlyMuted = btn.dataset.muted === "1"; // 항상 최신 DOM 상태를 읽는다 (stale closure 값 금지)
  btn.disabled = true;
  const ok = await callControl(deviceId, "mute", { on: !currentlyMuted });
  btn.disabled = false;
  if (ok) {
    showToast(currentlyMuted ? "음소거 해제 완료" : "음소거 완료");
    await refreshStatus(deviceId);
  }
}

async function hangupCall(deviceId, btn) {
  if (!confirm("통화를 종료하시겠습니까?")) return;
  btn.disabled = true;
  const ok = await callControl(deviceId, "hangup");
  btn.disabled = false;
  if (ok) {
    showToast("종료 완료");
    await refreshStatus(deviceId);
  }
}

async function rebootDevice(deviceId, btn) {
  const card = btn.closest(".device-card");
  const nameEl = card ? card.querySelector("h3") : null;
  const deviceName = nameEl ? nameEl.firstChild.textContent.trim() : deviceId;
  if (!confirm(`"${deviceName}" 장비를 재부팅하시겠습니까?\n일시적으로 응답하지 않게 됩니다.`)) return;
  btn.disabled = true;
  const ok = await callControl(deviceId, "reboot");
  btn.disabled = false;
  if (ok) showToast("재부팅 명령 전송됨");
}

function deviceForm() {
  return {
    open: false,
    saving: false,
    error: "",
    editingId: null,
    name: "",
    vendor: "poly",
    connection_type: "telnet",
    host: "",
    port: 2323,
    group: "",
    username: "",
    password: "",
    teams_tenant_address: "",
    is_simulated: true,
    openCreate() {
      this.editingId = null;
      this.name = "";
      this.vendor = "poly";
      this.connection_type = "telnet";
      this.host = "";
      this.port = 2323;
      this.group = "";
      this.username = "";
      this.password = "";
      this.teams_tenant_address = "";
      this.is_simulated = true;
      this.error = "";
      this.open = true;
    },
    openEdit(device) {
      this.editingId = device.id;
      this.name = device.name;
      this.vendor = device.vendor;
      this.connection_type = device.connection_type;
      this.host = device.host;
      this.port = device.port;
      this.group = device.group;
      this.username = "";
      this.password = "";
      this.teams_tenant_address = device.teams_tenant_address || "";
      this.is_simulated = device.is_simulated;
      this.error = "";
      this.open = true;
    },
    async submit() {
      this.saving = true;
      this.error = "";
      const body = {
        name: this.name,
        vendor: this.vendor,
        connection_type: this.connection_type,
        host: this.host,
        port: Number(this.port),
        group: this.group,
        teams_tenant_address: this.teams_tenant_address,
        is_simulated: this.is_simulated,
      };
      let resp;
      if (this.editingId) {
        if (this.username) body.username = this.username;
        if (this.password) body.password = this.password;
        resp = await fetch(`/api/devices/${this.editingId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } else {
        body.username = this.username;
        body.password = this.password;
        resp = await fetch("/api/devices", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      }
      this.saving = false;
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        this.error = typeof detail.detail === "string" ? detail.detail : "저장 실패";
        return;
      }
      location.reload();
    },
    async remove() {
      if (!this.editingId) return;
      if (!confirm(`"${this.name}" 장비를 삭제하시겠습니까?`)) return;
      this.saving = true;
      const resp = await fetch(`/api/devices/${this.editingId}`, { method: "DELETE" });
      this.saving = false;
      if (resp.ok) {
        location.reload();
      } else {
        this.error = "삭제 실패";
      }
    },
  };
}

async function openEditDevice(deviceId) {
  const resp = await fetch(`/api/devices/${deviceId}`);
  if (!resp.ok) {
    showToast("장비 정보를 불러오지 못했습니다");
    return;
  }
  const device = await resp.json();
  window.dispatchEvent(new CustomEvent("open-edit-device", { detail: device }));
}

const deviceMeetingsCache = new Map();

async function fetchDeviceMeetings(deviceId) {
  try {
    const resp = await fetch(`/api/devices/${deviceId}/obtp`);
    if (!resp.ok) return [];
    const data = await resp.json();
    if (!data.supported) return [];
    const now = new Date().toISOString();
    const upcoming = data.entries.filter((entry) => entry.start_time >= now || entry.end_time >= now);
    upcoming.sort((a, b) => a.start_time.localeCompare(b.start_time));
    return upcoming;
  } catch (e) {
    return [];
  }
}

function formatMeetingTime(isoString) {
  return isoString.replace("T", " ").slice(11, 16);
}

const MEETINGS_SORT_KEY = "bridgex.meetings.sort";
const MEETINGS_PAGE_SIZE_KEY = "bridgex.meetings.pageSize";
const MEETINGS_SORT_LABELS = { time: "시간", room: "회의실", subject: "회의명", join: "참가" };

const meetingsState = {
  rows: [],
  sortKey: "time",
  sortDir: "asc",
  pageSize: 10,
  page: 1,
};

function loadMeetingsPrefs() {
  try {
    const sort = JSON.parse(localStorage.getItem(MEETINGS_SORT_KEY) || "null");
    if (sort && sort.key && sort.dir) {
      meetingsState.sortKey = sort.key;
      meetingsState.sortDir = sort.dir;
    }
    const size = Number(localStorage.getItem(MEETINGS_PAGE_SIZE_KEY));
    if ([5, 10, 20].includes(size)) meetingsState.pageSize = size;
  } catch (e) {
    // localStorage 사용 불가 시 기본값(시간순 오름차순, 10개) 유지
  }
}

function saveMeetingsPrefs() {
  try {
    localStorage.setItem(
      MEETINGS_SORT_KEY,
      JSON.stringify({ key: meetingsState.sortKey, dir: meetingsState.sortDir })
    );
    localStorage.setItem(MEETINGS_PAGE_SIZE_KEY, String(meetingsState.pageSize));
  } catch (e) {
    // 무시 — 다음 방문 시 기본값으로 시작될 뿐 기능에는 영향 없음
  }
}

function meetingsSortValue(row, key) {
  if (key === "time") return row.entry.start_time;
  if (key === "room") return row.deviceName;
  if (key === "subject") return row.entry.subject;
  if (key === "join") return row.entry.join_uri ? 0 : 1; // 참가 링크 있는 행이 우선
  return "";
}

function sortMeetingsRows(rows) {
  const key = meetingsState.sortKey;
  const dir = meetingsState.sortDir === "desc" ? -1 : 1;
  return [...rows].sort((a, b) => {
    const av = meetingsSortValue(a, key);
    const bv = meetingsSortValue(b, key);
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return a.entry.start_time.localeCompare(b.entry.start_time);
  });
}

function setMeetingsSort(key) {
  if (meetingsState.sortKey === key) {
    meetingsState.sortDir = meetingsState.sortDir === "asc" ? "desc" : "asc";
  } else {
    meetingsState.sortKey = key;
    meetingsState.sortDir = "asc";
  }
  meetingsState.page = 1;
  saveMeetingsPrefs();
  renderMeetingsTable();
}

function setMeetingsPageSize(size) {
  meetingsState.pageSize = size;
  meetingsState.page = 1;
  saveMeetingsPrefs();
  renderMeetingsTable();
}

function changeMeetingsPage(delta) {
  const totalPages = Math.max(1, Math.ceil(meetingsState.rows.length / meetingsState.pageSize));
  meetingsState.page = Math.min(totalPages, Math.max(1, meetingsState.page + delta));
  renderMeetingsTable();
}

function renderMeetingsTable() {
  const container = document.getElementById("meetings-list");
  const pagination = document.getElementById("meetings-pagination");
  if (!container) return;
  container.textContent = "";

  if (meetingsState.rows.length === 0) {
    const p = document.createElement("p");
    p.className = "meta";
    p.textContent = "오늘 예정된 회의가 없습니다.";
    container.appendChild(p);
    if (pagination) pagination.style.display = "none";
    return;
  }

  const sorted = sortMeetingsRows(meetingsState.rows);
  const totalPages = Math.max(1, Math.ceil(sorted.length / meetingsState.pageSize));
  meetingsState.page = Math.min(meetingsState.page, totalPages);
  const start = (meetingsState.page - 1) * meetingsState.pageSize;
  const pageRows = sorted.slice(start, start + meetingsState.pageSize);

  const table = document.createElement("table");
  table.className = "meetings-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const key of ["time", "room", "subject", "join"]) {
    const th = document.createElement("th");
    const arrow = meetingsState.sortKey === key ? (meetingsState.sortDir === "asc" ? " ▲" : " ▼") : "";
    th.textContent = MEETINGS_SORT_LABELS[key] + arrow;
    th.addEventListener("click", () => setMeetingsSort(key));
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const row of pageRows) {
    const tr = document.createElement("tr");

    const timeTd = document.createElement("td");
    timeTd.textContent = formatMeetingTime(row.entry.start_time);
    tr.appendChild(timeTd);

    const roomTd = document.createElement("td");
    roomTd.textContent = row.deviceName;
    tr.appendChild(roomTd);

    const subjectTd = document.createElement("td");
    subjectTd.textContent = row.entry.subject;
    tr.appendChild(subjectTd);

    const joinTd = document.createElement("td");
    if (row.entry.join_uri) {
      const link = document.createElement("a");
      link.href = "#";
      link.className = "meeting-link";
      link.textContent = row.entry.join_uri;
      link.title = "참여하기";
      link.addEventListener("click", (ev) => joinMeetingLink(ev, row.deviceId, row.entry));
      joinTd.appendChild(link);
    } else {
      const span = document.createElement("span");
      span.className = "meta";
      span.textContent = "참가 정보 없음";
      joinTd.appendChild(span);
    }
    tr.appendChild(joinTd);

    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  container.appendChild(table);

  if (pagination) {
    pagination.style.display = "flex";
    document.querySelectorAll(".page-size-btn").forEach((btn) => {
      btn.classList.toggle("active", Number(btn.dataset.size) === meetingsState.pageSize);
    });
    const label = document.getElementById("meetings-page-label");
    if (label) label.textContent = `${meetingsState.page} / ${totalPages}페이지 (전체 ${sorted.length}건)`;
  }
}

async function loadUpcomingMeetings() {
  const rows = [];

  for (const card of document.querySelectorAll(".device-card")) {
    const deviceId = card.dataset.deviceId;
    const nameEl = card.querySelector("h3");
    const deviceName = nameEl ? nameEl.firstChild.textContent.trim() : deviceId;
    const entries = await fetchDeviceMeetings(deviceId);
    deviceMeetingsCache.set(deviceId, entries);
    for (const entry of entries) rows.push({ deviceId, deviceName, entry });
    renderCardTeamsSection(deviceId, entries);
  }

  meetingsState.rows = rows;
  renderMeetingsTable();
}

async function joinMeetingLink(ev, deviceId, entry) {
  ev.preventDefault();
  const card = document.querySelector(`[data-device-id="${deviceId}"]`);
  if (card && card.dataset.inCall === "1") {
    // 통화 중에 회의 링크를 또 누르면 같은 회의에 중복 참가되면서 하울링이 나는 사고가
    // 실제로 있었다(2026-07-31 VDI 2차 재테스트, Cisco 장비) — 실수로 누르는 경우를 막는다.
    showToast("이미 통화 중입니다 — 먼저 종료 후 참가해주세요");
    return;
  }
  const ok = await callControl(deviceId, "join", entry);
  if (ok) {
    showToast(`"${entry.subject}" 참가 명령 전송됨`);
    await refreshStatus(deviceId);
  }
}

function renderCardTeamsSection(deviceId, entries) {
  const card = document.querySelector(`[data-device-id="${deviceId}"]`);
  if (!card) return;

  const label = card.querySelector('[data-field="teams-label"]');
  if (label) {
    label.textContent = entries.length > 0 ? `Teams · 오늘 남은 회의 ${entries.length}건` : "Teams · 오늘 회의 수신 안됨";
  }

  const list = card.querySelector('[data-field="teams-meetings"]');
  if (!list) return;
  list.textContent = "";
  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "teams-meeting-row";

    const time = document.createElement("span");
    time.className = "time";
    time.textContent = formatMeetingTime(entry.start_time);
    row.appendChild(time);

    row.appendChild(document.createTextNode(entry.subject + " · "));

    if (entry.join_uri) {
      const link = document.createElement("a");
      link.href = "#";
      link.className = "meeting-link";
      link.textContent = entry.join_uri;
      const tip = document.createElement("span");
      tip.className = "tip";
      tip.textContent = "참여하기";
      link.appendChild(tip);
      link.addEventListener("click", (ev) => joinMeetingLink(ev, deviceId, entry));
      row.appendChild(link);
    }

    list.appendChild(row);
  }
}

function findActiveMeetingSubject(deviceId, callPeer) {
  if (!callPeer) return null;
  const entries = deviceMeetingsCache.get(deviceId) || [];
  const match = entries.find((entry) => entry.join_uri === callPeer);
  if (!match) return null;
  return match.subject.length > 20 ? match.subject.slice(0, 20) + "..." : match.subject;
}

const REBOOT_WARNING_SECONDS = 30 * 24 * 3600;

function formatLastReboot(uptimeSeconds) {
  if (uptimeSeconds === null || uptimeSeconds === undefined || uptimeSeconds === "") return "";
  const seconds = Number(uptimeSeconds);
  if (Number.isNaN(seconds)) return "";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  let text = "마지막 재부팅: ";
  text += days > 0 ? `${days}일 ${hours}시간 전` : `${hours}시간 전`;
  if (seconds >= REBOOT_WARNING_SECONDS) text += " ⚠";
  return text;
}

async function directDial(deviceId, btn) {
  const card = btn.closest(".device-card");
  if (card.dataset.inCall === "1") {
    // joinMeetingLink와 동일한 이유 — 통화 중에 direct-dial까지 또 걸리면 같은 회의에
    // 중복 참가되며 하울링이 난다(2026-07-31 VDI 2차 재테스트, Cisco 장비에서 실제 발생).
    showToast("이미 통화 중입니다 — 먼저 종료 후 다이얼해주세요");
    return;
  }
  const idInput = card.querySelector('[data-field="dial-id-input"]');
  const tenantInput = card.querySelector('[data-field="dial-tenant-input"]');
  const meetingId = idInput.value.trim();
  if (!/^\d{10}$/.test(meetingId)) {
    showToast("회의 ID는 숫자 10자리여야 합니다");
    return;
  }
  if (!tenantInput.value.trim()) {
    showToast("Teams 테넌트 주소를 입력하세요");
    return;
  }
  btn.disabled = true;
  const resp = await fetch(`/api/devices/${deviceId}/direct-dial`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ meeting_id: meetingId, tenant_address: tenantInput.value.trim() }),
  });
  btn.disabled = false;
  if (resp.ok) {
    showToast("다이얼 명령 전송됨");
    await refreshStatus(deviceId);
  } else {
    const detail = await resp.json().catch(() => ({}));
    showToast(`다이얼 실패: ${detail.detail || resp.status}`);
  }
}

function wireDialEnterKey() {
  document.querySelectorAll('[data-field="dial-id-input"]').forEach((input) => {
    input.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      const card = input.closest(".device-card");
      const btn = card.querySelector('[data-field="dial-btn"]');
      if (btn) btn.click();
    });
  });
}

async function refreshStatusWithSpin(deviceId, btn) {
  btn.classList.add("spin");
  setTimeout(() => btn.classList.remove("spin"), 700);
  await refreshStatus(deviceId);
}

document.addEventListener("DOMContentLoaded", () => {
  connectStatusSocket();
  updateStatBar();
  loadMeetingsPrefs();
  loadUpcomingMeetings();
  wireDialEnterKey();
  document.querySelectorAll('[data-field="reboot-text"]').forEach((el) => {
    const seconds = el.dataset.uptimeSeconds;
    el.textContent = formatLastReboot(seconds);
  });
});
