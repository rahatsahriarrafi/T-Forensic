"use strict";
const $ = (s, r = document) => r.querySelector(s);
const escapeHtml = (s) => String(s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

function showBusy(title, msg, hint, etaSeconds, progress) {
  const el = $("#busy");
  if (!el) return;
  $("#busy-title").textContent = title || "Working…";
  $("#busy-msg").textContent = msg || "Please wait";
  $("#busy-hint").textContent = hint || "Watch % loaded — ETA is only a rough guess.";
  el.classList.add("show");
  setWorkStatus(title || "Working…");
  if (! _loadStarted) _loadStarted = Date.now();
  if (progress != null && Number.isFinite(Number(progress))) setBusyProgress(progress);
  else if (_loadProgress <= 0) setBusyProgress(null);
  if (etaSeconds != null && Number(etaSeconds) > 0) startBusyEta(etaSeconds);
}
function hideBusy() {
  $("#busy")?.classList.remove("show");
  stopBusyEta();
  _loadProgress = 0;
  _loadStarted = 0;
  const fill = $("#busy-fill");
  const pct = $("#busy-pct");
  if (fill) {
    fill.classList.add("indeterminate");
    fill.style.width = "35%";
  }
  if (pct) pct.textContent = "0%";
  // Keep header chip only if nested withBusy still active
  if (_workDepth <= 0) clearWorkStatus();
}

/** Header loading chip — always visible while work runs */
let _workDepth = 0;
let _busyDelayTimer = null;
function setWorkStatus(text) {
  const el = $("#work-status");
  const tx = $("#work-status-text");
  if (tx) tx.textContent = text || "Working…";
  if (el) el.hidden = false;
  document.body.classList.add("is-working");
}
function clearWorkStatus() {
  const el = $("#work-status");
  if (el) el.hidden = true;
  document.body.classList.remove("is-working");
}
let _cancelFn = null;
function beginWork(label, opts) {
  _workDepth++;
  setWorkStatus(label || "Loading…");
  if (opts && typeof opts.onCancel === "function") _cancelFn = opts.onCancel;
  const delay = opts && opts.overlayDelay != null ? opts.overlayDelay : 220;
  const forceOverlay = opts && opts.overlay === true;
  const open = () => showBusy(
    opts?.title || label || "Working…",
    opts?.message || "Please wait…",
    opts?.hint || "Large files can take a while. You can stop this.",
    opts?.etaSeconds,
    opts?.progress
  );
  if (forceOverlay) {
    open();
    return;
  }
  if (_workDepth === 1 && delay >= 0) {
    clearTimeout(_busyDelayTimer);
    _busyDelayTimer = setTimeout(() => {
      if (_workDepth > 0) open();
    }, delay);
  }
}
function endWork() {
  _workDepth = Math.max(0, _workDepth - 1);
  if (_workDepth === 0) {
    clearTimeout(_busyDelayTimer);
    _busyDelayTimer = null;
    _cancelFn = null;
    hideBusy();
    clearWorkStatus();
  }
}
function stopBusyLoad() {
  const fn = _cancelFn;
  if (fn) fn();
  else hideBusy();
}
async function withBusy(label, fn, opts) {
  beginWork(label, opts || {});
  try {
    return await fn();
  } finally {
    endWork();
  }
}
function loadingHtml(title, msg) {
  return (
    `<div class="loading-box">` +
    `<span class="work-spin" aria-hidden="true"></span>` +
    `<div class="lt">${escapeHtml(title || "Loading…")}</div>` +
    `<div class="lm">${escapeHtml(msg || "Please wait")}</div>` +
    `</div>`
  );
}

let _etaTimer = null;
let _etaStart = 0;
let _etaTotal = 0;
let _loadProgress = 0;
let _loadStarted = 0;
function estimateFileSeconds(size) {
  const n = Number(size) || 0;
  if (n <= 0) return 4;
  // Local evidence read is often slower than disk speed (AD1 inflate, SQLite, ffmpeg).
  return Math.max(2, Math.min(600, Math.round(n / (8 * 1024 * 1024) + 2)));
}
function selectedFileSize() {
  const row = document.querySelector(".node.sel");
  const n = row ? parseInt(row.dataset.size || "", 10) : NaN;
  return Number.isFinite(n) ? n : 0;
}
function fmtEta(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (s < 60) return `~${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m < 60) return r ? `~${m}m ${String(r).padStart(2, "0")}s` : `~${m}m`;
  const h = Math.floor(m / 60);
  return `~${h}h ${String(m % 60).padStart(2, "0")}m`;
}
function setBusyProgress(fraction) {
  const pctEl = $("#busy-pct");
  const fill = $("#busy-fill");
  if (!pctEl || !fill) return;
  if (fraction == null || !Number.isFinite(Number(fraction))) {
    pctEl.textContent = "…";
    fill.classList.add("indeterminate");
    fill.style.width = "35%";
    return;
  }
  const p = Math.max(0, Math.min(1, Number(fraction)));
  if (!(p + 0.001 < _loadProgress && p > 0.02)) _loadProgress = p;
  if (!_loadStarted) _loadStarted = Date.now();
  const pct = Math.round(_loadProgress * 100);
  pctEl.textContent = pct + "%";
  fill.classList.remove("indeterminate");
  fill.style.width = pct + "%";
  if (_loadProgress >= 0.08 && _loadProgress < 0.99) {
    const elapsed = (Date.now() - _loadStarted) / 1000;
    const rem = elapsed * (1 - _loadProgress) / _loadProgress;
    const main = $("#busy-eta-main");
    const sub = $("#busy-eta-sub");
    const box = $("#busy-eta");
    if (main && Number.isFinite(rem)) {
      main.textContent = `~${fmtEta(rem).replace(/^~/, "")} left (from progress)`;
      if (sub) {
        sub.textContent =
          `${pct}% loaded · elapsed ${fmtEta(elapsed).replace(/^~/, "")}` +
          (_etaTotal ? ` · initial guess was ${fmtEta(_etaTotal)}` : "");
      }
      if (box) box.hidden = false;
    }
  }
}
function stopBusyEta() {
  if (_etaTimer) clearInterval(_etaTimer);
  _etaTimer = null;
  _etaTotal = 0;
  const box = $("#busy-eta");
  if (box) box.hidden = true;
}
function tickBusyEta() {
  const main = $("#busy-eta-main");
  const sub = $("#busy-eta-sub");
  const box = $("#busy-eta");
  if (!main || !_etaTotal) return;
  if (_loadProgress >= 0.08) return; // adaptive takes over
  const elapsed = (Date.now() - _etaStart) / 1000;
  const left = Math.max(0, _etaTotal - elapsed);
  if (left <= 0 && elapsed > _etaTotal) {
    main.textContent = "Longer than the estimate";
    if (sub) sub.textContent = `Elapsed ${fmtEta(elapsed).replace(/^~/, "")}. Use × to stop.`;
  } else {
    main.textContent = `About ${fmtEta(left)} left`;
    if (sub) sub.textContent = `Elapsed ${fmtEta(elapsed).replace(/^~/, "")}`;
  }
  if (box) box.hidden = false;
}
function startBusyEta(seconds) {
  const sec = Number(seconds);
  if (!Number.isFinite(sec) || sec <= 0) return;
  _etaTotal = sec;
  _etaStart = Date.now();
  if (!_loadStarted) _loadStarted = Date.now();
  tickBusyEta();
  if (_etaTimer) clearInterval(_etaTimer);
  _etaTimer = setInterval(tickBusyEta, 1000);
}
function toast({ title, message, suggestion, kind } = {}) {
  const box = $("#toast");
  if (!box) return;
  const el = document.createElement("div");
  el.className = "toast" + (kind === "err" ? " err" : "");
  el.innerHTML =
    `<button class="tx" type="button" aria-label="Dismiss">×</button>` +
    `<div class="tt"></div><div class="tm"></div><div class="ts"></div>`;
  el.querySelector(".tt").textContent = title || (kind === "err" ? "Error" : "Notice");
  el.querySelector(".tm").textContent = message || "";
  const sug = el.querySelector(".ts");
  if (suggestion) sug.textContent = "Try: " + suggestion;
  else sug.remove();
  el.querySelector(".tx").onclick = () => el.remove();
  box.appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 12000 : 5000);
}
function errHtml(d) {
  const title = escapeHtml(d.title || "Error");
  const msg = escapeHtml(d.error || d.message || "Something went wrong");
  const sug = d.suggestion ? `<div class="es">${escapeHtml(d.suggestion)}</div>` : "";
  return `<div class="err-block"><div class="et">${title}</div><div class="em">${msg}</div>${sug}</div>`;
}
function notifyError(d, fallbackTitle) {
  toast({
    title: d.title || fallbackTitle || "Error",
    message: d.error || d.message || String(d),
    suggestion: d.suggestion || "",
    kind: "err",
  });
}

let _depsHidden = false;
let _depsTimer = null;

function renderDepsBanner(report) {
  const box = $("#deps-banner");
  if (!box) return;
  const missing = (report && report.missing) || [];
  if (_depsHidden || !missing.length) {
    box.hidden = true;
    return;
  }
  const title = $("#deps-title");
  const list = $("#deps-list");
  if (title) {
    title.textContent = `${missing.length} tool${missing.length === 1 ? "" : "s"} missing — install to unlock features`;
  }
  if (list) {
    list.innerHTML = "";
    missing.slice(0, 8).forEach((m) => {
      const row = document.createElement("div");
      row.className = "deps-row";
      row.innerHTML =
        `<div><b>${escapeHtml(m.name || m.id)}</b> — ${escapeHtml(m.feature || "")}</div>` +
        `<code>${escapeHtml(m.suggestion || "")}</code>`;
      list.appendChild(row);
    });
    const cmds = (((report || {}).install || {}).commands) || [];
    if (cmds.length) {
      const all = document.createElement("div");
      all.className = "deps-row";
      all.innerHTML = `<div><b>All at once</b></div><code>${escapeHtml(cmds[cmds.length - 1] || cmds[0])}</code>`;
      list.appendChild(all);
    }
  }
  box.hidden = false;
}

async function refreshDeps({ toastOnMissing } = {}) {
  try {
    const report = await api("/api/deps");
    renderDepsBanner(report);
    if (toastOnMissing && report && report.counts && report.counts.missing) {
      const first = (report.missing || [])[0];
      toast({
        title: "Setup incomplete",
        message: report.summary || `${report.counts.missing} tools missing`,
        suggestion: (first && first.suggestion) || "Run: tforensic deps",
        kind: "err",
      });
    }
    return report;
  } catch (_) {
    return null;
  }
}

function startDepsWatch() {
  refreshDeps({ toastOnMissing: true });
  if (_depsTimer) clearInterval(_depsTimer);
  // Continuous: re-check every 45s so install suggestions clear once fulfilled
  _depsTimer = setInterval(() => refreshDeps({ toastOnMissing: false }), 45000);
  const btnR = $("#deps-refresh");
  const btnD = $("#deps-dismiss");
  if (btnR) btnR.onclick = () => { _depsHidden = false; refreshDeps({ toastOnMissing: true }); };
  if (btnD) btnD.onclick = () => { _depsHidden = true; const b = $("#deps-banner"); if (b) b.hidden = true; };
}

const api = (p, opts) => fetch(p, opts).then(async (r) => {
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    const data = await r.json();
    if (!r.ok && data && (data.error || data.title)) {
      data.__http = r.status;
      return data;
    }
    return data;
  }
  if (!r.ok) {
    return {
      error: `Request failed (${r.status})`,
      title: "Request failed",
      suggestion: "Retry the action. If it continues, restart tforensic serve.",
    };
  }
  return r;
});
const fmtSize = (n) => {
  const u = ["B", "K", "M", "G", "T"]; let i = 0; let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (i ? v.toFixed(1) : v) + u[i];
};

let selPath = null;
let browseDir = null; // folder scope for grep / search
let navHistory = [];  // previous paths for Back
let navSuppress = false;
let sqliteFilterFn = null; // active SQLite in-table filter hook
let sqliteClearFilter = null;
let curView = "text";

function makeNode(node) {
  const li = document.createElement("li");
  const row = document.createElement("div");
  row.className = "node " + (node.is_dir ? "dir" : "file");
  row.dataset.path = node.path;
  if (node.size != null) row.dataset.size = String(node.size);
  const tw = node.is_dir ? "▸" : " ";
  row.innerHTML = `<span class="tw">${tw}</span><span class="lbl"></span>` +
    (node.is_dir ? "" : `<span class="sz">${fmtSize(node.size || 0)}</span>`);
  row.querySelector(".lbl").textContent = node.name;
  li.appendChild(row);

  if (node.is_dir) {
    const ul = document.createElement("ul");
    ul.className = "tree children";
    li.appendChild(ul);
    let built = false;
    let loading = false;
    row.addEventListener("click", async () => {
      const open = ul.classList.toggle("open");
      row.querySelector(".tw").textContent = open ? "▾" : "▸";
      if (!open) return;
      if (built) return;
      const needsLazy = node.lazy || (node.path && String(node.path).match(/^(part|inode):/));
      const hasKids = (node.children || []).length > 0;
      if (needsLazy && !hasKids) {
        if (loading) return;
        loading = true;
        ul.innerHTML = `<li><div class="node muted">⏳ loading folder…</div></li>`;
        beginWork("Loading folder…", {
          title: "Loading folder",
          message: node.name || node.path,
          hint: "Reading directory entries (fls / tree).",
          overlayDelay: 150,
        });
        try {
          const d = await api("/api/tree?path=" + encodeURIComponent(node.path));
          ul.innerHTML = "";
          if (d.error) {
            ul.innerHTML = `<li><div class="node muted">${escapeHtml(d.error)}</div></li>`;
            notifyError(d, "Tree browse failed");
            return;
          }
          const kids = d.children || [];
          if (!kids.length) {
            ul.innerHTML = `<li><div class="node muted">(empty)</div></li>`;
          } else {
            kids.forEach((c) => ul.appendChild(makeNode(c)));
          }
          built = true;
        } catch (e) {
          ul.innerHTML = `<li><div class="node muted">${escapeHtml(e.message || e)}</div></li>`;
        } finally {
          loading = false;
          endWork();
        }
        return;
      }
      (node.children || []).forEach((c) => ul.appendChild(makeNode(c)));
      built = true;
    });
  } else {
    row.addEventListener("click", () => selectFile(node.path, row));
  }
  return li;
}

async function loadTree() {
  await withBusy("Loading tree…", async () => {
    const root = await api("/api/tree");
    const ul = document.createElement("ul");
    ul.className = "tree root";
    ul.appendChild(makeNode(root));
    $("#tree").innerHTML = "";
    $("#tree").appendChild(ul);
    $("#tree").querySelector(".node")?.click();
  }, { title: "Loading tree", message: "Building file tree", overlayDelay: 120 });
}

async function loadInfo() {
  const info = await api("/api/info");
  if (info.error) {
    $("#info").textContent = info.error || "No triage image — use Case tab";
    return;
  }
  const kind = info.kind || "ad1";
  if (kind === "case") {
    $("#info").textContent = `Case ${info.name || info.id} · ${JSON.stringify(info.stats || {})}`;
    const pill = $("#session-pill");
    if (pill) pill.textContent = `case ${info.id}`;
    return;
  }
  if (kind === "pcap") {
    $("#info").textContent =
      `${info.image} — packet capture · ${info.tshark ? "tshark" : "native"}`;
    const pill = $("#session-pill");
    if (pill) pill.textContent = `session ${info.session_id} · pcap`;
    $("#detail-body").innerHTML =
      `<div class="enc">Network / PCAP mode</div>` +
      `<pre>Capture: ${escapeHtml(info.pcap_path || info.image_path)}\n` +
      `Engine:  ${info.tshark ? "tshark (Wireshark)" : "native PCAP"}\n\n` +
      `Use the Network tab for packet list, display filters, protocols, DNS/HTTP.</pre>`;
    // Auto-open Network workspace
    const path = info.pcap_path || info.image_path;
    if (path && $("#pcap-path")) {
      $("#pcap-path").value = path;
      document.querySelector('.tab[data-pane="network"]')?.click();
      // ensure capture is active (serve already opened it)
      await refreshPcapStatus();
      await loadPcapPackets(true);
      const sum = await api("/api/pcap/summary");
      if (!sum.error) renderPcapStats(sum);
    }
    return;
  }
  if (kind === "disk" || kind === "ova") {
    const xm = info.xmount || {};
    const label = kind === "ova" ? "ova" : "disk";
    $("#info").textContent =
      `${info.image} — ${label}/${xm.input_type || "?"}→${xm.output_type || "raw"}  ·  mount ${xm.id || ""}`;
    let extra = "";
    if (info.ova) {
      extra = `\nOVA disk: ${info.ova.primary_disk || ""}\nMountable: ${info.ova.mount_path || ""}`;
    }
    $("#detail-body").innerHTML =
      `<div class="enc">${label} mode · xmount</div>` +
      `<pre>Image:  ${info.image_path}\nDevice: ${xm.virtual_device || ""}\nMount:  ${xm.id || ""}${extra}\n\n` +
      `Tree tab: expand image → partition → folders → click a file to preview.\n` +
      `Disk tab: alternate fls / icat browse.</pre>`;
  } else {
    $("#info").textContent =
      `${info.image} — ${info.root}  ·  ${info.dirs} dirs, ${info.files} files`;
  }
  const pill = $("#session-pill");
  if (pill) pill.textContent = `session ${info.session_id}` + (kind === "disk" || kind === "ova" ? ` · ${kind}` : "");
}

function parentDirOf(path) {
  if (!path) return null;
  const p = String(path);
  if (p.startsWith("inode:")) {
    // inode:offset:inode:name → stay on partition folder part:offset
    const parts = p.split(":");
    if (parts.length >= 2) return `part:${parts[1]}`;
    return null;
  }
  const i = p.lastIndexOf("/");
  if (i <= 0) return p.includes("/") ? "/" : null;
  return p.slice(0, i) || "/";
}

function updateNavChrome() {
  const back = $("#btn-nav-back");
  const grep = $("#btn-folder-grep");
  const search = $("#search");
  const insideQ = $("#inside-q");
  const scopeEl = $("#inside-scope");
  if (back) back.disabled = navHistory.length === 0;
  if (grep) grep.disabled = false;
  if (search) {
    search.classList.remove("scoped");
    search.placeholder = "Search whole image — Enter / Search…";
  }
  let scopeLabel = "current folder / view";
  let insidePh = "Inside — current folder or view…";
  if (sqliteFilterFn && document.querySelector(".sqlite-browser")) {
    scopeLabel = "this SQLite table";
    insidePh = "Inside — filter this table…";
  } else if (browseDir) {
    scopeLabel = browseDir.length > 36 ? "…" + browseDir.slice(-34) : browseDir;
    insidePh = "Inside — this folder (name + content)…";
  } else if (selPath) {
    scopeLabel = "parent folder / image";
    insidePh = "Inside — nearby folder or image…";
  }
  if (insideQ) insideQ.placeholder = insidePh;
  if (scopeEl) {
    scopeEl.textContent = scopeLabel;
    scopeEl.title = browseDir || selPath || "folder / view";
  }
}

function focusEl(el, caret) {
  if (!el) return;
  requestAnimationFrame(() => {
    el.focus();
    try {
      const n = typeof caret === "number" ? caret : el.value.length;
      el.setSelectionRange(n, n);
    } catch (_) {}
  });
}

/** Top bar: always whole-image search (never folder/table scoped). */
function submitGlobalSearch() {
  const s = $("#search");
  const q = (s && s.value.trim()) || "";
  const caret = s && typeof s.selectionStart === "number" ? s.selectionStart : null;
  const done = runGlobalSearch(q);
  Promise.resolve(done).finally(() => focusEl(s, caret));
}

/** Below INSIDE bar: SQLite table / current folder / nearby scope. */
function submitInsideSearch() {
  const s = $("#inside-q") || $("#search");
  const q = (($("#inside-q") && $("#inside-q").value.trim()) || "");
  const caret = s && typeof s.selectionStart === "number" ? s.selectionStart : null;
  if (sqliteFilterFn && document.querySelector(".sqlite-browser")) {
    runSearch(q); // filters open table
    focusEl($("#inside-q"), caret);
    return;
  }
  const done = q ? runFolderGrep(q) : Promise.resolve();
  Promise.resolve(done).finally(() => focusEl($("#inside-q"), caret));
}

function setDetailHead(path, name) {
  const head = $("#detail-head");
  if (!head) return;
  head.innerHTML =
    `<div class="detail-head-row">` +
    `<div><div class="path">${escapeHtml(path)}</div>` +
    `<div class="sub">${escapeHtml(name || "")}` +
    (browseDir ? ` · folder scope: <code>${escapeHtml(browseDir)}</code>` : "") +
    `</div></div>` +
    `<div class="detail-head-actions">` +
    `<button type="button" id="btn-head-back" ${navHistory.length ? "" : "disabled"}>← Back</button>` +
    `<button type="button" id="btn-head-grep">Inside search</button>` +
    `</div></div>`;
  const hb = $("#btn-head-back");
  const hg = $("#btn-head-grep");
  if (hb) hb.onclick = () => goBack();
  if (hg) hg.onclick = () => {
    const iq = $("#inside-q");
    if (iq) {
      iq.focus();
      if (!iq.value.trim()) promptFolderGrep();
      else submitInsideSearch();
    } else {
      promptFolderGrep();
    }
  };
  updateNavChrome();
}

async function goBack() {
  if (!navHistory.length) return;
  const prev = navHistory.pop();
  navSuppress = true;
  updateNavChrome();
  await selectFile(prev, null);
  navSuppress = false;
  updateNavChrome();
}

function promptFolderGrep() {
  const iq = $("#inside-q");
  const q = (iq && iq.value.trim()) || "";
  if (sqliteFilterFn && document.querySelector(".sqlite-browser")) {
    const term = q || window.prompt("Inside search — this SQLite table:", "") || "";
    if (iq) iq.value = term;
    sqliteFilterFn(String(term).trim());
    focusEl(iq);
    return;
  }
  const term = q || window.prompt("Inside search (current folder):", "");
  if (term == null) return;
  const t = String(term).trim();
  if (!t) return;
  if (iq) iq.value = t;
  runFolderGrep(t);
}

/** Whole-image filename search — ignores folder / SQLite scope. */
async function runGlobalSearch(q) {
  if (!q) {
    hideHitPanel();
    return;
  }
  await withBusy("Searching whole image…", async () => {
    const d = await api(`/api/search?q=${encodeURIComponent(q)}`);
    const items = (d.results || []).map((r) => ({
      name: r.name,
      path: r.path,
      htmlName: highlightTerm(r.name || "", q),
      is_dir: !!r.is_dir,
      size: r.size,
    }));
    showHitPanel({
      title: "Whole-image matches",
      sub: `${d.count || 0} hits across the image (tree kept open)`,
      items,
      onPick: (it) => selectFile(it.path, null),
    });
  }, { title: "Search whole image", message: q, overlayDelay: 80 });
}

async function runSearch(q) {
  if (!q) {
    hideHitPanel();
    if (sqliteClearFilter) sqliteClearFilter();
    return;
  }
  // Inside path: SQLite table filter only (top bar never calls this for global)
  if (sqliteFilterFn && document.querySelector(".sqlite-browser")) {
    sqliteFilterFn(q);
    return;
  }
  const under = browseDir;
  const url = under
    ? `/api/search?q=${encodeURIComponent(q)}&under=${encodeURIComponent(under)}`
    : `/api/search?q=${encodeURIComponent(q)}`;
  await withBusy(under ? "Searching folder…" : "Searching…", async () => {
    const d = await api(url);
    const items = (d.results || []).map((r) => ({
      name: r.name,
      path: r.path,
      htmlName: highlightTerm(r.name || "", q),
      is_dir: !!r.is_dir,
      size: r.size,
    }));
    showHitPanel({
      title: under ? "Folder matches" : "Filename matches",
      sub: under
        ? `${d.count || 0} hits under ${under} (tree kept open)`
        : `${d.count || 0} hits in image (tree kept open)`,
      items,
      onPick: (it) => selectFile(it.path, null),
    });
  }, { title: "Search", message: q, overlayDelay: 80 });
}

async function runFolderGrep(q) {
  if (!q) return;
  if (sqliteFilterFn && document.querySelector(".sqlite-browser")) {
    sqliteFilterFn(q);
    return;
  }
  const under = browseDir || parentDirOf(selPath) || null;
  await withBusy(under ? "Inside search…" : "Inside search (image)…", async () => {
    const url = under
      ? `/api/grep?q=${encodeURIComponent(q)}&under=${encodeURIComponent(under)}`
      : `/api/grep?q=${encodeURIComponent(q)}`;
    const d = await api(url);
    if (d.error) {
      notifyError(d);
      return;
    }
    const items = (d.hits || []).map((h) => ({
      name: h.name,
      path: h.path,
      snippet: h.snippet,
      htmlName: (h.kind === "content" ? "⌕ " : "") + highlightTerm(h.name || "", q),
      htmlSnippet: h.snippet ? highlightTerm(h.snippet, q) : "",
      kind: h.kind,
    }));
    showHitPanel({
      title: "Inside search results",
      sub: under
        ? `“${q}” in ${under} · ${d.count || 0} hits · tree unchanged`
        : `“${q}” · ${d.count || 0} hits · tree unchanged`,
      items,
      onPick: (it) => selectFile(it.path, null),
    });
  }, { title: "Inside search", message: under || "image", overlayDelay: 80 });
}

function formatAd1Timestamp(raw) {
  const m = String(raw || "").trim().match(
    /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(?:\.(\d+))?$/
  );
  if (!m) return null;
  return `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]} UTC`;
}

const AD1_ATTR_NAMES = {
  2: "Item type",
  3: "Logical size",
  4: "Physical size",
  7: "Accessed",
  8: "Modified",
  9: "Created",
  13: "Compressed",
  14: "Encrypted",
  30: "Has integrity hash",
  4097: "DOS 8.3 name",
  4098: "Is directory",
  4099: "Is deleted",
  4100: "Is unused",
  4101: "Is allocated",
  20481: "MD5",
  20482: "SHA-1",
  40961: "MFT entry",
  40962: "MFT modified",
  40963: "NTFS in use",
  40964: "NTFS directory",
  40965: "NTFS deleted flag",
  40966: "NTFS unused flag",
  40967: "Owner SID",
  40968: "Owner name",
  40969: "Group SID",
  40970: "Group name",
  40988: "SI Created",
  40989: "SI Modified",
  40990: "SI MFT changed",
  40991: "SI Accessed",
  41000: "File name",
  41001: "FN logical size",
  41002: "FN physical size",
  41003: "FN Created",
  41004: "FN Modified",
  41005: "FN MFT changed",
  41006: "FN Accessed",
  41007: "FN DOS name",
};

function ad1AttrLabel(key) {
  const k = +key;
  if (Number.isFinite(k) && AD1_ATTR_NAMES[k]) return AD1_ATTR_NAMES[k];
  if (Number.isFinite(k) && k >= 0x01000000) {
    const slot = Math.floor((k - 0x01000000) / 0x1000);
    const field = (k - 0x01000000) % 0x1000;
    const fields = {
      4: "ACE SID",
      5: "ACE account",
      6: "ACE access mask",
      7: "ACE: read",
      8: "ACE: write",
      9: "ACE: execute",
      10: "ACE: delete",
    };
    return `ACL[${slot}] ${fields[field] || ("field " + field)}`;
  }
  return Number.isFinite(k) ? `Attribute ${k}` : String(key);
}

function formatMetaRows(attrs, serverRows) {
  if (serverRows && serverRows.length) return serverRows;
  return Object.entries(attrs || {}).map(([k, v]) => {
    const raw = v == null ? "" : String(v);
    const ts = formatAd1Timestamp(raw);
    let kind = "text";
    if (ts) kind = "time";
    else if (raw.startsWith("S-1-")) kind = "sid";
    else if (/^[0-9a-fA-F]{32}$/.test(raw) || /^[0-9a-fA-F]{40}$/.test(raw)) kind = "hash";
    else if (/^(true|false)$/i.test(raw)) kind = "bool";
    return {
      key: String(k),
      label: ad1AttrLabel(k),
      raw,
      display: ts ? `${ts}  |  ${raw}` : raw,
      kind,
    };
  }).sort((a, b) => {
    const p = { time: 0, sid: 1, hash: 2, text: 3, bool: 4 };
    return (p[a.kind] ?? 9) - (p[b.kind] ?? 9) || a.label.localeCompare(b.label);
  });
}

function renderMetaTable(d, body) {
  body.innerHTML = "";
  if (d.recycle && d.recycle.deleted_utc) {
    const box = document.createElement("div");
    box.className = "meta-highlight";
    box.innerHTML =
      `<div class="mh-title">Recycle Bin — deleted file</div>` +
      `<div class="mh-row"><span class="k">Deleted (UTC)</span>` +
      `<span class="v timeish">${escapeHtml(d.recycle.deleted_utc)}</span></div>` +
      `<div class="mh-row"><span class="k">Original path</span>` +
      `<span class="v">${escapeHtml(d.recycle.original_path || "")}</span></div>` +
      `<div class="mh-row"><span class="k">Original size</span>` +
      `<span class="v">${escapeHtml(String(d.recycle.original_size ?? ""))}</span></div>`;
    body.appendChild(box);
  }
  const rows = formatMetaRows(d.attrs, d.rows);
  if (!rows.length) {
    body.innerHTML += `<pre class="muted">no metadata</pre>`;
    return;
  }
  const hint = document.createElement("div");
  hint.className = "meta-hint";
  hint.textContent = "Readable metadata · times in UTC · hover row for full value · ACL = permission entries";
  body.appendChild(hint);
  const table = document.createElement("table");
  table.className = "meta meta-readable";
  table.innerHTML = "<tr><th>Field</th><th>Value</th><th class=\"dim\">ID</th></tr>";
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.className = "meta-" + (r.kind || "text");
    const val = r.display || r.raw || "";
    tr.innerHTML =
      `<td class="k">${escapeHtml(r.label || r.key)}</td>` +
      `<td class="v" title="${escapeHtml(r.raw || val)}">${escapeHtml(val)}</td>` +
      `<td class="dim" title="${escapeHtml(r.key)}">${escapeHtml(r.key)}</td>`;
    table.appendChild(tr);
  });
  body.appendChild(table);
}

async function selectFile(path, rowEl) {
  if (!navSuppress && selPath && selPath !== path) {
    navHistory.push(selPath);
    if (navHistory.length > 40) navHistory.shift();
  }
  selPath = path;
  browseDir = parentDirOf(path);
  updateNavChrome();
  document.querySelectorAll(".node.sel").forEach((e) => e.classList.remove("sel"));
  if (rowEl) rowEl.classList.add("sel");
  const name = path.split("/").pop() || path.split(":").pop() || path;
  // Tell desktop shell which file is selected (for Terminal → open here)
  try {
    window.parent.postMessage({
      type: "tff-selected",
      path,
      name,
      isDir: false,
    }, "*");
  } catch (_) {}
  setDetailHead(path, name);
  const dl = $("#dl");
  const isDiskInode = String(path).startsWith("inode:");
  if (dl) {
    dl.hidden = isDiskInode;
    if (!isDiskInode) dl.href = "/api/download?path=" + encodeURIComponent(path);
  }
  const ex = $("#export-btn");
  if (ex) ex.hidden = isDiskInode;
  curView = "text";
  await renderView("text");
}

let _fileAbort = null;
function isAbort(e) {
  return !!(e && (e.name === "AbortError" || /aborted/i.test(String(e.message || ""))));
}
function startFileLoad() {
  if (_fileAbort) _fileAbort.abort();
  _fileAbort = new AbortController();
  return _fileAbort;
}
async function renderView(view) {
  curView = view;
  document.querySelectorAll(".dtab[data-view]").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view));
  if (!selPath) return;
  // Leaving a previous SQLite preview — drop in-table filter hooks
  sqliteFilterFn = null;
  sqliteClearFilter = null;
  updateNavChrome();
  const body = $("#detail-body");
  const label = view === "hex" ? "Hex view" : view === "meta" ? "Metadata" : view === "hash" ? "Hashes" : "Preview";
  const ac = startFileLoad();
  const bytes = selectedFileSize();
  body.innerHTML = loadingHtml(label + "…", selPath);
  beginWork(`${label}…`, {
    title: label,
    message: selPath,
    hint: "Reading file from the evidence image. Use × to stop.",
    overlayDelay: 200,
    etaSeconds: estimateFileSeconds(bytes),
    onCancel: () => ac.abort(),
  });
  try {
    const pe = encodeURIComponent(selPath);
    if (view === "text" || view === "hex") {
      const mode = view === "hex" ? "hex" : "auto";
      const d = await api(`/api/file?path=${pe}&mode=${mode}`, { signal: ac.signal });
      if (d.error) {
        body.innerHTML = errHtml(d);
        notifyError(d);
        return;
      }
      renderAccessor(d, body);
      return;
    }
    if (view === "meta") {
      const d = await api(`/api/meta?path=${pe}`, { signal: ac.signal });
      if (d.error) {
        body.innerHTML = errHtml(d);
        notifyError(d);
        return;
      }
      renderMetaTable(d, body);
      return;
    }
    if (view === "hash") {
      const d = await api(`/api/hash?path=${pe}`, { signal: ac.signal });
      if (d.error) {
        body.innerHTML = errHtml(d);
        notifyError(d);
        return;
      }
      const exe = d.executable ? `<span class="badge">PE / executable (MZ)</span>` : "";
      body.innerHTML =
        `<div>${exe}</div>` +
        `<pre>MD5     ${d.md5}\nSHA-1   ${d.sha1}\nSHA-256 ${d.sha256}\nSize    ${d.size} (${fmtSize(d.size)})</pre>`;
    }
  } catch (e) {
    if (isAbort(e)) {
      if (_fileAbort === ac) body.innerHTML = `<pre class="muted">Stopped.</pre>`;
      return;
    }
    body.innerHTML = errHtml({ error: String(e.message || e), title: "Load failed" });
  } finally {
    if (_fileAbort === ac) _fileAbort = null;
    endWork();
  }
}

function hideCellPop() {
  const pop = $("#sqlite-cell-pop");
  if (pop) pop.hidden = true;
}

function showCellPop(col, text) {
  let pop = $("#sqlite-cell-pop");
  if (!pop) {
    pop = document.createElement("div");
    pop.id = "sqlite-cell-pop";
    pop.className = "sqlite-cell-pop";
    pop.hidden = true;
    pop.innerHTML =
      `<div class="scp-card">` +
      `<div class="scp-head"><strong id="scp-title">Cell</strong>` +
      `<div class="scp-actions">` +
      `<button type="button" id="scp-copy">Copy</button>` +
      `<button type="button" id="scp-close">Close</button>` +
      `</div></div>` +
      `<pre class="scp-body" id="scp-body"></pre></div>`;
    document.body.appendChild(pop);
    pop.addEventListener("click", (e) => {
      if (e.target === pop) hideCellPop();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") hideCellPop();
    });
  }
  const tit = $("#scp-title");
  const body = $("#scp-body");
  const copyBtn = $("#scp-copy");
  const closeBtn = $("#scp-close");
  if (tit) tit.textContent = col || "Full value";
  if (body) body.textContent = text == null ? "" : String(text);
  if (copyBtn) {
    copyBtn.onclick = async () => {
      try {
        await navigator.clipboard.writeText(String(text ?? ""));
        toast({ title: "Copied", message: col || "cell", kind: "ok" });
      } catch (_) {
        // fallback select
        if (body) {
          const range = document.createRange();
          range.selectNodeContents(body);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
        }
      }
    };
  }
  if (closeBtn) closeBtn.onclick = () => hideCellPop();
  pop.hidden = false;
}

function highlightTerm(text, term) {
  const s = String(text ?? "");
  if (!term) return escapeHtml(s);
  const t = String(term);
  const low = s.toLowerCase();
  const needle = t.toLowerCase();
  let out = "";
  let i = 0;
  while (i < s.length) {
    const j = low.indexOf(needle, i);
    if (j < 0) {
      out += escapeHtml(s.slice(i));
      break;
    }
    out += escapeHtml(s.slice(i, j));
    out += `<mark class="hit">${escapeHtml(s.slice(j, j + t.length))}</mark>`;
    i = j + t.length;
  }
  return out;
}

function showHitPanel({ title, sub, items, onPick }) {
  const panel = $("#hit-panel");
  const list = $("#hit-list");
  const tit = $("#hit-title");
  const subEl = $("#hit-sub");
  if (!panel || !list) return;
  if (tit) tit.textContent = title || "Search results";
  if (subEl) subEl.textContent = sub || "";
  list.innerHTML = "";
  if (!items || !items.length) {
    list.innerHTML = `<pre class="muted" style="padding:12px">No matches.</pre>`;
  } else {
    items.forEach((it) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "hit-item";
      btn.innerHTML =
        `<div class="hn">${it.htmlName || escapeHtml(it.name || it.path || "")}</div>` +
        (it.path ? `<div class="hp">${escapeHtml(it.path)}</div>` : "") +
        (it.snippet ? `<div class="hs">${it.htmlSnippet || escapeHtml(it.snippet)}</div>` : "");
      btn.onclick = () => {
        panel.hidden = true;
        if (onPick) onPick(it);
      };
      list.appendChild(btn);
    });
  }
  panel.hidden = false;
}

function hideHitPanel() {
  const panel = $("#hit-panel");
  if (panel) panel.hidden = true;
}

function renderSqliteBrowser(d, body) {
  const wrap = document.createElement("div");
  wrap.className = "sqlite-browser";

  const tables = d.tables || d.items || [];
  let active = d.active_table || (tables[0] && (tables[0].name || tables[0])) || null;
  let offset = 0;
  const limit = 100;
  let lastPayload = null;
  let filterTerm = "";

  const side = document.createElement("div");
  side.className = "sqlite-side";
  const main = document.createElement("div");
  main.className = "sqlite-main";
  wrap.appendChild(side);
  wrap.appendChild(main);
  body.appendChild(wrap);

  const title = document.createElement("div");
  title.className = "sqlite-side-title";
  title.textContent = `Tables (${tables.length})`;
  side.appendChild(title);

  const list = document.createElement("div");
  list.className = "sqlite-table-list";
  side.appendChild(list);

  function formatTimeCell(text, term) {
    // "HUMAN  |  kind:RAW"
    const m = String(text).match(
      /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\s+\|\s+((?:webkit|unix(?:-ms|-us)?):\d+)$/
    );
    if (!m) return null;
    const human = term ? highlightTerm(m[1], term) : escapeHtml(m[1]);
    const raw = term ? highlightTerm(m[2], term) : escapeHtml(m[2]);
    return `<span class="t-human">${human}</span>` +
      `<span class="t-raw">| ${raw}</span>`;
  }

  function paintRows(payload, opts = {}) {
    const activeEl = document.activeElement;
    const keepTopSearch = activeEl && activeEl.id === "search";
    const keepInside = activeEl && activeEl.id === "inside-q";
    const keepFilter =
      !!opts.focusFilter ||
      (activeEl && activeEl.closest && activeEl.closest(".sqlite-filter-bar"));
    const caret =
      opts.caret != null
        ? opts.caret
        : activeEl && typeof activeEl.selectionStart === "number"
          ? activeEl.selectionStart
          : null;

    lastPayload = payload;
    main.innerHTML = "";
    const filterBar = document.createElement("div");
    filterBar.className = "sqlite-filter-bar";
    const fin = document.createElement("input");
    fin.type = "search";
    fin.placeholder = "Inside table — Enter searches ALL rows (try @ or proton)…";
    fin.value = filterTerm;
    const countEl = document.createElement("span");
    countEl.className = "hit-count";
    filterBar.appendChild(fin);
    // Quick chips for common forensic hunts (Q6 email / mail)
    const chips = document.createElement("div");
    chips.className = "sqlite-chips";
    [
      ["@", "Emails (@)"],
      ["proton", "ProtonMail"],
      ["mail", "mail"],
      ["http", "http"],
    ].forEach(([term, label]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "sqlite-chip";
      b.textContent = label;
      b.title = `Search whole table for “${term}”`;
      b.onclick = () => {
        filterTerm = term;
        if ($("#inside-q")) $("#inside-q").value = term;
        searchEntireTable(term);
      };
      chips.appendChild(b);
    });
    filterBar.appendChild(chips);
    filterBar.appendChild(countEl);
    main.appendChild(filterBar);

    const bar = document.createElement("div");
    bar.className = "sqlite-toolbar";
    const total = payload.total != null ? payload.total : "?";
    const isSearch = payload.mode === "search" || !!payload.search;
    const end = isSearch
      ? payload.returned
      : payload.offset + payload.returned;
    bar.innerHTML =
      `<strong>${escapeHtml(payload.table || active || "")}</strong>` +
      `<span class="muted">${isSearch
        ? `${payload.returned} match${payload.returned === 1 ? "" : "es"} for “${escapeHtml(payload.search || filterTerm)}” · of ${total}`
        : `${payload.returned} rows · ${payload.offset + 1}–${end} of ${total}`}</span>`;
    const prev = document.createElement("button");
    prev.type = "button";
    prev.textContent = "◀ Prev";
    prev.disabled = isSearch || offset <= 0;
    prev.onclick = () => {
      offset = Math.max(0, offset - limit);
      loadTable(active);
    };
    const next = document.createElement("button");
    next.type = "button";
    next.textContent = "Next ▶";
    next.disabled = isSearch || (payload.total != null
      ? offset + limit >= payload.total
      : payload.returned < limit);
    next.onclick = () => {
      offset += limit;
      loadTable(active);
    };
    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.textContent = "Clear search";
    clearBtn.disabled = !isSearch && !filterTerm;
    clearBtn.onclick = () => {
      filterTerm = "";
      if ($("#inside-q")) $("#inside-q").value = "";
      offset = 0;
      loadTable(active);
    };
    const schemaBtn = document.createElement("button");
    schemaBtn.type = "button";
    schemaBtn.textContent = "Schema";
    schemaBtn.onclick = () => showSchema(active);
    bar.appendChild(prev);
    bar.appendChild(next);
    bar.appendChild(clearBtn);
    bar.appendChild(schemaBtn);
    main.appendChild(bar);

    if (!payload.columns || !payload.columns.length) {
      const empty = document.createElement("pre");
      empty.className = "muted";
      empty.textContent = "No columns / empty table.";
      main.appendChild(empty);
      return;
    }
    const table = document.createElement("table");
    table.className = "meta data sqlite-grid";
    const thead = document.createElement("tr");
    payload.columns.forEach((c) => {
      const th = document.createElement("th");
      th.textContent = c;
      thead.appendChild(th);
    });
    table.appendChild(thead);

    const term = filterTerm.trim();
    const termL = term.toLowerCase();
    let hitCount = 0;
    (payload.rows || []).forEach((row) => {
      const rowText = row.map((c) => (c == null ? "" : String(c))).join(" ").toLowerCase();
      const isHit = termL && rowText.includes(termL);
      if (isHit) hitCount += 1;
      // When filtering, hide non-matches; when empty filter, show all
      if (termL && !isHit) return;
      const tr = document.createElement("tr");
      if (isHit) tr.classList.add("hit-row");
      row.forEach((cell, i) => {
        const td = document.createElement("td");
        const text = cell == null ? "NULL" : String(cell);
        const timeHtml = formatTimeCell(text, termL ? term : "");
        if (cell == null) {
          td.className = "null";
          td.textContent = "NULL";
        } else if (text.startsWith("BLOB(")) {
          td.className = "blob";
          td.innerHTML = termL ? highlightTerm(text, term) : escapeHtml(text);
        } else if (timeHtml) {
          td.className = "timeish";
          td.innerHTML = timeHtml;
        } else {
          const colL = ((payload.columns || [])[i] || "").toLowerCase();
          if (colL.includes("url") || colL.includes("title") || colL.includes("path") || text.length > 48) {
            td.classList.add("wide-col");
          }
          td.innerHTML = termL ? highlightTerm(text, term) : escapeHtml(text);
        }
        const col = (payload.columns || [])[i] || "";
        const full = cell == null ? "NULL" : String(cell);
        td.title = full;
        td.onclick = (e) => {
          e.stopPropagation();
          document.querySelectorAll(".sqlite-grid td.cell-open").forEach((x) => x.classList.remove("cell-open"));
          td.classList.add("cell-open");
          showCellPop(col, full);
        };
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    countEl.textContent = termL
      ? (payload.mode === "search"
        ? `${payload.returned} in whole table (red)`
        : `${hitCount} on this page (red)`)
      : "";
    const scroller = document.createElement("div");
    scroller.className = "sqlite-scroll";
    scroller.appendChild(table);
    main.appendChild(scroller);

    fin.onkeydown = (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      filterTerm = fin.value.trim();
      if ($("#inside-q")) $("#inside-q").value = filterTerm;
      if (!filterTerm) {
        offset = 0;
        loadTable(active);
        return;
      }
      searchEntireTable(filterTerm);
    };
    fin.oninput = () => {
      /* value only; Enter runs whole-table search */
    };

    if (keepTopSearch) {
      focusEl($("#search"), caret);
    } else if (keepInside) {
      focusEl($("#inside-q"), caret);
    } else if (keepFilter) {
      fin.focus();
      try {
        const pos = caret != null ? caret : fin.value.length;
        fin.setSelectionRange(pos, pos);
      } catch (_) {}
    }
  }

  async function searchEntireTable(term) {
    if (!selPath || !active) return;
    const t = String(term || "").trim();
    filterTerm = t;
    main.innerHTML = loadingHtml("Searching table…", t || active);
    try {
      const pe = encodeURIComponent(selPath);
      const te = encodeURIComponent(active);
      const payload = await api(
        `/api/sqlite/search?path=${pe}&table=${te}&q=${encodeURIComponent(t)}&limit=300`
      );
      if (payload.error) {
        main.innerHTML = errHtml(payload);
        return;
      }
      paintRows(payload, { focusFilter: true });
    } catch (e) {
      main.innerHTML = errHtml({ error: String(e.message || e), title: "SQLite search failed" });
    }
  }

  sqliteFilterFn = (term) => {
    filterTerm = term || "";
    if (!filterTerm) {
      if (sqliteClearFilter) sqliteClearFilter();
      return;
    }
    searchEntireTable(filterTerm);
  };
  sqliteClearFilter = () => {
    filterTerm = "";
    offset = 0;
    if (active) loadTable(active);
  };
  updateNavChrome();

  async function showSchema(tableName) {
    if (!selPath || !tableName) return;
    main.innerHTML = loadingHtml("Schema…", tableName);
    try {
      const pe = encodeURIComponent(selPath);
      const te = encodeURIComponent(tableName);
      const s = await api(`/api/sqlite/schema?path=${pe}&table=${te}`);
      if (s.error) {
        main.innerHTML = errHtml(s);
        return;
      }
      main.innerHTML = "";
      const bar = document.createElement("div");
      bar.className = "sqlite-toolbar";
      bar.innerHTML = `<strong>Schema · ${escapeHtml(tableName)}</strong>`;
      const back = document.createElement("button");
      back.type = "button";
      back.textContent = "← Rows";
      back.onclick = () => loadTable(tableName);
      bar.appendChild(back);
      main.appendChild(bar);
      const meta = document.createElement("table");
      meta.className = "meta data";
      meta.innerHTML = "<tr><th>#</th><th>Column</th><th>Type</th><th>PK</th><th>NotNull</th><th>Default</th></tr>";
      (s.columns || []).forEach((c) => {
        const tr = document.createElement("tr");
        tr.innerHTML =
          `<td>${c.cid}</td><td>${escapeHtml(c.name)}</td><td>${escapeHtml(c.type || "")}</td>` +
          `<td>${c.pk ? "✓" : ""}</td><td>${c.notnull ? "✓" : ""}</td>` +
          `<td>${escapeHtml(c.default == null ? "" : String(c.default))}</td>`;
        meta.appendChild(tr);
      });
      main.appendChild(meta);
      if (s.sql) {
        const pre = document.createElement("pre");
        pre.className = "sqlite-sql";
        pre.textContent = s.sql;
        main.appendChild(pre);
      }
    } catch (e) {
      main.innerHTML = errHtml({ error: String(e.message || e), title: "Schema failed" });
    }
  }

  async function loadTable(tableName) {
    if (!selPath || !tableName) {
      main.innerHTML = `<pre class="muted">No tables in this database.</pre>`;
      return;
    }
    active = tableName;
    list.querySelectorAll(".sqlite-t").forEach((el) => {
      el.classList.toggle("sel", el.dataset.name === tableName);
    });
    main.innerHTML = loadingHtml("Reading table…", tableName);
    try {
      const pe = encodeURIComponent(selPath);
      const te = encodeURIComponent(tableName);
      const payload = await api(
        `/api/sqlite/rows?path=${pe}&table=${te}&offset=${offset}&limit=${limit}`
      );
      if (payload.error) {
        main.innerHTML = errHtml(payload);
        return;
      }
      paintRows(payload);
    } catch (e) {
      main.innerHTML = errHtml({ error: String(e.message || e), title: "SQLite browse failed" });
    }
  }

  if (!tables.length) {
    side.innerHTML += `<pre class="muted">No tables/views</pre>`;
    main.innerHTML = `<pre class="muted">${escapeHtml(d.note || "Empty SQLite database.")}</pre>`;
    return;
  }

  tables.forEach((t) => {
    const name = typeof t === "string" ? t : t.name;
    const typ = typeof t === "string" ? "table" : (t.type || "table");
    const count = typeof t === "object" && t.row_count != null ? ` · ${t.row_count}` : "";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sqlite-t";
    btn.dataset.name = name;
    btn.innerHTML =
      `<span class="tn">${escapeHtml(name)}</span>` +
      `<span class="tt">${escapeHtml(typ)}${escapeHtml(count)}</span>`;
    btn.onclick = () => {
      offset = 0;
      loadTable(name);
    };
    list.appendChild(btn);
  });

  // Prefer server sample if present for first paint, else fetch
  if (d.columns && d.rows && active) {
    paintRows({
      table: active,
      columns: d.columns,
      rows: d.rows,
      offset: 0,
      limit: d.rows.length,
      returned: d.rows.length,
      total: null,
    });
    list.querySelectorAll(".sqlite-t").forEach((el) => {
      el.classList.toggle("sel", el.dataset.name === active);
    });
  } else {
    loadTable(active);
  }
}

function renderAccessor(d, body) {
  const bits = [];
  if (d.label) bits.push(`accessor: ${d.label}`);
  if (d.extension) bits.push(`.${d.extension}`);
  if (d.mime) bits.push(d.mime);
  if (d.encoding) bits.push(`encoding: ${d.encoding}`);
  if (d.note) bits.push(d.note);
  if (d.executable) bits.push("PE/MZ");
  if (d.truncated) bits.push(`truncated (${fmtSize(d.size)})`);

  body.innerHTML = "";
  if (bits.length) {
    const enc = document.createElement("div");
    enc.className = "enc";
    enc.textContent = bits.join(" · ");
    body.appendChild(enc);
  }

  if (d.data_url && (d.mode === "image" || d.kind === "image")) {
    const wrap = document.createElement("div");
    wrap.className = "img-wrap";
    const img = document.createElement("img");
    img.src = d.data_url;
    img.alt = selPath || "";
    wrap.appendChild(img);
    body.appendChild(wrap);
    if (d.mode === "image") return;
  }

  if (d.mode === "list" && d.items) {
    const pre = document.createElement("pre");
    pre.textContent = d.items.map((it) => {
      if (typeof it === "string") return it;
      const mark = it.is_dir ? "/" : "";
      return `${String(it.size ?? "").padStart(10)}  ${it.name}${mark}`;
    }).join("\n");
    body.appendChild(pre);
    return;
  }

  if (d.mode === "table" && (d.accessor === "recycle" || d.kind === "recycle"
      || d.accessor === "prefetch" || d.kind === "prefetch"
      || d.accessor === "shellbags" || d.kind === "shellbags"
      || d.accessor === "exif" || d.kind === "exif"
      || d.accessor === "sam" || d.kind === "sam")) {
    const table = document.createElement("table");
    table.className = "meta meta-readable recycle-table";
    if (d.kind === "prefetch" || d.accessor === "prefetch") {
      const warn = document.createElement("div");
      warn.className = "meta-highlight";
      warn.innerHTML =
        `<div class="mh-title">Windows Prefetch</div>` +
        `<div class="mh-row"><span class="k">Tip</span>` +
        `<span class="v">Installer .pf ≠ app was used. Look for a separate browser .pf for real runs.</span></div>`;
      body.appendChild(warn);
    }
    if (d.kind === "shellbags" || d.accessor === "shellbags") {
      const warn = document.createElement("div");
      warn.className = "meta-highlight";
      warn.innerHTML =
        `<div class="mh-title">ShellBags (BagMRU)</div>` +
        `<div class="mh-row"><span class="k">Tip</span>` +
        `<span class="v">Phone photos often live under DCIM → Camera before copy into Pictures\\Contact.</span></div>`;
      body.appendChild(warn);
    }
    if (d.kind === "sam" || d.accessor === "sam") {
      const warn = document.createElement("div");
      warn.className = "meta-highlight";
      warn.innerHTML =
        `<div class="mh-title">SAM / NTLM hashes</div>` +
        `<div class="mh-row"><span class="k">Tip</span>` +
        `<span class="v">TFF dumps with SYSTEM boot key, then auto-cracks via hashcat (masks). Cracked passwords show inline.</span></div>`;
      body.appendChild(warn);
    }
    if ((d.kind === "exif" || d.accessor === "exif") && d.data_url) {
      const wrap = document.createElement("div");
      wrap.className = "img-wrap";
      const img = document.createElement("img");
      img.src = d.data_url;
      img.alt = selPath || "";
      wrap.appendChild(img);
      body.appendChild(wrap);
    }
    (d.rows || []).forEach((row) => {
      const tr = document.createElement("tr");
      const k = row[0] == null ? "" : String(row[0]);
      const v = row[1] == null ? "" : String(row[1]);
      const isTime = /UTC/i.test(v) || /run|date|time/i.test(k);
      const isHit = /camera|dcim|lg |proton|hint|john doe|ntlm|boot key|crack/i.test(k + " " + v);
      if (isHit) tr.classList.add("hit-row");
      tr.innerHTML = `<td class="k">${escapeHtml(k)}</td><td class="v${isTime ? " timeish" : ""}">${escapeHtml(v)}</td>`;
      tr.title = v;
      table.appendChild(tr);
    });
    body.appendChild(table);
    if (d.text) {
      const pre = document.createElement("pre");
      pre.className = "muted";
      pre.textContent = d.text;
      body.appendChild(pre);
    }
    return;
  }

  if (d.mode === "table" || d.mode === "sqlite-browser" || d.kind === "sqlite") {
    renderSqliteBrowser(d, body);
    return;
  }

  if (d.mode === "info") {
    if (d.data_url) {
      const wrap = document.createElement("div");
      wrap.className = "img-wrap";
      const img = document.createElement("img");
      img.src = d.data_url;
      img.alt = selPath || "media still";
      wrap.appendChild(img);
      body.appendChild(wrap);
    }
    const pre = document.createElement("pre");
    pre.className = "muted";
    const exportHint = d.data_url
      ? "\n\nStill frame only - use Download or Export for full playback."
      : "\n\nUse Download or Export, then open with the matching app on your system.";
    pre.textContent = (d.note || "No inline preview") + exportHint;
    body.appendChild(pre);
    if (d.text) {
      const hex = document.createElement("pre");
      hex.className = "hex";
      hex.textContent = d.text;
      body.appendChild(hex);
    }
    return;
  }

  const pre = document.createElement("pre");
  if (d.mode === "hex") pre.className = "hex";
  const trunc = d.truncated && d.mode !== "hex"
    ? `\n\n… [showing partial text; ${fmtSize(d.size)} total - use Hex tab or Download for the rest]`
    : "";
  pre.textContent = (d.text || "") + trunc;
  body.appendChild(pre);

  // Hex paging — walk the entire file (forensic: every byte is in reach)
  if (d.mode === "hex" && d.size > 0) {
    const off = d.offset || 0;
    const win = d.window || 0;
    const end = Math.min(off + win, d.size);
    const bar = document.createElement("div");
    bar.className = "enc";
    bar.style.display = "flex";
    bar.style.flexWrap = "wrap";
    bar.style.gap = "8px";
    bar.style.alignItems = "center";
    bar.style.marginTop = "8px";
    const label = document.createElement("span");
    label.textContent = `Bytes ${off.toLocaleString()}–${end.toLocaleString()} of ${d.size.toLocaleString()} (${fmtSize(d.size)})`;
    bar.appendChild(label);
    const mkBtn = (text, disabled, fn) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = text;
      b.disabled = !!disabled;
      b.onclick = fn;
      bar.appendChild(b);
      return b;
    };
    const step = win > 0 ? win : 1024 * 1024;
    mkBtn("Prev", off <= 0, () => loadHexOffset(Math.max(0, off - step)));
    mkBtn("Next", end >= d.size, () => loadHexOffset(end));
    mkBtn("Start", off <= 0, () => loadHexOffset(0));
    if (end < d.size) {
      mkBtn("Load 8 MiB here", false, () => loadHexOffset(off, 8 * 1024 * 1024));
    }
    body.appendChild(bar);
  }
}

async function loadHexOffset(offset, bytes) {
  if (!selPath) return;
  const body = $("#detail-body");
  if (!body) return;
  const ac = startFileLoad();
  const pe = encodeURIComponent(selPath);
  let url = `/api/file?path=${pe}&mode=hex&offset=${offset || 0}`;
  if (bytes) url += `&bytes=${bytes}`;
  beginWork("Loading hex…", {
    title: "Hex",
    message: selPath,
    hint: `offset ${offset || 0}. Use × to stop.`,
    overlayDelay: 120,
    etaSeconds: estimateFileSeconds(bytes || selectedFileSize()),
    onCancel: () => ac.abort(),
  });
  try {
    const d = await api(url, { signal: ac.signal });
    if (d.error) {
      body.innerHTML = errHtml(d);
      notifyError(d);
      return;
    }
    curView = "hex";
    document.querySelectorAll(".dtab[data-view]").forEach((b) =>
      b.classList.toggle("active", b.dataset.view === "hex"));
    renderAccessor(d, body);
  } catch (e) {
    if (isAbort(e)) {
      if (_fileAbort === ac) body.innerHTML = `<pre class="muted">Stopped.</pre>`;
      return;
    }
    body.innerHTML = errHtml({ error: String(e.message || e), title: "Hex load failed" });
  } finally {
    if (_fileAbort === ac) _fileAbort = null;
    endWork();
  }
}

async function loadFindings() {
  await withBusy("Loading findings…", async () => {
    const d = await api("/api/artifacts");
    const box = $("#findings");
    box.innerHTML = "";
    if (!d.hits || !d.hits.length) {
      box.innerHTML = `<pre class="muted">No known artifacts matched.</pre>`;
      return;
    }
    const groups = {};
    d.hits.forEach((h) => {
      (groups[h.category] ||= []).push(h);
    });
    Object.keys(groups).sort().forEach((cat) => {
      const h3 = document.createElement("h3");
      h3.textContent = cat;
      const wrap = document.createElement("div");
      wrap.className = "find-group";
      wrap.appendChild(h3);
      groups[cat].forEach((h) => {
        const el = document.createElement("div");
        el.className = "find-item";
        el.innerHTML =
          `<div class="fn">${escapeHtml(h.label)} — <strong>${escapeHtml(h.name)}</strong></div>` +
          `<div class="fp">${escapeHtml(h.path)}</div>`;
        el.addEventListener("click", () => selectFile(h.path, null));
        wrap.appendChild(el);
      });
      box.appendChild(wrap);
    });
  }, { title: "Findings", message: "Loading artifact hits", overlayDelay: 150 });
}

document.querySelectorAll(".tab").forEach((t) => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".pane").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $("#" + t.dataset.pane).classList.add("active");
  });
});

document.querySelectorAll(".dtab[data-view]").forEach((b) => {
  b.addEventListener("click", () => renderView(b.dataset.view));
});

const exportBtn = $("#export-btn");
if (exportBtn) {
  exportBtn.addEventListener("click", async () => {
    if (!selPath) return;
    showBusy("Exporting…", "Copying file into the session temp folder.", "Usually quick for small files.");
    try {
      const d = await api("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: selPath }),
      });
      if (d.error) notifyError(d, "Export failed");
      else toast({ title: "Exported", message: d.exported, kind: "ok" });
    } catch (e) {
      notifyError({ error: String(e.message || e), suggestion: "Retry export, or use Download." });
    } finally {
      hideBusy();
    }
  });
}

$("#search").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    submitGlobalSearch();
  }
});
const insideQ = $("#inside-q");
if (insideQ) {
  insideQ.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      submitInsideSearch();
    }
  });
}
const btnSearch = $("#btn-search");
if (btnSearch) btnSearch.onclick = () => submitGlobalSearch();
const btnInsideGo = $("#btn-inside-go");
if (btnInsideGo) btnInsideGo.onclick = () => submitInsideSearch();
const btnNavBack = $("#btn-nav-back");
if (btnNavBack) btnNavBack.onclick = () => goBack();
const btnFolderGrep = $("#btn-folder-grep");
if (btnFolderGrep) {
  btnFolderGrep.onclick = () => {
    const iq = $("#inside-q");
    if (iq) {
      iq.focus();
      if (iq.value.trim()) submitInsideSearch();
    } else {
      promptFolderGrep();
    }
  };
}
const hitClose = $("#hit-close");
if (hitClose) hitClose.onclick = () => hideHitPanel();
const hitPanel = $("#hit-panel");
if (hitPanel) {
  hitPanel.addEventListener("click", (e) => {
    if (e.target === hitPanel) hideHitPanel();
  });
}
updateNavChrome();

/** Browser evidence open — file picker uploads to local API; path opens server-local files. */
async function refreshAfterOpen() {
  await loadInfo();
  await loadTree();
  await loadFindings();
  try { await loadXmount(); } catch (_) {}
  try { await refreshPcapStatus(); } catch (_) {}
}

async function openEvidencePath(path) {
  path = (path || "").trim();
  if (!path) {
    toast({
      title: "Missing path",
      message: "Enter an absolute path on this machine.",
      suggestion: "Example: /home/you/evidence.ad1",
      kind: "err",
    });
    return null;
  }
  showBusy("Opening evidence…", path, "Parsing or mounting the selected image.");
  try {
    const d = await api("/api/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    if (d.error) {
      notifyError(d, "Open failed");
      return null;
    }
    toast({ title: "Evidence open", message: d.image || path, kind: "ok" });
    await refreshAfterOpen();
    return d;
  } catch (e) {
    notifyError({
      title: "Open failed",
      error: e.message || String(e),
      suggestion: "Check the path exists on the machine running tforensic serve.",
    });
    return null;
  } finally {
    hideBusy();
  }
}

async function openEvidenceUpload(file, { fillInput, openAfter = true } = {}) {
  if (!file) return null;
  showBusy(
    openAfter ? "Opening evidence…" : "Uploading…",
    file.name,
    openAfter
      ? "Uploading to the local server, then opening for analysis."
      : "Saving the file so the path field can use it."
  );
  try {
    const r = await fetch("/api/open-upload", {
      method: "POST",
      headers: {
        "X-Filename": file.name,
        "Content-Type": "application/octet-stream",
        "X-Open": openAfter ? "1" : "0",
      },
      body: file,
    });
    const ct = r.headers.get("content-type") || "";
    const d = ct.includes("application/json") ? await r.json() : { error: r.statusText };
    if (!r.ok || d.error) {
      notifyError(d, "Upload / open failed");
      return null;
    }
    const path = d.uploaded_path || d.image_path || d.pcap_path || "";
    if (fillInput && path) {
      fillInput.value = path;
      fillInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (openAfter) {
      toast({ title: "Evidence open", message: d.image || file.name, kind: "ok" });
      await refreshAfterOpen();
    } else {
      toast({
        title: "File ready",
        message: path || file.name,
        suggestion: "Path filled — click Mount / Open / Add evidence.",
        kind: "ok",
      });
    }
    return d;
  } catch (e) {
    notifyError({
      title: "Upload failed",
      error: e.message || String(e),
      suggestion: "Retry, or use Path… for large images already on disk.",
    });
    return null;
  } finally {
    hideBusy();
  }
}

function pickEvidenceFile(opts = {}) {
  const input = $("#evidence-file");
  if (!input) {
    toast({
      title: "Picker unavailable",
      message: "Reload the page and try again.",
      kind: "err",
    });
    return;
  }
  input.value = "";
  const onChange = async () => {
    input.removeEventListener("change", onChange);
    const file = input.files && input.files[0];
    if (!file) return;
    await openEvidenceUpload(file, opts);
  };
  input.addEventListener("change", onChange);
  input.click();
}

$("#btn-open-evidence")?.addEventListener("click", () => {
  pickEvidenceFile({ openAfter: true });
});
$("#btn-open-path")?.addEventListener("click", async () => {
  const path = window.prompt(
    "Absolute path to evidence on this machine (AD1, E01, OVA, PCAP, …):",
    ""
  );
  if (path == null) return;
  await openEvidencePath(path);
});
$("#xm-browse")?.addEventListener("click", () => {
  pickEvidenceFile({ fillInput: $("#xm-image"), openAfter: false });
});
$("#pcap-browse")?.addEventListener("click", () => {
  pickEvidenceFile({ fillInput: $("#pcap-path"), openAfter: false });
});
$("#case-ev-browse")?.addEventListener("click", () => {
  pickEvidenceFile({ fillInput: $("#case-ev-path"), openAfter: false });
});

// Desktop shell reads this when opening Terminal on the selected file
window.__tffGetSelection = () => ({
  path: selPath || null,
  name: selPath ? (selPath.split("/").pop() || selPath) : null,
  browseDir: browseDir || null,
});

(async () => {
  showBusy("Loading case…", "Fetching tree, formats, and disk tools.", "Almost ready.");
  try {
    try {
      const ver = await api("/api/version");
      if (ver && ver.version) {
        const label = `v${ver.version}`;
        const av = $("#app-version");
        const fv = $("#footer-version");
        if (av) av.textContent = label;
        if (fv) fv.textContent = `${ver.short || "TFF"} ${label}`;
        document.title = `${ver.name || "Team Forensic Framework"} ${label}`;
      }
    } catch (_) {}
    await loadFormats();
    await loadInfo();
    await loadTree();
    await loadFindings();
    await loadXmount();
    startDepsWatch();
  } finally {
    hideBusy();
  }
})().catch((e) => {
  hideBusy();
  const d = {
    title: "Failed to load",
    error: e.message || String(e),
    suggestion: "Restart tforensic serve, or reopen the image from the desktop app.",
  };
  notifyError(d);
  $("#detail-body").innerHTML = errHtml(d);
});

async function loadFormats() {
  const box = $("#formats-list");
  if (!box) return;
  try {
    const d = await api("/api/formats");
    box.innerHTML = "";
    const title = document.createElement("div");
    title.className = "muted";
    title.style.marginBottom = "8px";
    title.textContent = "Accepted evidence for analysis";
    box.appendChild(title);

    (d.catalog || []).forEach((g) => {
      const el = document.createElement("div");
      el.className = "fmt-group";
      const badge = g.engine === "ad1"
        ? `<span class="fmt-badge ad1">AD1 engine</span>`
        : `<span class="fmt-badge xmount">xmount</span>`;
      el.innerHTML =
        `<h3>${escapeHtml(g.group)}${badge}</h3>` +
        `<div class="exts">${(g.extensions || []).map((e) => `<span>${escapeHtml(e)}</span>`).join("")}</div>` +
        `<div class="notes">${escapeHtml(g.notes || "")}</div>`;
      box.appendChild(el);
    });

    const foot = document.createElement("div");
    foot.className = "fmt-foot";
    const xm = d.xmount || {};
    const sk = d.sleuthkit || {};
    foot.innerHTML =
      `xmount: ${xm.available ? "yes" : "no"}` +
      (xm.inputs && xm.inputs.length ? ` · in: ${xm.inputs.join(", ")}` : "") +
      `<br>sleuthkit mmls/fls: ${sk.mmls ? "yes" : "no"} / ${sk.fls ? "yes" : "no"}` +
      `<br>Use <strong>Open evidence…</strong> in the header to pick a file, or <strong>Path…</strong> for a local absolute path.`;
    box.appendChild(foot);

    const actions = document.createElement("div");
    actions.className = "fmt-open-actions";
    const bFile = document.createElement("button");
    bFile.type = "button";
    bFile.className = "disk-btn";
    bFile.textContent = "Open evidence…";
    bFile.onclick = () => pickEvidenceFile({ openAfter: true });
    const bPath = document.createElement("button");
    bPath.type = "button";
    bPath.className = "disk-btn secondary";
    bPath.textContent = "Open by path…";
    bPath.onclick = () => $("#btn-open-path")?.click();
    actions.appendChild(bFile);
    actions.appendChild(bPath);
    box.insertBefore(actions, foot);

    // Also show summary in empty detail if still default
    const body = $("#detail-body");
    if (body && /Nothing loaded/i.test(body.textContent || "")) {
      body.innerHTML =
        `<div class="enc">Accepted formats</div>` +
        `<pre>` +
        (d.catalog || []).map((g) =>
          `${g.group}\n  ${(g.extensions || []).join("  ")}\n  ${g.notes || ""}`
        ).join("\n\n") +
        `\n\nClick Open evidence… in the header to select a file for analysis.</pre>`;
    }
  } catch (e) {
    box.innerHTML = `<pre class="muted">Could not load formats: ${escapeHtml(e.message)}</pre>`;
  }
}

/* ---- xmount / disk panel ---- */
let xmCurrent = null; // { id, device, offset }

async function loadXmount() {
  const st = $("#xm-status");
  if (!st) return;
  try {
    const info = await api("/api/xmount/info");
    if (!info.xmount) {
      st.textContent = "xmount not installed";
      st.className = "disk-status muted";
      return;
    }
    st.textContent = `xmount ${info.version || ""} · mmls=${info.mmls} · fls=${info.fls}`;
    st.className = "disk-status";
    await refreshMounts();
    // If case is already a disk mount, auto-show partitions
    const caseInfo = await api("/api/info");
    if ((caseInfo.kind === "disk" || caseInfo.kind === "ova") && caseInfo.xmount) {
      $("#xm-image").value = caseInfo.image_path || "";
      await showPartitions(caseInfo.xmount);
    }
  } catch (e) {
    st.textContent = "xmount API unavailable (restart serve)";
  }
}

async function refreshMounts() {
  const box = $("#xm-mounts");
  if (!box) return;
  const d = await api("/api/xmount/mounts");
  box.innerHTML = "<div class='muted'>Active mounts</div>";
  if (!d.mounts || !d.mounts.length) {
    box.innerHTML += "<pre class='muted'>none</pre>";
    return;
  }
  d.mounts.forEach((m) => {
    const el = document.createElement("div");
    el.className = "disk-card";
    el.innerHTML =
      `<div class="ttl">${escapeHtml(m.id)} · ${escapeHtml(m.input_type)}→${escapeHtml(m.output_type)}</div>` +
      `<div class="meta">${escapeHtml(m.image_path)}</div>` +
      `<div class="meta">${escapeHtml(m.virtual_device || "")}</div>`;
    const bParts = document.createElement("button");
    bParts.className = "disk-btn secondary";
    bParts.textContent = "Partitions";
    bParts.onclick = () => showPartitions(m);
    const bU = document.createElement("button");
    bU.className = "disk-btn danger";
    bU.textContent = "Umount";
    bU.onclick = async () => {
      await api("/api/xmount/umount", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: m.id }),
      });
      $("#xm-parts").innerHTML = "";
      $("#xm-fls").innerHTML = "";
      await refreshMounts();
    };
    el.appendChild(bParts);
    el.appendChild(bU);
    box.appendChild(el);
  });
}

async function showPartitions(m) {
  xmCurrent = { id: m.id, device: m.virtual_device, offset: 0 };
  const box = $("#xm-parts");
  box.innerHTML = "<pre class='muted'>loading partitions…</pre>";
  showBusy("Reading partitions…", "Running mmls on the virtual disk.", "Needs sleuthkit (mmls).");
  try {
    const d = await api(`/api/xmount/partitions?id=${encodeURIComponent(m.id)}`);
    if (d.error) {
      notifyError(d, "Partitions failed");
      box.innerHTML = errHtml(d);
      return;
    }
    box.innerHTML = `<div class="muted">Partitions on ${escapeHtml(d.device || "")}</div>`;
    (d.partitions || []).forEach((p) => {
      const row = document.createElement("div");
      row.className = "part-row";
      row.textContent = `${p.slot}  start=${p.start}  len=${p.length}  ${p.desc}`;
      row.title = `byte offset ${p.byte_offset}`;
      row.onclick = () => showFls(m.id, p.start);
      box.appendChild(row);
    });
  } finally {
    hideBusy();
  }
}

async function showFls(mountId, offset, inode) {
  xmCurrent = { id: mountId, offset, inode };
  const box = $("#xm-fls");
  box.innerHTML = "<pre class='muted'>listing…</pre>";
  showBusy("Listing files…", "Running fls on the selected partition.", "Click a folder to go deeper.");
  try {
    let url = `/api/xmount/fls?id=${encodeURIComponent(mountId)}&offset=${offset}`;
    if (inode) url += `&inode=${encodeURIComponent(inode)}`;
    const d = await api(url);
    if (d.error) {
      notifyError(d, "Listing failed");
      box.innerHTML = errHtml(d);
      return;
    }
    box.innerHTML = `<div class="muted">fls -o ${offset}${inode ? " inode " + inode : ""}</div>`;
    (d.entries || []).forEach((e) => {
      const row = document.createElement("div");
      row.className = "fls-row" + (e.is_dir ? " dir" : "");
      row.textContent = `${e.is_dir ? "d" : "r"}${e.deleted ? "*" : " "} ${e.inode}  ${e.name}`;
      if (e.is_dir) {
        row.onclick = () => showFls(mountId, offset, e.inode);
      } else {
        row.onclick = async () => {
          showBusy("Extracting file…", `icat inode ${e.inode}`, "Writing into session temp.");
          try {
            const res = await api("/api/xmount/icat", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ id: mountId, inode: e.inode, offset }),
            });
            if (res.error) {
              notifyError(res, "Extract failed");
              $("#detail-body").innerHTML = errHtml(res);
            } else {
              toast({ title: "Extracted", message: res.exported, kind: "ok" });
              $("#detail-head").innerHTML =
                `<div class="path">inode ${escapeHtml(String(e.inode))} — ${escapeHtml(e.name)}</div>` +
                `<div class="sub">extracted via icat</div>`;
              $("#detail-body").innerHTML =
                `<div class="enc">exported to session temp</div><pre>${escapeHtml(res.exported)}</pre>`;
            }
          } finally {
            hideBusy();
          }
        };
      }
      box.appendChild(row);
    });
  } finally {
    hideBusy();
  }
}

const xmMountBtn = $("#xm-mount");
async function refreshEstimate() {
  const box = $("#xm-eta");
  const image = $("#xm-image")?.value.trim();
  if (!box) return;
  if (!image) {
    box.textContent = "Enter a path to see an open-time estimate.";
    return;
  }
  box.textContent = "Estimating…";
  try {
    const itype = $("#xm-in")?.value || "";
    let url = `/api/estimate?path=${encodeURIComponent(image)}`;
    if (itype) url += `&input_type=${encodeURIComponent(itype)}`;
    const d = await api(url);
    if (d.error) {
      box.textContent = d.error;
      return;
    }
    if (!d.exists) {
      box.innerHTML = `Path not found yet — estimate uses size when the file is readable.`;
      return;
    }
    const stages = (d.stages || [])
      .map((s) => `${escapeHtml(s.name)} ${escapeHtml(s.human)}`)
      .join(" · ");
    box.innerHTML =
      `Est. <strong>${escapeHtml(d.human)}</strong> ` +
      `(${escapeHtml(d.human_range)}) · ${escapeHtml(d.size_human)} · ${escapeHtml(d.kind)}` +
      (stages ? `<br>${stages}` : "") +
      `<br><span class="muted">${escapeHtml(d.note || "")}</span>`;
    box.dataset.seconds = String(d.seconds || "");
  } catch (e) {
    box.textContent = "Could not estimate (is the API running?).";
  }
}
if ($("#xm-image")) {
  let etaDebounce = null;
  $("#xm-image").addEventListener("input", () => {
    clearTimeout(etaDebounce);
    etaDebounce = setTimeout(refreshEstimate, 350);
  });
  $("#xm-in")?.addEventListener("change", refreshEstimate);
}
if (xmMountBtn) {
  xmMountBtn.addEventListener("click", async () => {
    const image = $("#xm-image").value.trim();
    if (!image) {
      toast({
        title: "Missing path",
        message: "Enter a full path to the disk image.",
        suggestion: "Example: /home/you/evidence.E01",
        kind: "err",
      });
      return;
    }
    await refreshEstimate();
    const etaSec = parseFloat($("#xm-eta")?.dataset.seconds || "0") || 0;
    const body = {
      image,
      input_type: $("#xm-in").value || null,
      output_type: $("#xm-out").value || "raw",
      morph: $("#xm-morph").value || "combine",
      cache: $("#xm-cache").value.trim() || null,
    };
    xmMountBtn.disabled = true;
    xmMountBtn.textContent = "Mounting…";
    showBusy(
      "Mounting image…",
      "xmount is creating a read-only virtual disk.",
      etaSec
        ? `Rough ETA ${fmtEta(etaSec)} — watch % loaded`
        : "E01/OVA can take a while — watch % loaded.",
      etaSec || undefined,
      0.15
    );
    try {
      const res = await api("/api/xmount/mount", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.error) {
        notifyError(res, "Mount failed");
        $("#xm-parts").innerHTML = errHtml(res);
      } else {
        toast({ title: "Mounted", message: res.id || "Disk mount ready", kind: "ok" });
        await refreshMounts();
        await showPartitions(res);
      }
    } catch (e) {
      notifyError({
        error: String(e.message || e),
        suggestion: "Install xmount: sudo apt install xmount",
      });
    } finally {
      hideBusy();
      xmMountBtn.disabled = false;
      xmMountBtn.textContent = "Mount";
    }
  });
}
const xmRefreshBtn = $("#xm-refresh");
if (xmRefreshBtn) xmRefreshBtn.addEventListener("click", () => refreshMounts());

/* ---- Persistent Case (Autopsy-class) ---- */
let activeCaseId = null;
let ingestPoll = null;

async function refreshCaseList() {
  const box = $("#case-list");
  if (!box) return;
  const d = await api("/api/case/list");
  box.innerHTML = "<div class='muted'>Cases</div>";
  (d.cases || []).forEach((c) => {
    const el = document.createElement("div");
    el.className = "case-row";
    const st = c.stats || {};
    el.innerHTML = `<div class="ttl">${escapeHtml(c.name)}</div><div class="meta">${escapeHtml(c.id)} · files ${st.files || 0}</div>`;
    el.onclick = async () => {
      const r = await api("/api/case/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: c.id }),
      });
      if (r.error) return notifyError(r);
      activeCaseId = r.id;
      toast({ title: "Case open", message: r.name, kind: "ok" });
      await refreshCaseInfo();
      await loadCharts();
    };
    box.appendChild(el);
  });
}

async function refreshCaseInfo() {
  const box = $("#case-info");
  const jobs = $("#case-jobs");
  const cust = $("#case-custody");
  if (!box) return;
  try {
    const d = await api("/api/case/info");
    if (d.error) {
      box.textContent = d.error;
      return;
    }
    activeCaseId = d.id;
    const st = d.stats || {};
    box.innerHTML =
      `<div class="ttl">${escapeHtml(d.name)} <span class="muted">${escapeHtml(d.id)}</span></div>` +
      `<div class="meta">examiner: ${escapeHtml(d.examiner || "—")}</div>` +
      `<div class="meta">evidence ${st.evidence || 0} · files ${st.files || 0} · artifacts ${st.artifacts || 0} · timeline ${st.timeline || 0}</div>` +
      `<div class="meta">${escapeHtml(d.path || "")}</div>` +
      `<div class="muted">Evidence</div>` +
      (d.evidence || []).map((e) =>
        `<div class="case-row" data-eid="${escapeHtml(e.id)}"><div class="ttl">${escapeHtml(e.name)}</div>` +
        `<div class="meta">${escapeHtml(e.kind)} · ${escapeHtml(e.status)} · ${escapeHtml(e.id)}</div></div>`
      ).join("");
    if (jobs) {
      jobs.innerHTML = "<div class='muted'>Jobs</div>";
      (d.jobs || []).forEach((j) => {
        jobs.innerHTML +=
          `<div class="meta">${escapeHtml(j.id)} ${escapeHtml(j.status)} ${(j.progress * 100).toFixed(0)}% — ${escapeHtml(j.message || "")}</div>`;
      });
    }
    const c = await api("/api/case/custody");
    if (cust) {
      cust.innerHTML = "<div class='muted'>Custody (recent)</div>";
      (c.entries || []).slice(0, 8).forEach((e) => {
        cust.innerHTML += `<div class="meta">${escapeHtml(e.action)} — ${escapeHtml(e.detail)}</div>`;
      });
    }
  } catch (e) {
    box.textContent = "No active case — create or open one.";
  }
}

function postCase(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

$("#case-create")?.addEventListener("click", async () => {
  const name = $("#case-name")?.value.trim() || "Untitled case";
  const examiner = $("#case-examiner")?.value.trim() || "";
  showBusy("Creating case…", name, "Writing SQLite case DB under ~/.tforensic/cases");
  try {
    const r = await postCase("/api/case/create", { name, examiner });
    if (r.error) notifyError(r);
    else {
      activeCaseId = r.id;
      toast({ title: "Case created", message: r.id, kind: "ok" });
      await refreshCaseList();
      await refreshCaseInfo();
    }
  } finally {
    hideBusy();
  }
});

$("#case-refresh")?.addEventListener("click", async () => {
  await refreshCaseList();
  await refreshCaseInfo();
});

$("#case-add")?.addEventListener("click", async () => {
  const path = $("#case-ev-path")?.value.trim();
  if (!path) return toast({ title: "Missing path", message: "Enter evidence path", kind: "err" });
  showBusy("Adding evidence…", path, "Hashing image into case DB");
  try {
    const r = await postCase("/api/case/add", { path });
    if (r.error) notifyError(r);
    else {
      toast({ title: "Evidence added", message: `${r.id} (${r.kind})`, kind: "ok" });
      await refreshCaseInfo();
    }
  } finally {
    hideBusy();
  }
});

$("#case-ingest")?.addEventListener("click", async () => {
  const info = await api("/api/case/info");
  const ev = (info.evidence || []).slice(-1)[0];
  if (!ev) return toast({ title: "No evidence", message: "Add evidence first", kind: "err" });
  showBusy("Starting ingest…", ev.name, "Index + modules running in background");
  try {
    const r = await postCase("/api/case/ingest", { evidence_id: ev.id });
    if (r.error) notifyError(r);
    else {
      toast({
        title: "Ingest started",
        message: `job ${r.job_id} · ETA ${r.estimate?.human || "?"}`,
        kind: "ok",
      });
      if (ingestPoll) clearInterval(ingestPoll);
      ingestPoll = setInterval(async () => {
        const j = await api(`/api/case/jobs?job=${encodeURIComponent(r.job_id)}`);
        const eta = j.eta_seconds;
        showBusy(
          "Ingesting…",
          j.message || j.status,
          `${((j.progress || 0) * 100).toFixed(0)}% loaded — ETA may be wrong`,
          j.eta_seconds,
          j.progress
        );
        if (j.status === "done" || j.status === "error") {
          clearInterval(ingestPoll);
          hideBusy();
          if (j.status === "error") notifyError({ error: j.error || j.message, title: "Ingest failed" });
          else toast({ title: "Ingest complete", message: ev.id, kind: "ok" });
          await refreshCaseInfo();
          await loadTimeline();
          await loadCharts();
        }
      }, 800);
    }
  } catch (e) {
    hideBusy();
    notifyError({ error: String(e.message || e) });
  }
});

$("#case-tag-btn")?.addEventListener("click", async () => {
  const file_id = parseInt($("#case-tag-fid")?.value, 10);
  const tag = $("#case-tag")?.value.trim();
  if (!file_id || !tag) return toast({ title: "Need file id + tag", message: "", kind: "err" });
  const r = await postCase("/api/case/tag", { file_id, tag });
  if (r.error) notifyError(r);
  else toast({ title: "Tagged", message: tag, kind: "ok" });
});

$("#case-note-btn")?.addEventListener("click", async () => {
  const body = $("#case-note")?.value.trim();
  const file_id = parseInt($("#case-tag-fid")?.value, 10) || null;
  if (!body) return;
  const r = await postCase("/api/case/note", { body, file_id });
  if (r.error) notifyError(r);
  else toast({ title: "Note saved", message: String(r.id), kind: "ok" });
});

$("#case-hash-btn")?.addEventListener("click", async () => {
  const text = $("#case-hashes")?.value || "";
  const r = await postCase("/api/case/hash-import", { name: "imported", kind: "notable", text });
  if (r.error) notifyError(r);
  else toast({ title: "Hash set imported", message: `${r.count} hashes, ${r.files_marked} files marked`, kind: "ok" });
});

$("#case-report-btn")?.addEventListener("click", async () => {
  showBusy("Generating report…", "HTML case report", "");
  try {
    const r = await postCase("/api/case/report", {});
    if (r.error) notifyError(r);
    else {
      toast({ title: "Report ready", message: r.report, kind: "ok" });
      $("#detail-body").innerHTML = `<div class="enc">HTML report</div><pre>${escapeHtml(r.report)}</pre>`;
    }
  } finally {
    hideBusy();
  }
});

$("#case-verify-btn")?.addEventListener("click", async () => {
  showBusy("Verifying…", "Re-hashing evidence", "Chain of custody update");
  try {
    const r = await postCase("/api/case/verify", {});
    if (r.error) notifyError(r);
    else {
      toast({ title: "Verify done", message: "See detail panel", kind: "ok" });
      $("#detail-body").innerHTML = `<pre>${escapeHtml(JSON.stringify(r, null, 2))}</pre>`;
    }
  } finally {
    hideBusy();
  }
});

$("#case-export-btn")?.addEventListener("click", async () => {
  showBusy("Exporting case…", "Zip case.db + reports (not full images)", "");
  try {
    const r = await postCase("/api/case/export", {});
    if (r.error) notifyError(r);
    else toast({ title: "Exported", message: r.export, kind: "ok" });
  } finally {
    hideBusy();
  }
});

async function loadTimeline() {
  const box = $("#tl-list");
  if (!box) return;
  box.innerHTML = loadingHtml("Loading timeline…", "Fetching case events");
  await withBusy("Loading timeline…", async () => {
    try {
      const d = await api("/api/case/timeline?limit=200");
      if (d.error) {
        box.innerHTML = errHtml(d);
        return;
      }
      box.innerHTML = "";
      (d.events || []).forEach((e) => {
        const row = document.createElement("div");
        row.className = "case-row";
        const when = new Date((e.ts || 0) * 1000).toISOString().replace("T", " ").slice(0, 19);
        row.innerHTML =
          `<div class="ttl">${escapeHtml(when)} · ${escapeHtml(e.event_type)}</div>` +
          `<div class="meta">${escapeHtml(e.description)} — ${escapeHtml(e.path || "")}</div>`;
        box.appendChild(row);
      });
      if (!(d.events || []).length) box.innerHTML = "<pre class='muted'>No timeline events yet — run ingest.</pre>";
    } catch {
      box.innerHTML = "<pre class='muted'>Open a case first.</pre>";
    }
  }, { title: "Timeline", message: "Loading events", overlayDelay: 150 });
}
$("#tl-refresh")?.addEventListener("click", loadTimeline);

function _chartMax(items) {
  let m = 0;
  (items || []).forEach((x) => { if (x.count > m) m = x.count; });
  return m || 1;
}

function svgBarChart(items, opts) {
  const list = (items || []).slice(0, opts?.limit || 12);
  if (!list.length) return `<div class="chart-empty">No data yet</div>`;
  const W = opts?.width || 420;
  const rowH = 22;
  const left = 72;
  const right = 36;
  const H = list.length * rowH + 8;
  const max = _chartMax(list);
  const barW = W - left - right;
  const cls = opts?.barClass || "chart-bar";
  const bars = list.map((it, i) => {
    const y = 4 + i * rowH;
    const w = Math.max(2, (it.count / max) * barW);
    const label = String(it.label || "?").slice(0, 10);
    return (
      `<text class="chart-bar-label" x="0" y="${y + 12}">${escapeHtml(label)}</text>` +
      `<rect class="${cls}" x="${left}" y="${y + 2}" width="${w.toFixed(1)}" height="14" rx="3"/>` +
      `<text class="chart-bar-val" x="${left + w + 4}" y="${y + 12}">${it.count}</text>`
    );
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(opts?.title || "chart")}">${bars}</svg>`;
}

