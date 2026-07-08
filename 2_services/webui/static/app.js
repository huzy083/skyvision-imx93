// SkyVision WebUI – consume SSE stream + auto-refresh snapshot

const fmt = {
  num: (n, d = 2) => (n == null || Number.isNaN(n)) ? "—" : n.toFixed(d),
  ts: t => {
    const d = new Date(t * 1000);
    const p = n => String(n).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  },
};

const $ = id => document.getElementById(id);
const snapImg = $("snapshot");
const snapWrap = snapImg.parentElement;

let connOk = false;

function setConn(ok) {
  if (connOk === ok) return;
  connOk = ok;
  const b = $("connBadge");
  b.textContent = ok ? "● 已连接" : "● 断开";
  b.classList.toggle("bad", !ok);
}

// MJPEG <img> stream handles itself; only worry about reconnect on error.
snapImg.addEventListener("load",  () => snapWrap.classList.remove("stale"));
snapImg.addEventListener("error", () => {
  snapWrap.classList.add("stale");
  setTimeout(() => { snapImg.src = "/api/mjpeg?t=" + Date.now(); }, 1000);
});

// ---- state handlers per topic ----
function onDetection(data) {
  const list = $("detList");
  list.innerHTML = "";
  const objects = data.objects || [];
  $("detMeta").textContent = `${objects.length} obj · ${fmt.ts(data.ts)}`;
  for (const o of objects) {
    const item = document.createElement("div");
    item.className = "det-item";
    const [x0, y0, x1, y1] = o.bbox || [];
    item.innerHTML =
      `<span class="label">${o.label}</span>` +
      `<span class="score">${(o.score * 100).toFixed(0)}%</span>` +
      (x0 != null ? `<span class="bbox">(${x0.toFixed(2)}, ${y0.toFixed(2)}) → (${x1.toFixed(2)}, ${y1.toFixed(2)})</span>` : "");
    list.appendChild(item);
  }
}

function onStatus(data) {
  $("stCamera").textContent = data.camera || "—";
  $("stFps").textContent = fmt.num(data.fps, 1);
  $("stLat").textContent = fmt.num(data.latency_ms, 0) + " ms";
  $("stBr").textContent = fmt.num(data.bitrate_mbps, 2) + " Mbps";
  $("stLink").textContent = data.link || "—";
  $("stRec").textContent = data.recording ? "● 录像中" : "—";
  $("videoMeta").textContent = `${data.camera || ""} · ${fmt.num(data.fps, 0)}fps · ${fmt.num(data.latency_ms, 0)}ms`;
}

function onUavState(data) {
  // 与地面站 QML 状态条同款: 就绪/电池/飞控/模式/双源位姿
  const ready = $("uavReady");
  if (data.diverged)      { ready.textContent = "⚠ 定位发散"; ready.className = "v bad"; }
  else if (data.armed)    { ready.textContent = "✈ 飞行中";   ready.className = "v info"; }
  else if (data.ready)    { ready.textContent = "✔ 可起飞";   ready.className = "v ok"; }
  else                    { ready.textContent = "✘ 未就绪";   ready.className = "v warn"; }

  const bv = data.batt_v;
  const batt = $("uavBatt");
  batt.textContent = bv != null ? bv.toFixed(1) + " V" : "—";
  // 6S: >22.8V 正常 / >21.6V 偏低 / 以下告警
  batt.className = "v " + (bv == null ? "" : bv > 22.8 ? "ok" : bv > 21.6 ? "warn" : "bad");

  $("uavFcu").textContent = data.fcu ? "已连" : "未连";
  $("uavFcu").className = "v " + (data.fcu ? "ok" : "bad");
  $("uavMode").textContent = (data.mode || "?") + (data.armed ? " · 解锁" : " · 上锁");

  const p3 = o => o ? `${fmt.num(o.x, 2)}, ${fmt.num(o.y, 2)}, ${fmt.num(o.z, 2)}` : "—";
  $("uavLio").textContent = p3(data.lio);
  $("uavLio").className = "v mono " + (data.lio_fresh ? "" : "stale-v");
  $("uavEkf").textContent = p3(data.ekf);
  $("uavEkf").className = "v mono " + (data.ekf_fresh ? "" : "stale-v");
  $("uavMeta").textContent = fmt.ts(data.ts);
}

let evtTotal = 0;
function onEvent(data) {
  evtTotal++;
  $("evtCount").textContent = evtTotal;
  const list = $("evtList");
  const div = document.createElement("div");
  div.className = `evt-item level-${data.level || "info"}`;
  let msg = data.msg || "";
  if (data.camera) msg += `  [${data.camera}]`;
  if (data.labels) msg += `  ${data.labels.join(",")}`;
  div.innerHTML = `<span class="ts">${fmt.ts(data.ts)}</span><span class="msg">${msg}</span>`;
  list.insertBefore(div, list.firstChild);
  while (list.children.length > 100) list.removeChild(list.lastChild);
}

// dispatch by topic
function dispatch(topic, data) {
  switch (topic) {
    case "skyvision/detection": onDetection(data); break;
    case "skyvision/status":    onStatus(data); break;
    case "skyvision/uav_pose":  onUavState(data); break;
    case "skyvision/event":     onEvent(data); break;
  }
}

// ---- SSE ----
function connectSSE() {
  const es = new EventSource("/events");
  es.onopen = () => setConn(true);
  es.onmessage = ev => {
    try {
      const m = JSON.parse(ev.data);
      if (m.topic === "_init") {
        const last = m.data.last || {};
        for (const [t, d] of Object.entries(last)) if (d) dispatch(t, d);
        const evts = (m.data.events || []).slice().reverse();
        for (const e of evts) onEvent(e);
      } else {
        dispatch(m.topic, m.data);
      }
    } catch (e) { /* ignore */ }
  };
  es.onerror = () => {
    setConn(false);
    es.close();
    setTimeout(connectSSE, 2000);
  };
}
connectSSE();

// clock
setInterval(() => {
  const d = new Date();
  const p = n => String(n).padStart(2, "0");
  $("clock").textContent =
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}, 1000);
