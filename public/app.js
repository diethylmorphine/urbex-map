/* URBEX GRID — Mini App client */
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

const API = {
  async req(path, opts = {}) {
    const res = await fetch(path, {
      ...opts,
      headers: {
        "Content-Type": "application/json",
        Authorization: "tma " + tg.initData,
        ...(opts.headers || {}),
      },
    });
    if (!res.ok) throw Object.assign(new Error("api"), { status: res.status });
    return res.json();
  },
  get: (p) => API.req(p),
  post: (p, body) => API.req(p, { method: "POST", body: JSON.stringify(body || {}) }),
};

const $ = (id) => document.getElementById(id);
const TIER_COLORS = ["#7fa98c", "#e8a13c", "#c25b2a", "#e24c4c"];

let ME = null, TIERS = [], MAP = null, MARKERS = {}, ADMIN_MODE = false;
let placing = false, currentLoc = null;

function toast(msg, ms = 2200) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), ms);
}

/* ---------- map ---------- */
function initMap() {
  MAP = L.map("map", { zoomControl: false, attributionControl: true })
    .setView([52.2297, 21.0122], 12); // fallback center
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap &copy; CARTO',
  }).addTo(MAP);
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (p) => MAP.setView([p.coords.latitude, p.coords.longitude], 14),
      () => {}
    );
  }
  MAP.on("move", () => {
    if (!placing) return;
    const c = MAP.getCenter();
    $("placeCoords").textContent = c.lat.toFixed(6) + ", " + c.lng.toFixed(6);
  });
}

function pinIcon(loc) {
  const cls = loc.status === "pending" ? "pin pending" : `pin pin-t${loc.tier}`;
  return L.divIcon({ className: "", html: `<div class="${cls}"></div>`, iconSize: [18, 18], iconAnchor: [9, 9] });
}

/* ---------- data ---------- */
async function loadMe() {
  const data = await API.get("/api/me");
  ME = data.me;
  TIERS = data.tiers;
  $("hudName").textContent = ME.username ? "@" + ME.username : ME.first_name || "EXPLORER";
  $("hudPoints").textContent = ME.points;
  $("hudTier").textContent = "T" + ME.visible_tier + (ME.is_admin ? " · ADMIN" : "");
  const next = TIERS.find((t) => t.min_points > ME.points);
  if (next && !ME.is_admin) {
    const prev = TIERS.filter((t) => t.min_points <= ME.points).pop();
    const span = next.min_points - prev.min_points;
    const pct = Math.min(100, ((ME.points - prev.min_points) / span) * 100);
    $("tierFill").style.width = pct + "%";
    $("hudNext").textContent = `${next.min_points - ME.points} PTS TO T${next.tier} ${next.name}`;
  } else {
    $("tierFill").style.width = "100%";
    $("hudNext").textContent = ME.is_admin ? "FULL CLEARANCE" : "MAX TIER";
  }
  if (ME.is_admin) $("adminToggle").classList.remove("hidden");
}

async function loadLocations() {
  const data = await API.get("/api/locations");
  Object.values(MARKERS).forEach((m) => MAP.removeLayer(m));
  MARKERS = {};
  for (const loc of data.locations) {
    if (loc.status === "pending" && !ADMIN_MODE && !loc.mine) continue;
    const m = L.marker([loc.lat, loc.lng], { icon: pinIcon(loc) }).addTo(MAP);
    m.on("click", () => openDetail(loc));
    MARKERS[loc.id] = m;
  }
  const chip = $("lockedChip");
  if (data.hidden_count > 0 && !ME.is_admin) {
    $("lockedCount").textContent = data.hidden_count;
    chip.classList.remove("hidden");
  } else chip.classList.add("hidden");
}

/* ---------- placement flow ---------- */
$("fabAdd").onclick = () => {
  placing = true;
  closeSheets();
  $("crosshair").classList.remove("hidden");
  $("placeBar").classList.remove("hidden");
  $("fabAdd").classList.add("hidden");
  const c = MAP.getCenter();
  $("placeCoords").textContent = c.lat.toFixed(6) + ", " + c.lng.toFixed(6);
  toast("MOVE MAP — CENTER THE TARGET");
};
$("placeCancel").onclick = exitPlacing;
function exitPlacing() {
  placing = false;
  $("crosshair").classList.add("hidden");
  $("placeBar").classList.add("hidden");
  $("fabAdd").classList.remove("hidden");
}
$("placeConfirm").onclick = () => {
  const c = MAP.getCenter();
  exitPlacing();
  $("formCoords").textContent = c.lat.toFixed(6) + ", " + c.lng.toFixed(6);
  $("sheetForm").dataset.lat = c.lat;
  $("sheetForm").dataset.lng = c.lng;
  $("sheetForm").classList.remove("hidden");
};

$("formCancel").onclick = () => $("sheetForm").classList.add("hidden");
$("formSubmit").onclick = async () => {
  const title = $("fTitle").value.trim();
  if (!title) return toast("NAME THE SPOT");
  try {
    await API.post("/api/locations", {
      title,
      description: $("fDesc").value.trim(),
      category: $("fCategory").value,
      lat: parseFloat($("sheetForm").dataset.lat),
      lng: parseFloat($("sheetForm").dataset.lng),
    });
    $("fTitle").value = ""; $("fDesc").value = "";
    $("sheetForm").classList.add("hidden");
    toast("SUBMITTED — AWAITING VERIFICATION");
    tg.HapticFeedback?.notificationOccurred("success");
    loadLocations();
  } catch { toast("SUBMIT FAILED"); }
};

/* ---------- detail sheet ---------- */
function closeSheets() {
  $("sheetForm").classList.add("hidden");
  $("sheetDetail").classList.add("hidden");
}