function svgLineChart(items) {
  const list = items || [];
  if (list.length < 2) {
    if (list.length === 1) {
      return `<div class="chart-empty">${escapeHtml(list[0].label)}: ${list[0].count} events</div>`;
    }
    return `<div class="chart-empty">No timeline density yet — run ingest</div>`;
  }
  const W = 640, H = 160, padL = 28, padR = 12, padT = 12, padB = 28;
  const max = _chartMax(list);
  const n = list.length;
  const pts = list.map((it, i) => {
    const x = padL + (i / Math.max(n - 1, 1)) * (W - padL - padR);
    const y = padT + (1 - it.count / max) * (H - padT - padB);
    return [x, y, it];
  });
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const area =
    `M${pts[0][0].toFixed(1)},${(H - padB).toFixed(1)} ` +
    pts.map((p) => `L${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ") +
    ` L${pts[pts.length - 1][0].toFixed(1)},${(H - padB).toFixed(1)} Z`;
  const dots = pts.map((p) =>
    `<circle class="chart-dot" cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="2.5">` +
    `<title>${escapeHtml(p[2].label)}: ${p[2].count}</title></circle>`
  ).join("");
  const first = list[0].label || "";
  const last = list[list.length - 1].label || "";
  return (
    `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Timeline activity">` +
    `<line class="chart-axis" x1="${padL}" y1="${H - padB}" x2="${W - padR}" y2="${H - padB}"/>` +
    `<path class="chart-area" d="${area}"/>` +
    `<path class="chart-line" d="${line}"/>` +
    dots +
    `<text class="chart-bar-label" x="${padL}" y="${H - 8}">${escapeHtml(first)}</text>` +
    `<text class="chart-bar-label" x="${W - padR}" y="${H - 8}" text-anchor="end">${escapeHtml(last)}</text>` +
    `</svg>`
  );
}

