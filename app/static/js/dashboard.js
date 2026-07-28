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

  const muteBtn = card.querySelector("[data-field=mute-btn]");
  if (muteBtn) {
    muteBtn.dataset.muted = status.muted ? "1" : "0";
    muteBtn.textContent = status.muted ? "🎤 Unmute" : "🔇 Mute";
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
}

async function callControl(deviceId, action, body) {
  const resp = await fetch(`/api/devices/${deviceId}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    showToast(`실패: ${detail.detail || resp.status}`);
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

async function rebootDevice(deviceId, deviceName, btn) {
  if (!confirm(`"${deviceName}" 장비를 재부팅하시겠습니까?\n일시적으로 응답하지 않게 됩니다.`)) return;
  btn.disabled = true;
  const ok = await callControl(deviceId, "reboot");
  btn.disabled = false;
  if (ok) showToast("재부팅 명령 전송됨");
}

async function deleteDevice(deviceId, deviceName, btn) {
  if (!confirm(`"${deviceName}" 장비를 삭제하시겠습니까?`)) return;
  btn.disabled = true;
  const resp = await fetch(`/api/devices/${deviceId}`, { method: "DELETE" });
  btn.disabled = false;
  if (resp.ok) {
    location.reload();
  } else {
    showToast("삭제 실패");
  }
}

function deviceForm() {
  return {
    open: false,
    saving: false,
    error: "",
    name: "",
    vendor: "poly",
    connection_type: "telnet",
    host: "",
    port: 2323,
    group: "",
    username: "",
    password: "",
    is_simulated: true,
    async submit() {
      this.saving = true;
      this.error = "";
      const resp = await fetch("/api/devices", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: this.name,
          vendor: this.vendor,
          connection_type: this.connection_type,
          host: this.host,
          port: Number(this.port),
          group: this.group,
          username: this.username,
          password: this.password,
          is_simulated: this.is_simulated,
        }),
      });
      this.saving = false;
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        this.error = typeof detail.detail === "string" ? detail.detail : "등록 실패";
        return;
      }
      location.reload();
    },
  };
}

document.addEventListener("DOMContentLoaded", () => {
  connectStatusSocket();
  updateStatBar();
});
