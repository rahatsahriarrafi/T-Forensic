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
function beginWork(label, opts) {
  _workDepth++;
  setWorkStatus(label || "Loading…");
  const delay = opts && opts.overlayDelay != null ? opts.overlayDelay : 220;
  const forceOverlay = opts && opts.overlay === true;
  if (forceOverlay) {
    showBusy(opts.title || label || "Working…", opts.message || "Please wait…", opts.hint || "");
    return;
  }
  if (_workDepth === 1 && delay >= 0) {
    clearTimeout(_busyDelayTimer);
    _busyDelayTimer = setTimeout(() => {
      if (_workDepth > 0) {
        showBusy(
          opts?.title || label || "Working…",
          opts?.message || "Still loading — please wait.",
          opts?.hint || "Large images and packet files can take a few seconds."
        );
      }
    }, delay);
  }
}
function endWork() {
  _workDepth = Math.max(0, _workDepth - 1);
  if (_workDepth === 0) {
    clearTimeout(_busyDelayTimer);
    _busyDelayTimer = null;
    hideBusy();
    clearWorkStatus();
  }
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
    main.textContent = "Taking longer than estimated…";
    if (sub) sub.textContent = `Elapsed ${fmtEta(elapsed).replace(/^~/, "")} · watch % loaded`;
  } else {
    main.textContent = `Rough ETA ${fmtEta(left)} (may be wrong)`;
    if (sub) sub.textContent = `Elapsed ${fmtEta(elapsed).replace(/^~/, "")} · prefer % loaded`;
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
let curView = "text";

function makeNode(node) {
  const li = document.createElement("li");
  const row = document.createElement("div");
  row.className = "node " + (node.is_dir ? "dir" : "file");
  row.dataset.path = node.path;
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

async function selectFile(path, rowEl) {
  selPath = path;
  document.querySelectorAll(".node.sel").forEach((e) => e.classList.remove("sel"));
  if (rowEl) rowEl.classList.add("sel");
  const name = path.split("/").pop() || path.split(":").pop() || path;
  $("#detail-head").innerHTML =
    `<div class="path">${escapeHtml(path)}</div><div class="sub">${escapeHtml(name)}</div>`;
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

async function renderView(view) {
  curView = view;
  document.querySelectorAll(".dtab[data-view]").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view));
  if (!selPath) return;
  const body = $("#detail-body");
  const label = view === "hex" ? "Hex view" : view === "meta" ? "Metadata" : view === "hash" ? "Hashes" : "Preview";
  body.innerHTML = loadingHtml(label + "…", selPath);
  beginWork(`${label}…`, {
    title: label,
    message: selPath,
    hint: "Reading file from the evidence image.",
    overlayDelay: 200,
  });
  try {
    const pe = encodeURIComponent(selPath);
    if (view === "text" || view === "hex") {
      const mode = view === "hex" ? "hex" : "auto";
      const d = await api(`/api/file?path=${pe}&mode=${mode}`);
      if (d.error) {
        body.innerHTML = errHtml(d);
        notifyError(d);
        return;
      }
      renderAccessor(d, body);
      return;
    }
    if (view === "meta") {
      const d = await api(`/api/meta?path=${pe}`);
      if (d.error) {
        body.innerHTML = errHtml(d);
        notifyError(d);
        return;
      }
      const rows = Object.entries(d.attrs || {})
        .map(([k, v]) => {
          const hk = Number.isFinite(+k) ? "0x" + (+k).toString(16) : k;
          return `<tr><td class="k">${escapeHtml(hk)}</td><td>${escapeHtml(v)}</td></tr>`;
        })
        .join("");
      body.innerHTML = rows
        ? `<table class="meta">${rows}</table>`
        : `<pre class="muted">no metadata</pre>`;
      return;
    }
    if (view === "hash") {
      const d = await api(`/api/hash?path=${pe}`);
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
    body.innerHTML = errHtml({ error: String(e.message || e), title: "Load failed" });
  } finally {
    endWork();
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

  if (d.mode === "image" && d.data_url) {
    const wrap = document.createElement("div");
    wrap.className = "img-wrap";
    const img = document.createElement("img");
    img.src = d.data_url;
    img.alt = selPath || "";
    wrap.appendChild(img);
    body.appendChild(wrap);
    return;
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

  if (d.mode === "table") {
    if (d.items && d.items.length) {
      const list = document.createElement("pre");
      list.textContent = "Tables/views:\n" + d.items.map((t) => `  [${t.type}] ${t.name}`).join("\n");
      body.appendChild(list);
    }
    if (d.columns && d.rows) {
      const table = document.createElement("table");
      table.className = "meta data";
      const thead = document.createElement("tr");
      d.columns.forEach((c) => {
        const th = document.createElement("th");
        th.textContent = c;
        thead.appendChild(th);
      });
      table.appendChild(thead);
      d.rows.forEach((row) => {
        const tr = document.createElement("tr");
        row.forEach((cell) => {
          const td = document.createElement("td");
          td.textContent = cell;
          tr.appendChild(td);
        });
        table.appendChild(tr);
      });
      body.appendChild(table);
    }
    return;
  }

  if (d.mode === "info") {
    const pre = document.createElement("pre");
    pre.className = "muted";
    pre.textContent = (d.note || "No inline preview") +
      "\n\nUse Download or Export, then open with the matching app on your system.";
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
  const trunc = d.truncated && d.mode !== "hex" ? `\n\n… [truncated; ${fmtSize(d.size)} total]` : "";
  pre.textContent = (d.text || "") + trunc;
  body.appendChild(pre);
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

async function runSearch(q) {
  if (!q) { await loadTree(); return; }
  await withBusy("Searching…", async () => {
    const d = await api("/api/search?q=" + encodeURIComponent(q));
    const ul = document.createElement("ul");
    ul.className = "tree root";
    (d.results || []).forEach((r) => {
      ul.appendChild(makeNode({ name: r.name, path: r.path, is_dir: false, size: r.size }));
    });
    $("#tree").innerHTML = "";
    $("#tree").appendChild(ul);
  }, { title: "Search", message: q, overlayDelay: 120 });
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

let searchTimer = null;
$("#search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => runSearch(e.target.value.trim()), 200);
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
      `<br>Open via desktop <strong>Open image…</strong> or CLI <code>tforensic open / serve</code>`;
    box.appendChild(foot);

    // Also show summary in empty detail if still default
    const body = $("#detail-body");
    if (body && /Nothing loaded/i.test(body.textContent || "")) {
      body.innerHTML =
        `<div class="enc">Accepted formats</div>` +
        `<pre>` +
        (d.catalog || []).map((g) =>
          `${g.group}\n  ${(g.extensions || []).join("  ")}\n  ${g.notes || ""}`
        ).join("\n\n") +
        `\n\nUse File → Open image… or the Formats tab.</pre>`;
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
$("#pcap-close")?.addEventListener("click", async () => {
  await api("/api/pcap/close", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  $("#pcap-packets").innerHTML = "";
  $("#pcap-meta").innerHTML = `<pre class="muted">Capture closed.</pre>`;
  toast({ title: "PCAP closed", message: "", kind: "ok" });
});