function renderChartsDashboard(d) {
  const m = d.metrics || {};
  const cards = [
    ["Files", m.files],
    ["Artifacts", m.artifacts],
    ["Timeline", m.timeline],
    ["Tags", m.tags],
    ["Evidence", m.evidence],
    ["Hash hits", m.hash_marked],
    ["Keywords", m.keyword_hits],
    ["Deleted", m.deleted],
  ];
  const metricsEl = $("#charts-metrics");
  if (metricsEl) {
    metricsEl.innerHTML = cards.map(([lab, val]) =>
      `<div class="metric-card"><div class="mv">${val ?? 0}</div><div class="ml">${lab}</div></div>`
    ).join("");
  }
  const side = $("#charts-side");
  if (side) {
    const topExt = (d.extensions || []).slice(0, 5).map((x) => `${x.label} (${x.count})`).join(", ") || "—";
    const topArt = (d.artifacts || []).slice(0, 5).map((x) => `${x.label} (${x.count})`).join(", ") || "—";
    side.innerHTML =
      `<div class="meta">Top extensions: ${escapeHtml(topExt)}</div>` +
      `<div class="meta">Modules: ${escapeHtml(topArt)}</div>` +
      `<div class="muted" style="margin-top:6px">Full charts → detail panel</div>`;
  }

  const body = $("#detail-body");
  const head = $("#detail-head");
  if (head) head.innerHTML = `<span>Case overview · charts</span>`;
  if (!body) return;
  body.innerHTML =
    `<div class="charts-grid">` +
    `<div class="chart-card wide"><h3>Timeline activity (by day)</h3>${svgLineChart(d.timeline)}</div>` +
    `<div class="chart-card"><h3>File extensions</h3>${svgBarChart(d.extensions, { barClass: "chart-bar" })}</div>` +
    `<div class="chart-card"><h3>Ingest modules</h3>${svgBarChart(d.artifacts, { barClass: "chart-bar mod" })}</div>` +
    `<div class="chart-card"><h3>Artifact categories</h3>${svgBarChart(d.categories, { barClass: "chart-bar alt" })}</div>` +
    `<div class="chart-card"><h3>Event types</h3>${svgBarChart(d.event_types)}</div>` +
    `<div class="chart-card"><h3>Tags</h3>${svgBarChart(d.tags, { barClass: "chart-bar mod" })}</div>` +
    `<div class="chart-card"><h3>Files per evidence</h3>${svgBarChart(
      (d.evidence || []).map((e) => ({ label: e.label, count: e.count })),
      { barClass: "chart-bar" }
    )}</div>` +
    `</div>`;
}

