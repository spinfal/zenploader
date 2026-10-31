"use strict";

// ASCII banner (ANSI Shadow), matching the CLI. One class per row for the gradient.
const BANNER = [
  "███████╗███████╗███╗   ██╗██████╗ ██╗      ██████╗  █████╗ ██████╗ ███████╗██████╗ ",
  "╚══███╔╝██╔════╝████╗  ██║██╔══██╗██║     ██╔═══██╗██╔══██╗██╔══██╗██╔════╝██╔══██╗",
  "  ███╔╝ █████╗  ██╔██╗ ██║██████╔╝██║     ██║   ██║███████║██║  ██║█████╗  ██████╔╝",
  " ███╔╝  ██╔══╝  ██║╚██╗██║██╔═══╝ ██║     ██║   ██║██╔══██║██║  ██║██╔══╝  ██╔══██╗",
  "███████╗███████╗██║ ╚████║██║     ███████╗╚██████╔╝██║  ██║██████╔╝███████╗██║  ██║",
  "╚══════╝╚══════╝╚═╝  ╚═══╝╚═╝     ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝",
];

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  mode: "file",
  file: null,
  sites: [],
  chosenUrl: "",
  chosenName: "",
};

// ---- banner ----------------------------------------------------------
function renderBanner() {
  const el = $("#banner");
  el.innerHTML = BANNER
    .map((line, i) => `<span class="r${i}">${escapeHtml(line)}</span>`)
    .join("\n");
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// ---- tabs ------------------------------------------------------------
function initTabs() {
  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      $$(".tab").forEach((t) => t.classList.toggle("is-active", t === tab));
      $$(".panel").forEach((p) => {
        const on = p.dataset.panel === name;
        p.classList.toggle("is-active", on);
        p.hidden = !on;
      });
      if (name === "sites") renderSitesManage();
    });
  });
}

// ---- upload mode (file / text) ---------------------------------------
function initModes() {
  $$(".seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.mode = btn.dataset.mode;
      $$(".seg-btn").forEach((b) => b.classList.toggle("is-active", b === btn));
      $$(".mode").forEach((m) => { m.hidden = m.dataset.mode !== state.mode; });
      refreshGate();
    });
  });
}

// ---- dropzone --------------------------------------------------------
function initDrop() {
  const drop = $("#drop");
  const input = $("#file-input");

  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
  });
  input.addEventListener("change", () => setFile(input.files[0] || null));

  ["dragenter", "dragover"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); })
  );
  drop.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files[0];
    if (f) { input.files = e.dataTransfer.files; setFile(f); }
  });
}

function setFile(f) {
  state.file = f;
  const meta = $("#file-meta");
  if (f) {
    meta.hidden = false;
    meta.textContent = `${f.name}  (${humanSize(f.size)})`;
    if (!$("#name-input").value.trim()) $("#name-input").value = f.name;
  } else {
    meta.hidden = true;
  }
  refreshGate();
}

function humanSize(n) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let s = n, i = 0;
  while (s >= 1024 && i < units.length - 1) { s /= 1024; i++; }
  return i === 0 ? `${s} B` : `${s.toFixed(1)} ${units[i]}`;
}

// ---- site picker -----------------------------------------------------
async function loadSites() {
  try {
    const r = await fetch("/api/sites");
    const j = await r.json();
    if (j.ok) { state.sites = j.sites; renderSiteList(); }
  } catch (e) { /* offline; nothing to show */ }
}

function renderSiteList() {
  const q = $("#site-search").value.trim().toLowerCase();
  const list = $("#site-list");
  const matches = state.sites.filter((s) =>
    s.name.toLowerCase().includes(q) || s.url.toLowerCase().includes(q)
  );
  list.innerHTML = matches.map((s) => `
    <li data-url="${escapeHtml(s.url)}" class="${s.url === state.chosenUrl ? "is-sel" : ""}">
      ${escapeHtml(s.name)}<span class="url">${escapeHtml(s.url)}</span>
    </li>`).join("") || `<li class="muted">no matches</li>`;

  $$("#site-list li[data-url]").forEach((li) => {
    li.addEventListener("click", () => {
      state.chosenUrl = li.dataset.url;
      state.chosenName = state.sites.find((s) => s.url === state.chosenUrl)?.name || "";
      const chosen = $("#site-chosen");
      chosen.hidden = false;
      chosen.textContent = `▸ ${state.chosenName}`;
      renderSiteList();
      refreshGate();
    });
  });
}

