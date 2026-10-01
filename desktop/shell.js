"use strict";

const meta = document.getElementById("meta");
const viewer = document.getElementById("viewer");
const welcome = document.getElementById("welcome");
const btnBrowser = document.getElementById("btn-browser");
const termWrap = document.getElementById("term-wrap");
const busyEl = document.getElementById("busy");
const busyTitle = document.getElementById("busy-title");
const busyMsg = document.getElementById("busy-msg");
const busyHint = document.getElementById("busy-hint");
const busyEta = document.getElementById("busy-eta");
const busyEtaMain = document.getElementById("busy-eta-main");
const busyEtaSub = document.getElementById("busy-eta-sub");
const busyPct = document.getElementById("busy-pct");
const busyFill = document.getElementById("busy-fill");
const toastBox = document.getElementById("toast");
let caseUrl = null;
let termReady = false;
let ptyStarted = false;
let etaTimer = null;
let etaStartedAt = 0;
let etaTotalSec = 0;
let loadProgress = 0;
let loadStartedAt = 0;

function fmtEta(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (s < 60) return `~${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m < 60) return r ? `~${m}m ${String(r).padStart(2, "0")}s` : `~${m}m`;
  const h = Math.floor(m / 60);
  return `~${h}h ${String(m % 60).padStart(2, "0")}m`;
}

function setLoadProgress(fraction) {
  if (!busyPct || !busyFill) return;
  if (fraction == null || !Number.isFinite(Number(fraction))) {
    busyPct.textContent = "…";
    busyFill.classList.add("indeterminate");
    busyFill.style.width = "35%";
    return;
  }
  const p = Math.max(0, Math.min(1, Number(fraction)));
  // never go backwards (except reset via hide)
  if (!(p + 0.001 < loadProgress && p > 0.02)) {
    loadProgress = p;
  }
  if (!loadStartedAt) loadStartedAt = Date.now();
  const pct = Math.round(loadProgress * 100);
  busyPct.textContent = pct + "%";
  busyFill.classList.remove("indeterminate");
  busyFill.style.width = pct + "%";

  // Keep hint in sync with the bar (avoid "35% loaded" next to "70%")
  if (busyHint && !busyHint.dataset.locked) {
    busyHint.textContent = `${pct}% loaded`;
  }

  updateEtaDisplay();
}

function updateEtaDisplay() {
  if (!busyEtaMain) return;
  const elapsed = loadStartedAt ? (Date.now() - loadStartedAt) / 1000 : 0;
  const pct = Math.round(loadProgress * 100);

  // Milestone jumps (e.g. 2% → 70% in <1s) are not real throughput — don't invent "~0s left"
  const canAdapt =
    loadProgress >= 0.12 &&
    loadProgress < 0.97 &&
    elapsed >= 3;

  if (canAdapt) {
    const rem = elapsed * (1 - loadProgress) / Math.max(loadProgress, 0.01);
    busyEtaMain.textContent = `About ${fmtEta(rem).replace(/^~/, "")} left`;
    busyEtaSub.textContent =
      `${pct}% · elapsed ${fmtEta(elapsed).replace(/^~/, "")}` +
      (etaTotalSec ? ` · first guess ${fmtEta(etaTotalSec)}` : "");
    busyEta.hidden = false;
    return;
  }

  if (etaTotalSec > 0) {
    const left = Math.max(0, etaTotalSec - elapsed);
    if (left <= 0 && elapsed > etaTotalSec) {
      busyEtaMain.textContent = "Taking longer than the first guess…";
      busyEtaSub.textContent = `${pct}% · elapsed ${fmtEta(elapsed).replace(/^~/, "")}`;
    } else {
      busyEtaMain.textContent = `Rough ETA ${fmtEta(left)}`;
      busyEtaSub.textContent =
        `${pct}% · elapsed ${fmtEta(elapsed).replace(/^~/, "")}` +
        (etaTotalSec ? ` · first guess ${fmtEta(etaTotalSec)}` : "");
    }
    busyEta.hidden = false;
    return;
  }

  if (loadProgress > 0 && loadProgress < 1) {
    busyEtaMain.textContent = "Working…";
    busyEtaSub.textContent = `${pct}% loaded · elapsed ${fmtEta(elapsed).replace(/^~/, "")}`;
    busyEta.hidden = false;
  }
}

function stopEta() {
  if (etaTimer) clearInterval(etaTimer);
  etaTimer = null;
  etaTotalSec = 0;
  if (busyEta) busyEta.hidden = true;
  if (busyHint) delete busyHint.dataset.locked;
}

function tickEta() {
  updateEtaDisplay();
}

function startEta(seconds) {
  const sec = Number(seconds);
  if (!Number.isFinite(sec) || sec <= 0) return;
  etaTotalSec = sec;
  etaStartedAt = Date.now();
  if (!loadStartedAt) loadStartedAt = Date.now();
  updateEtaDisplay();
  if (etaTimer) clearInterval(etaTimer);
  etaTimer = setInterval(tickEta, 1000);
}

function showBusy(title, msg, hint, etaSeconds, progress) {
  busyTitle.textContent = title || "Working…";
  busyMsg.textContent = msg || "Please wait — large images can take a while.";
  if (hint) {
    busyHint.textContent = hint;
    // Stage hints without an explicit % may lock briefly; unlock when progress updates
    busyHint.dataset.locked = /%/.test(hint) ? "1" : "";
    if (!busyHint.dataset.locked) delete busyHint.dataset.locked;
  } else if (!busyHint.textContent) {
    busyHint.textContent = "Watch % loaded — ETA is only a rough guess.";
  }
  busyEl.classList.add("show");
  if (!loadStartedAt) loadStartedAt = Date.now();
  if (progress != null && Number.isFinite(Number(progress))) {
    setLoadProgress(progress);
  } else if (loadProgress <= 0) {
    setLoadProgress(null); // indeterminate
  }
  if (etaSeconds != null && Number(etaSeconds) > 0) startEta(etaSeconds);
  else updateEtaDisplay();
}

function hideBusy() {
  busyEl.classList.remove("show");
  stopEta();
  loadProgress = 0;
  loadStartedAt = 0;
  if (busyFill) {
    busyFill.classList.add("indeterminate");
    busyFill.style.width = "35%";
  }
  if (busyPct) busyPct.textContent = "0%";
}

function toast({ title, message, suggestion, kind }) {
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
  toastBox.appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 14000 : 6000);
}

async function openCase() {
  const prevMeta = meta.textContent;
  meta.textContent = "Choose a file…";
  try {
    const result = await window.tforensic.pickAndOpen();
    if (!result || result.canceled) {
      hideBusy();
      meta.textContent = caseUrl ? prevMeta : "No case loaded";
      return;
    }
    if (result.ok === false) {
      hideBusy();
      return;
    }
    // Success path: case-opened / progress handlers manage the overlay.
    // If invoke returned after open finished, ensure overlay is cleared.
    if (caseUrl) hideBusy();
  } catch (err) {
    hideBusy();
    meta.textContent = "Open failed";
    toast({
      title: "Could not open",
      message: String(err.message || err),
      suggestion: "Check Formats list and that xmount / qemu-utils / sleuthkit are installed.",
      kind: "err",
    });
  }
}

function showCase({ url, session, image }) {
  setLoadProgress(1);
  setTimeout(() => hideBusy(), 200);
  caseUrl = url;
  viewer.hidden = false;
  welcome.hidden = true;
  viewer.src = url;
  btnBrowser.disabled = false;
  const name = (image || "").split(/[\\/]/).pop();
  meta.textContent = `${name} · session ${session}`;
  // Case changed → old PTY env is stale; restart so tree ↔ terminal match
  const termWasOpen = termWrap.classList.contains("open");
  ptyStarted = false;
  window.tforensic.ptyKill?.();
  if (termWasOpen && termReady) {
    setTimeout(async () => {
      const size = refitPty() || { cols: 80, rows: 24 };
      const ok = await window.tforensic.ptyAvailable();
      if (!ok) return;
      window.tforensic.ptyStart(size);
      ptyStarted = true;
      window.tforensic.writeTerminal?.("[TFF] terminal restarted for new case — run tfor-here");
      window.tforensic.focusTerminal?.();
    }, 400);
  }
  // Pull engine version into shell chrome
  fetch(url.replace(/\/?$/, "/") + "api/version")
    .then((r) => r.json())
    .then((v) => {
      if (!v || !v.version) return;
      const el = document.getElementById("shell-version");
      if (el) el.textContent = `v${v.version}`;
      const by = document.querySelector("#welcome .byline");
      if (by) by.textContent = `TFF · by Team NullX · v${v.version}`;
    })
    .catch(() => {});
  toast({
    title: "Case ready",
    message: `${name} is open for analysis.`,
    suggestion: termWasOpen
      ? "Terminal restarted for this session — run tfor-here"
      : "Open Terminal after the tree loads for matching mounts.",
    kind: "ok",
  });
}

document.getElementById("btn-open").onclick = openCase;
document.getElementById("btn-open-2").onclick = openCase;
btnBrowser.onclick = () => caseUrl && window.tforensic.openExternal(caseUrl);
window.tforensic.onCaseOpened(showCase);

window.tforensic.onOpenProgress?.((p) => {
  showBusy(
    p.title || "Working…",
    p.message || "Please wait…",
    p.hint || "Watch % loaded — ETA is approximate.",
    p.etaSeconds,
    p.progress
  );
  if (p.message) meta.textContent = p.progress != null
    ? `${Math.round(p.progress * 100)}% · ${p.message}`
    : p.message;
});

window.tforensic.onOpenError?.((err) => {
  hideBusy();
  meta.textContent = "Open failed";
  toast({
    title: err.title || "Could not open image",
    message: err.message || "Unknown error",
    suggestion: err.suggestion || "",
    kind: "err",
  });
});

window.tforensic.onOpenCanceled?.(() => {
  hideBusy();
  if (!caseUrl) meta.textContent = "No case loaded";
});

const TERM_H_KEY = "tff.termHeight";
const termResizer = document.getElementById("term-resizer");
const termHead = document.getElementById("term-head");

function applyTermHeight(px) {
  const min = 120;
  const max = Math.floor(window.innerHeight * 0.7);
  const h = Math.max(min, Math.min(max, Math.round(px)));
  termWrap.style.setProperty("--term-h", `${h}px`);
  termWrap.style.height = `${h}px`;
  termWrap.style.flexBasis = `${h}px`;
  try { localStorage.setItem(TERM_H_KEY, String(h)); } catch (_) {}
  return h;
}

try {
  const saved = parseInt(localStorage.getItem(TERM_H_KEY), 10);
  if (saved > 80) applyTermHeight(saved);
} catch (_) {}

function refitPty() {
  if (!termWrap.classList.contains("open") || !termReady) return null;
  const size = window.tforensic.fitTerminal();
  if (size) window.tforensic.ptyResize(size.cols, size.rows);
  return size;
}

let lastSelected = null; // { path, name } from viewer iframe

window.addEventListener("message", (ev) => {
  const d = ev && ev.data;
  if (!d || d.type !== "tff-selected") return;
  if (d.path) lastSelected = { path: d.path, name: d.name || "" };
});

function getViewerSelection() {
  // Always prefer live selection from the open tree
  try {
    const iframe = document.getElementById("viewer");
    const sel = iframe && iframe.contentWindow && iframe.contentWindow.__tffGetSelection
      ? iframe.contentWindow.__tffGetSelection()
      : null;
    if (sel && sel.path) {
      lastSelected = { path: sel.path, name: sel.name || "" };
      return lastSelected;
    }
  } catch (_) {}
  if (lastSelected && lastSelected.path) return lastSelected;
  return null;
}

/** Export the tree-selected file and cd the terminal to it (for exiftool, etc.). */
async function terminalOpenSelectedFile() {
  if (!caseUrl) {
    window.tforensic.writeTerminal?.("[TFF] Open an image first");
    return false;
  }
  const sel = getViewerSelection();
  if (!sel || !sel.path) {
    window.tforensic.writeTerminal?.(
      "[TFF] No file selected — click a file in the Tree, then Sync / Open selected"
    );
    return false;
  }
  if (String(sel.path).startsWith("inode:")) {
    window.tforensic.writeTerminal?.(
      "[TFF] Disk inode selected — use Disk extract, then Sync again"
    );
    return false;
  }
  try {
    window.tforensic.writeTerminal?.(
      `[TFF] Loading selected file into terminal: ${sel.name || sel.path}`
    );
    const base = caseUrl.replace(/\/?$/, "/");
    const res = await fetch(base + "api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: sel.path }),
    });
    const d = await res.json();
    if (d.error || !d.exported) {
      window.tforensic.writeTerminal?.(
        `[TFF] export failed: ${d.error || d.message || "unknown"}`
      );
      return false;
    }
    const file = d.exported;
    const dir = file.replace(/[\\/][^\\/]+$/, "") || file;
    // small delay so any prior shell cd finishes first
    await new Promise((r) => setTimeout(r, 120));
    window.tforensic.ptyCd?.(dir, file, sel.name || file.split(/[\\/]/).pop());
    return true;
  } catch (err) {
    window.tforensic.writeTerminal?.(
      `[TFF] could not open selection in terminal: ${err.message || err}`
    );
    return false;
  }
}

async function toggleTerm() {
  const open = termWrap.classList.toggle("open");
  if (!open) return;
  if (!termReady) {
    try {
      window.tforensic.initTerminal("terminal");
      termReady = true;
    } catch (err) {
      window.tforensic.writeTerminal?.("[xterm failed to load]");
      toast({
        title: "Terminal unavailable",
        message: err.message,
        suggestion: "Use an external terminal: python3 -m tforensic …",
        kind: "err",
      });
      return;
    }
  }
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const size = refitPty();
  if (!ptyStarted) {
    const ok = await window.tforensic.ptyAvailable();
    if (!ok) {
      window.tforensic.writeTerminal("node-pty not available. Use: python3 -m tforensic …");
      return;
    }
    window.tforensic.ptyStart(size || { cols: 80, rows: 24 });
    ptyStarted = true;
    // Let the shell finish sourcing rc, then jump to selected file
    setTimeout(() => { terminalOpenSelectedFile(); }, 700);
  } else {
    await terminalOpenSelectedFile();
  }
  window.tforensic.focusTerminal?.();
}

document.getElementById("btn-term").onclick = toggleTerm;
document.getElementById("btn-term-close").onclick = (e) => {
  e.stopPropagation();
  termWrap.classList.remove("open");
};
document.getElementById("btn-term-sync").onclick = async (e) => {
  e.stopPropagation();
  if (!ptyStarted) {
    await toggleTerm();
    return;
  }
  // Refresh env, but do not cd away — then load the tree-selected file
  try {
    await window.tforensic.ptyResync?.({ skipCd: true });
  } catch (_) {}
  await new Promise((r) => setTimeout(r, 150));
  const ok = await terminalOpenSelectedFile();
  if (!ok) {
    toast({
      title: "Sync",
      message: "Select a file in the Tree first, then click Sync.",
      kind: "err",
    });
  } else {
    toast({
      title: "Synced",
      message: "Selected file is ready in the terminal ($TFOR_FILE).",
      kind: "ok",
    });
  }
  window.tforensic.focusTerminal?.();
};
const btnTermHere = document.getElementById("btn-term-here");
if (btnTermHere) {
  btnTermHere.onclick = async (e) => {
    e.stopPropagation();
    if (!termWrap.classList.contains("open") || !ptyStarted) {
      await toggleTerm();
      return;
    }
    await terminalOpenSelectedFile();
    window.tforensic.focusTerminal?.();
  };
}

window.tforensic.onPtyExit?.(() => {
  ptyStarted = false;
});

let termDragging = false;
let termDragStartY = 0;
let termDragStartH = 0;
let termDragPointerId = null;

function beginTermDrag(e) {
  if (!termWrap.classList.contains("open")) return;
  if (e.target && e.target.closest && e.target.closest("#btn-term-close")) return;
  e.preventDefault();
  e.stopPropagation();
  termDragging = true;
  termDragPointerId = e.pointerId;
  termDragStartY = e.clientY;
  termDragStartH = termWrap.getBoundingClientRect().height;
  termResizer.classList.add("dragging");
  document.body.style.cursor = "ns-resize";
  document.body.style.userSelect = "none";
  try {
    e.currentTarget.setPointerCapture(e.pointerId);
  } catch (_) {}
}

function moveTermDrag(e) {
  if (!termDragging) return;
  if (termDragPointerId != null && e.pointerId !== termDragPointerId) return;
  applyTermHeight(termDragStartH + (termDragStartY - e.clientY));
  refitPty();
}

function endTermDrag(e) {
  if (!termDragging) return;
  if (termDragPointerId != null && e.pointerId !== termDragPointerId) return;
  termDragging = false;
  termDragPointerId = null;
  termResizer.classList.remove("dragging");
  document.body.style.cursor = "";
  document.body.style.userSelect = "";
  try {
    if (e.currentTarget && e.currentTarget.releasePointerCapture) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
  } catch (_) {}
  refitPty();
  window.tforensic.focusTerminal?.();
}

[termResizer, termHead].forEach((el) => {
  if (!el) return;
  el.addEventListener("pointerdown", beginTermDrag);
  el.addEventListener("pointermove", moveTermDrag);
  el.addEventListener("pointerup", endTermDrag);
  el.addEventListener("pointercancel", endTermDrag);
});

window.addEventListener("resize", () => {
  if (!termWrap.classList.contains("open") || !termReady) return;
  const cur = termWrap.getBoundingClientRect().height;
  applyTermHeight(cur);
  refitPty();
});

window.tforensic.getState().then((s) => {
  if (s.url) showCase(s);
});