async function loadCharts() {
  const metricsEl = $("#charts-metrics");
  const side = $("#charts-side");
  if (side) side.innerHTML = loadingHtml("Building charts…", "Aggregating case stats");
  await withBusy("Building charts…", async () => {
    try {
      const d = await api("/api/case/charts");
      if (d.error) {
        if (metricsEl) metricsEl.innerHTML = "";
        if (side) side.innerHTML = errHtml(d);
        return;
      }
      renderChartsDashboard(d);
    } catch {
      if (metricsEl) metricsEl.innerHTML = "";
      if (side) side.innerHTML = `<pre class="muted">Open a case and run ingest to populate charts.</pre>`;
    }
  }, { title: "Charts", message: "Aggregating case data", overlayDelay: 150 });
}
$("#charts-refresh")?.addEventListener("click", loadCharts);

$("#case-q-btn")?.addEventListener("click", async () => {
  const q = $("#case-q")?.value.trim();
  if (!q) return;
  const box = $("#case-q-results");
  box.innerHTML = loadingHtml("Searching…", q);
  await withBusy("Case search…", async () => {
    const d = await api(`/api/case/search?q=${encodeURIComponent(q)}`);
    if (d.error) {
      box.innerHTML = errHtml(d);
      return;
    }
    box.innerHTML = `<div class="muted">Files ${ (d.files||[]).length } · keyword hits ${ (d.keyword_hits||[]).length }</div>`;
    (d.files || []).forEach((f) => {
      const row = document.createElement("div");
      row.className = "case-row";
      row.innerHTML = `<div class="ttl">${escapeHtml(f.name)}</div><div class="meta">#${f.id} ${escapeHtml(f.path)}</div>`;
      row.onclick = () => {
        $("#case-tag-fid").value = f.id;
        $("#detail-head").innerHTML = `<div class="path">${escapeHtml(f.path)}</div><div class="sub">case file #${f.id}</div>`;
        $("#detail-body").innerHTML = `<pre>${escapeHtml(JSON.stringify(f, null, 2))}</pre>`;
      };
      box.appendChild(row);
    });
    (d.keyword_hits || []).forEach((h) => {
      const row = document.createElement("div");
      row.className = "case-row";
      row.innerHTML = `<div class="ttl">[${escapeHtml(h.keyword)}]</div><div class="meta">${escapeHtml(h.path)}</div>`;
      box.appendChild(row);
    });
  }, { title: "Search", message: q, overlayDelay: 100 });
});