async function openDetail(loc) {
  currentLoc = loc;
  closeSheets();
  $("dTitle").textContent = loc.title;
  $("dCoords").textContent = loc.lat.toFixed(6) + ", " + loc.lng.toFixed(6);
  const badge = $("dTier");
  if (loc.status === "pending") {
    badge.textContent = "PENDING";
    badge.style.background = "#e24c4c";
  } else {
    const t = TIERS.find((x) => x.tier === loc.tier);
    badge.textContent = `T${loc.tier} ${t ? t.name : ""}`;
    badge.style.background = TIER_COLORS[loc.tier] || TIER_COLORS[0];
  }
  $("dMeta").textContent =
    `${loc.category.toUpperCase()} · BY ${loc.author ? "@" + loc.author : "ANON"} · ${loc.review_count} REPORTS`;
  $("dDesc").textContent = loc.description || "No intel yet.";
  $("dLikes").textContent = loc.likes;

  // admin panel: delete for any spot; verify block only while pending
  const panel = $("dAdminPanel");
  if (ME.is_admin) {
    panel.classList.remove("hidden");
    const verifyBlock = $("dVerifyBlock");
    if (loc.status === "pending") {
      verifyBlock.classList.remove("hidden");
      const tb = $("tierButtons");
      tb.innerHTML = "";
      TIERS.forEach((t) => {
        const b = document.createElement("button");
        b.className = "btn ghost";
        b.style.borderColor = TIER_COLORS[t.tier];
        b.style.color = TIER_COLORS[t.tier];
        b.textContent = `T${t.tier}`;
        b.onclick = async () => {
          await API.post("/api/admin/verify", { id: loc.id, tier: t.tier });
          toast(`APPROVED AS T${t.tier}`);
          closeSheets(); loadLocations();
        };
        tb.appendChild(b);
      });
    } else verifyBlock.classList.add("hidden");
  } else panel.classList.add("hidden");

  await renderReviews(loc.id);
  $("sheetDetail").classList.remove("hidden");
}

$("dDelete").onclick = () => {
  if (!currentLoc) return;
  const doDelete = async () => {
    await API.post("/api/admin/delete", { id: currentLoc.id });
    toast("SPOT DELETED");
    closeSheets(); loadLocations();
  };
  if (tg.showConfirm) {
    tg.showConfirm(`Delete "${currentLoc.title}" permanently?`, (ok) => { if (ok) doDelete(); });
  } else if (confirm(`Delete "${currentLoc.title}" permanently?`)) {
    doDelete();
  }
};

$("dReject").onclick = async () => {
  if (!currentLoc) return;
  await API.post("/api/admin/reject", { id: currentLoc.id });
  toast("REJECTED");
  closeSheets(); loadLocations();
};

$("dLike").onclick = async () => {
  if (!currentLoc || currentLoc.status !== "approved") return toast("NOT VERIFIED YET");
  try {
    const r = await API.post(`/api/locations/${currentLoc.id}/like`);
    currentLoc.likes += r.liked ? 1 : -1;
    $("dLikes").textContent = currentLoc.likes;
    tg.HapticFeedback?.impactOccurred("light");
  } catch { toast("FAILED"); }
};

$("dNav").onclick = () => {
  if (!currentLoc) return;
  tg.openLink(`https://www.google.com/maps/dir/?api=1&destination=${currentLoc.lat},${currentLoc.lng}`);
};

async function renderReviews(locId) {
  const list = $("reviewList");
  list.innerHTML = "";
  const { reviews } = await API.get(`/api/locations/${locId}/reviews`);
  if (!reviews.length) {
    list.innerHTML = '<div class="review-text" style="color:var(--faded)">No field reports. Be the first in.</div>';
    return;
  }
  for (const r of reviews) {
    const el = document.createElement("div");
    el.className = "review";
    el.innerHTML = `
      <div class="review-head">
        <span>@${r.author}</span>
        <button class="review-like">▲ ${r.likes}</button>
      </div>
      <div class="review-text"></div>`;
    el.querySelector(".review-text").textContent = r.text;
    el.querySelector(".review-like").onclick = async (e) => {
      const btn = e.target;
      const res = await API.post(`/api/reviews/${r.id}/like`);
      r.likes += res.liked ? 1 : -1;
      btn.textContent = `▲ ${r.likes}`;
    };
    list.appendChild(el);
  }
}

$("rSubmit").onclick = async () => {
  const text = $("rText").value.trim();
  if (!text || !currentLoc) return;
  await API.post(`/api/locations/${currentLoc.id}/reviews`, { text });
  $("rText").value = "";
  await renderReviews(currentLoc.id);
  loadMe(); // review_posted points
};

/* ---------- admin mode ---------- */
$("adminToggle").onclick = () => {
  ADMIN_MODE = !ADMIN_MODE;
  const b = $("adminToggle");
  b.classList.toggle("on", ADMIN_MODE);
  b.querySelector(".sub").textContent = ADMIN_MODE ? "MODE ON" : "MODE OFF";
  toast(ADMIN_MODE ? "ADMIN MODE — PENDING SPOTS VISIBLE" : "USER VIEW");
  loadLocations();
};

/* map click closes sheets */
document.addEventListener("click", (e) => {
  if (e.target.closest("#map") && !placing) closeSheets();
});

/* ---------- boot ---------- */
(async function boot() {
  initMap();
  try {
    await loadMe();
    // show configured reward in the form note
    await loadLocations();
    setInterval(loadLocations, 30000); // poll for updates
  } catch (e) {
    toast(e.status === 401 ? "OPEN THIS APP FROM TELEGRAM" : "CONNECTION FAILED", 5000);
  }
})();