// ---- content-type datalist ------------------------------------------
function populateCtypes() {
  // a sensible subset for quick overrides
  const common = [
    "text/plain", "text/html", "text/css", "text/csv", "application/json",
    "application/javascript", "application/pdf", "application/zip",
    "application/octet-stream", "image/png", "image/jpeg", "image/gif",
    "image/webp", "image/svg+xml", "video/mp4", "video/webm", "audio/mpeg",
  ];
  $("#ctype-list").innerHTML = common.map((c) => `<option value="${c}">`).join("");
}

// ---- gate (enable upload button) ------------------------------------
function refreshGate() {
  const hasTarget = !!state.chosenUrl;
  let hasPayload;
  if (state.mode === "file") hasPayload = !!state.file;
  else hasPayload = $("#text-input").value.length > 0;
  $("#upload-btn").disabled = !(hasTarget && hasPayload);
}

// ---- upload ----------------------------------------------------------
function initUpload() {
  $("#upload-btn").addEventListener("click", doUpload);
  $("#text-input").addEventListener("input", refreshGate);
  $("#site-search").addEventListener("input", renderSiteList);
}

async function doUpload() {
  const btn = $("#upload-btn");
  const status = $("#status");
  const result = $("#result");
  result.hidden = true;
  btn.disabled = true;

  status.hidden = false;
  status.className = "status is-busy";
  status.textContent = "▓▒░ uploading...";

  const form = new FormData();
  form.append("url", state.chosenUrl);
  const name = $("#name-input").value.trim();
  const ctype = $("#ctype-input").value.trim();
  if (name) form.append("filename", name);
  if (ctype) form.append("content_type", ctype);

  if (state.mode === "file") form.append("file", state.file);
  else form.append("text", $("#text-input").value);

  try {
    const r = await fetch("/api/upload", { method: "POST", body: form });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "upload failed");

    status.hidden = true;
    result.hidden = false;
    const a = $("#result-url");
    a.href = j.url;
    a.textContent = j.url;
    $("#result-meta").textContent =
      `${j.filename} · ${humanSize(j.size)} · ${j.content_type}` +
      (j.expires_human ? `  —  expires ${j.expires_human}` : "");
  } catch (e) {
    status.className = "status is-err";
    status.textContent = `✗ ${e.message}`;
  } finally {
    refreshGate();
  }
}

function initCopy() {
  $("#copy-btn").addEventListener("click", async () => {
    const url = $("#result-url").textContent;
    try {
      await navigator.clipboard.writeText(url);
      const b = $("#copy-btn");
      const old = b.textContent;
      b.textContent = "copied!";
      setTimeout(() => { b.textContent = old; }, 1200);
    } catch (e) { /* clipboard blocked */ }
  });
}

// ---- sites management ------------------------------------------------
function initSitesManage() {
  $("#add-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("#add-name").value.trim();
    const url = $("#add-url").value.trim();
    const status = $("#sites-status");
    try {
      const r = await fetch("/api/sites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, url }),
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error);
      state.sites = j.sites;
      $("#add-name").value = "";
      $("#add-url").value = "";
      status.hidden = false;
      status.className = "status is-busy";
      status.textContent = `✓ added ${name}`;
      renderSitesManage();
      renderSiteList();
    } catch (err) {
      status.hidden = false;
      status.className = "status is-err";
      status.textContent = `✗ ${err.message}`;
    }
  });
}

function renderSitesManage() {
  const ul = $("#sites-manage");
  ul.innerHTML = state.sites.map((s) => `
    <li>
      <div class="sm-text">
        <div class="sm-name">${escapeHtml(s.name)}</div>
        <div class="sm-url">${escapeHtml(s.url)}</div>
      </div>
      <button class="sm-del" data-url="${escapeHtml(s.url)}">del</button>
    </li>`).join("");

  $$("#sites-manage .sm-del").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`remove this site?\n${btn.dataset.url}`)) return;
      const r = await fetch("/api/sites", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: btn.dataset.url }),
      });
      const j = await r.json();
      if (j.ok) {
        state.sites = j.sites;
        if (state.chosenUrl === btn.dataset.url) {
          state.chosenUrl = "";
          $("#site-chosen").hidden = true;
          refreshGate();
        }
        renderSitesManage();
        renderSiteList();
      }
    });
  });
}

// ---- boot ------------------------------------------------------------
renderBanner();
initTabs();
initModes();
initDrop();
initUpload();
initCopy();
initSitesManage();
populateCtypes();
loadSites();