// init case panel after load
(async () => {
  try {
    await refreshCaseList();
    await refreshCaseInfo();
  } catch (_) {}
})();

/* ---- Lab / Framework ---- */
async function refreshLab() {
  const stBox = $("#lab-status");
  const plugBox = $("#lab-plugins");
  const plugSel = $("#lab-plugin-sel");
  const pbSel = $("#lab-pb-sel");
  try {
    const st = await api("/api/lab/status");
    if (st.error) {
      if (stBox) stBox.textContent = st.error + " — open/create a case first";
      return;
    }
    if (stBox) {
      stBox.innerHTML =
        `<div class="ttl">Lab ${st.enabled ? "ON" : "OFF"}` +
        `${st.virtual_write ? " · virtual-write" : ""}</div>` +
        `<div class="meta">${escapeHtml(st.path || "")}</div>` +
        (st.cache_file ? `<div class="meta">cache: ${escapeHtml(st.cache_file)}</div>` : "") +
        `<div class="meta">working copies: ${st.working_copies || 0}</div>` +
        `<div class="muted">${escapeHtml(st.note || "")}</div>`;
      if (st.cache_file && $("#xm-cache")) $("#xm-cache").value = st.cache_file;
    }
    const pl = await api("/api/plugin/list");
    if (plugSel) {
      plugSel.innerHTML = "";
      (pl.plugins || []).forEach((p) => {
        const o = document.createElement("option");
        o.value = p.name;
        o.textContent = `${p.name} — ${p.description || ""}`;
        plugSel.appendChild(o);
      });
    }
    if (plugBox) {
      plugBox.innerHTML = (pl.plugins || [])
        .map((p) => `<div class="meta">${escapeHtml(p.name)}${p.requires_lab ? " [lab]" : ""} — ${escapeHtml(p.description || "")}</div>`)
        .join("");
    }
    const pb = await api("/api/playbook/list");
    if (pbSel) {
      pbSel.innerHTML = "";
      (pb.playbooks || []).forEach((p) => {
        if (p.error) return;
        const o = document.createElement("option");
        o.value = p.name;
        o.textContent = `${p.name} — ${p.description || ""}`;
        pbSel.appendChild(o);
      });
    }
  } catch (e) {
    if (stBox) stBox.textContent = "Open a case to use Lab / framework features.";
  }
}

$("#lab-enable")?.addEventListener("click", async () => {
  showBusy("Enabling lab…", "Writable sandbox under case/lab/", "Evidence stays immutable", null, 0.3);
  try {
    const r = await postCase("/api/lab/enable", { virtual_write: false });
    if (r.error) notifyError(r);
    else toast({ title: "Lab enabled", message: r.path, kind: "ok" });
    await refreshLab();
  } finally {
    hideBusy();
  }
});
$("#lab-vw")?.addEventListener("click", async () => {
  showBusy("Enabling lab + virtual-write…", "xmount cache will catch disk writes", "Source image never changes", null, 0.3);
  try {
    const r = await postCase("/api/lab/enable", { virtual_write: true });
    if (r.error) notifyError(r);
    else {
      toast({ title: "Virtual-write ready", message: r.cache_file || r.path, kind: "ok" });
      if (r.cache_file && $("#xm-cache")) $("#xm-cache").value = r.cache_file;
    }
    await refreshLab();
  } finally {
    hideBusy();
  }
});
$("#lab-refresh")?.addEventListener("click", refreshLab);

$("#lab-run-plugin")?.addEventListener("click", async () => {
  const name = $("#lab-plugin-sel")?.value;
  if (!name) return;
  showBusy("Running plugin…", name, "Writes go to lab/ only", null, 0.1);
  try {
    const r = await postCase("/api/plugin/run", { plugin: name, sync: true });
    hideBusy();
    if (r.error || r.ok === false) notifyError(r.error ? r : { error: r.error || r.summary, title: "Plugin failed" });
    else {
      toast({ title: "Plugin done", message: r.summary || name, kind: "ok" });
      $("#lab-out").innerHTML = `<pre>${escapeHtml(JSON.stringify(r, null, 2))}</pre>`;
      $("#detail-body").innerHTML = `<div class="enc">plugin ${escapeHtml(name)}</div><pre>${escapeHtml(JSON.stringify(r, null, 2))}</pre>`;
    }
  } catch (e) {
    hideBusy();
    notifyError({ error: String(e.message || e) });
  }
});

$("#lab-run-pb")?.addEventListener("click", async () => {
  const name = $("#lab-pb-sel")?.value;
  if (!name) return;
  showBusy("Running playbook…", name, "Framework pipeline — watch % loaded", null, 0.05);
  try {
    const r = await postCase("/api/playbook/run", { playbook: name, sync: true });
    hideBusy();
    if (r.error || r.ok === false) {
      notifyError({ title: "Playbook issue", error: r.error || "one or more steps failed", suggestion: "Check lab-out detail" });
      $("#lab-out").innerHTML = `<pre>${escapeHtml(JSON.stringify(r, null, 2))}</pre>`;
    } else {
      toast({ title: "Playbook complete", message: name, kind: "ok" });
      $("#lab-out").innerHTML = `<pre>${escapeHtml(JSON.stringify(r, null, 2))}</pre>`;
    }
    await refreshLab();
    await refreshCaseInfo();
  } catch (e) {
    hideBusy();
    notifyError({ error: String(e.message || e) });
  }
});

document.querySelectorAll(".tab").forEach((t) => {
  t.addEventListener("click", () => {
    if (t.dataset.pane === "lab") withBusy("Loading lab…", () => refreshLab(), { overlayDelay: 100 });
    if (t.dataset.pane === "charts") loadCharts();
    if (t.dataset.pane === "timeline") loadTimeline();
    if (t.dataset.pane === "network") withBusy("Network status…", () => refreshPcapStatus(), { overlayDelay: 80 });
    if (t.dataset.pane === "findings") loadFindings();
    if (t.dataset.pane === "formats") withBusy("Loading formats…", () => loadFormats(), { overlayDelay: 80 });
    if (t.dataset.pane === "disk") withBusy("Loading disk tools…", () => loadXmount().then(() => refreshMounts()), { overlayDelay: 100 });
    if (t.dataset.pane === "case") {
      withBusy("Loading case…", async () => {
        await refreshCaseList();
        await refreshCaseInfo();
      }, { overlayDelay: 100 });
    }
    if (t.dataset.pane === "tree") {
      setWorkStatus("Tree ready — expand folders to load");
      setTimeout(() => { if (_workDepth === 0) clearWorkStatus(); }, 900);
    }
  });
});

/* ---- Network / PCAP (Wireshark-style) ---- */
let pcapOffset = 0;

async function refreshPcapStatus() {
  const st = $("#pcap-status");
  try {
    const d = await api("/api/pcap/status");
    if (st) {
      st.textContent = d.tshark
        ? "tshark available — full Wireshark display filters"
        : "tshark not found — native PCAP fallback (classic .pcap only)";
    }
    if (d.active) {
      $("#pcap-meta").innerHTML =
        `<div class="ttl">${escapeHtml(d.active.name)}</div>` +
        `<div class="meta">${escapeHtml(d.active.path)} · ${d.active.packet_count ?? "?"} pkts · engine ${escapeHtml(d.active.engine)}</div>`;
      if (!$("#pcap-path").value) $("#pcap-path").value = d.active.path;
    }
  } catch (e) {
    if (st) st.textContent = String(e.message || e);
  }
}

function renderPcapStats(summary) {
  const head = $("#detail-head");
  const body = $("#detail-body");
  if (head) head.innerHTML = `<span>Network · ${escapeHtml(summary.name || "PCAP")}</span>`;
  if (!body) return;
  const protos = summary.charts?.protocols || summary.protocols || [];
  const convs = summary.charts?.conversations || [];
  body.innerHTML =
    `<div class="charts-grid">` +
    `<div class="chart-card"><h3>Protocols</h3>${typeof svgBarChart === "function" ? svgBarChart(protos, { barClass: "chart-bar" }) : ""}</div>` +
    `<div class="chart-card"><h3>Top conversations</h3>${typeof svgBarChart === "function" ? svgBarChart(convs, { barClass: "chart-bar alt" }) : ""}</div>` +
    `</div>` +
    `<div class="enc" style="margin-top:10px">Capture</div>` +
    `<pre>${escapeHtml(JSON.stringify({
      packets: summary.packet_count,
      duration: summary.duration,
      size: summary.size,
      engine: summary.engine,
      link: summary.link_type,
    }, null, 2))}</pre>`;
}

async function loadPcapPackets(reset) {
  if (reset) pcapOffset = 0;
  const box = $("#pcap-packets");
  const yf = $("#pcap-filter")?.value.trim() || "";
  showBusy("Reading packets…", yf || "all frames", "tshark display filter");
  try {
    const d = await api(
      `/api/pcap/packets?offset=${pcapOffset}&limit=200&filter=${encodeURIComponent(yf)}`
    );
    if (d.error) {
      if (box) box.innerHTML = errHtml(d);
      return;
    }
    if (!box) return;
    let html =
      `<table class="pcap-table"><thead><tr>` +
      `<th>#</th><th>Time</th><th>Source</th><th>Dest</th><th>Proto</th><th>Len</th><th>Info</th>` +
      `</tr></thead><tbody>`;
    (d.packets || []).forEach((p) => {
      html +=
        `<tr data-no="${p.no}">` +
        `<td>${p.no}</td>` +
        `<td>${(p.time || 0).toFixed(6)}</td>` +
        `<td title="${escapeHtml(p.src)}">${escapeHtml(p.src)}</td>` +
        `<td title="${escapeHtml(p.dst)}">${escapeHtml(p.dst)}</td>` +
        `<td class="pcap-proto">${escapeHtml(p.proto)}</td>` +
        `<td>${p.length || ""}</td>` +
        `<td class="info" title="${escapeHtml(p.info)}">${escapeHtml(p.info)}</td>` +
        `</tr>`;
    });
    html += `</tbody></table>`;
    if (!(d.packets || []).length) {
      html = `<pre class="muted">No packets${yf ? " matching filter" : ""}.</pre>`;
    }
    box.innerHTML = html;
    box.querySelectorAll("tr[data-no]").forEach((tr) => {
      tr.addEventListener("click", () => showPcapDetail(parseInt(tr.dataset.no, 10), tr));
    });
  } catch (e) {
    if (box) box.innerHTML = errHtml({ error: String(e.message || e) });
  } finally {
    hideBusy();
  }
}

async function showPcapDetail(no, tr) {
  document.querySelectorAll(".pcap-table tr.sel").forEach((x) => x.classList.remove("sel"));
  if (tr) tr.classList.add("sel");
  showBusy("Packet detail…", `frame ${no}`, "tshark -V");
  try {
    const d = await api(`/api/pcap/detail?no=${no}`);
    if (d.error) {
      notifyError(d);
      return;
    }
    $("#detail-head").innerHTML = `<span>Frame ${no}</span>`;
    $("#detail-body").innerHTML =
      `<div class="enc">Protocol tree</div><pre>${escapeHtml(d.tree || "")}</pre>` +
      `<div class="enc">Hex</div><pre class="hex">${escapeHtml(d.hex || "")}</pre>`;
  } catch (e) {
    notifyError({ error: String(e.message || e) });
  } finally {
    hideBusy();
  }
}

$("#pcap-open")?.addEventListener("click", async () => {
  const path = $("#pcap-path")?.value.trim();
  if (!path) return toast({ title: "Missing path", message: "Enter a .pcap / .pcapng path", kind: "err" });
  showBusy("Opening capture…", path, "Indexing via tshark/capinfos");
  try {
    const r = await api("/api/pcap/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    if (r.error) return notifyError(r);
    toast({ title: "PCAP open", message: `${r.name} · ${r.packet_count ?? "?"} packets`, kind: "ok" });
    $("#pcap-meta").innerHTML =
      `<div class="ttl">${escapeHtml(r.name)}</div>` +
      `<div class="meta">${r.packet_count ?? "?"} pkts · ${fmtSize(r.size)} · ${escapeHtml(r.engine)}</div>`;
    await loadPcapPackets(true);
    const sum = await api("/api/pcap/summary");
    if (!sum.error) renderPcapStats(sum);
  } catch (e) {
    notifyError({ error: String(e.message || e) });
  } finally {
    hideBusy();
  }
});

$("#pcap-apply")?.addEventListener("click", () => loadPcapPackets(true));
$("#pcap-stats")?.addEventListener("click", async () => {
  showBusy("Protocol stats…", "io,phs + conversations", "");
  try {
    const sum = await api("/api/pcap/summary");
    if (sum.error) notifyError(sum);
    else renderPcapStats(sum);
    const dns = await api("/api/pcap/dns");
    const http = await api("/api/pcap/http");
    const extra = [];
    if ((dns.queries || []).length) {
      extra.push(
        `<div class="enc">DNS queries</div><pre>${escapeHtml(
          dns.queries.slice(0, 40).map((q) => `${q.src} → ${q.query}`).join("\n")
        )}</pre>`
      );
    }
    if ((http.requests || []).length) {
      extra.push(
        `<div class="enc">HTTP requests</div><pre>${escapeHtml(
          http.requests.slice(0, 40).map((h) => `${h.method} ${h.host}${h.uri}`).join("\n")
        )}</pre>`
      );
    }
    if (extra.length) $("#detail-body").innerHTML += extra.join("");
  } finally {
    hideBusy();
  }
});
$("#busy-stop")?.addEventListener("click", () => stopBusyLoad());
$("#pcap-close")?.addEventListener("click", async () => {
  await api("/api/pcap/close", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  $("#pcap-packets").innerHTML = "";
  $("#pcap-meta").innerHTML = `<pre class="muted">Capture closed.</pre>`;
  toast({ title: "PCAP closed", message: "", kind: "ok" });
});

(function initPaneSplit() {
  const side = document.getElementById("sidebar");
  const bar = document.getElementById("pane-split");
  const main = document.querySelector("main");
  if (!side || !bar || !main) return;
  const KEY = "tff-side-w";
  const MIN = 220;
  const DETAIL_MIN = 280;
  function clamp(w) {
    const max = Math.max(MIN, main.getBoundingClientRect().width - DETAIL_MIN);
    return Math.min(max, Math.max(MIN, w));
  }
  try {
    const saved = parseInt(localStorage.getItem(KEY) || "", 10);
    if (saved > 0) side.style.width = clamp(saved) + "px";
  } catch (_) {}
  let drag = false;
  let startX = 0;
  let startW = 0;
  bar.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    drag = true;
    startX = e.clientX;
    startW = side.getBoundingClientRect().width;
    bar.classList.add("dragging");
    document.body.classList.add("pane-dragging");
    try { bar.setPointerCapture(e.pointerId); } catch (_) {}
    e.preventDefault();
  });
  bar.addEventListener("pointermove", (e) => {
    if (!drag) return;
    side.style.width = clamp(startW + (e.clientX - startX)) + "px";
  });
  function endDrag() {
    if (!drag) return;
    drag = false;
    bar.classList.remove("dragging");
    document.body.classList.remove("pane-dragging");
    try {
      localStorage.setItem(KEY, String(Math.round(side.getBoundingClientRect().width)));
    } catch (_) {}
  }
  bar.addEventListener("pointerup", endDrag);
  bar.addEventListener("pointercancel", endDrag);
  bar.addEventListener("dblclick", () => {
    side.style.width = "";
    try { localStorage.removeItem(KEY); } catch (_) {}
  });
})();
