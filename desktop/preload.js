"use strict";

const { contextBridge, ipcRenderer, clipboard } = require("electron");

let term = null;
let fitAddon = null;
let ptyDataBound = false;

function pasteIntoPty() {
  let text = "";
  try {
    text = clipboard.readText() || "";
  } catch (_) {}
  if (!text) {
    try {
      text = clipboard.readText("selection") || "";
    } catch (_) {}
  }
  if (text) ipcRenderer.send("pty-input", text);
}

function copyFromTerm() {
  if (!term || !term.hasSelection()) return false;
  const s = term.getSelection();
  if (!s) return false;
  try {
    clipboard.writeText(s);
  } catch (_) {
    return false;
  }
  return true;
}

contextBridge.exposeInMainWorld("tforensic", {
  pickAndOpen: () => ipcRenderer.invoke("pick-and-open"),
  pickAndOpenFolder: () => ipcRenderer.invoke("pick-and-open-folder"),
  getState: () => ipcRenderer.invoke("get-state"),
  openExternal: (url) => ipcRenderer.invoke("open-external", url),
  onCaseOpened: (cb) => ipcRenderer.on("case-opened", (_e, data) => cb(data)),
  onOpenProgress: (cb) => ipcRenderer.on("open-progress", (_e, data) => cb(data)),
  onOpenError: (cb) => ipcRenderer.on("open-error", (_e, data) => cb(data)),
  onOpenCanceled: (cb) => ipcRenderer.on("open-canceled", () => cb()),
  ptyAvailable: () => ipcRenderer.invoke("pty-available"),
  ptyStart: (size) => ipcRenderer.send("pty-start", size || null),
  ptyInput: (data) => ipcRenderer.send("pty-input", data),
  ptyResize: (cols, rows) => ipcRenderer.send("pty-resize", { cols, rows }),
  ptyResync: (opts) => ipcRenderer.invoke("pty-resync", opts || {}),
  ptyKill: () => ipcRenderer.send("pty-kill"),
  ptyCd: (dir, file, name) => ipcRenderer.send("pty-cd", { dir, file, name }),
  onPtyData: (cb) => ipcRenderer.on("pty-data", (_e, data) => cb(data)),
  onPtyExit: (cb) => ipcRenderer.on("pty-exit", () => cb()),

  initTerminal: (elementId) => {
    if (term) {
      try { term.focus(); } catch (_) {}
      return { cols: term.cols, rows: term.rows };
    }
    const { Terminal } = require("xterm");
    const { FitAddon } = require("xterm-addon-fit");
    // convertEol must be false with node-pty — otherwise typing/newlines behave oddly
    term = new Terminal({
      theme: {
        background: "#0a1018",
        foreground: "#e8eef7",
        cursor: "#00e5c0",
        selectionBackground: "rgba(0, 229, 192, 0.28)",
      },
      fontFamily: "IBM Plex Mono, JetBrains Mono, Fira Code, ui-monospace, monospace",
      fontSize: 13,
      lineHeight: 1.2,
      cursorBlink: true,
      cursorStyle: "block",
      convertEol: false,
      scrollback: 5000,
      allowTransparency: false,
      macOptionIsMeta: true,
      rightClickSelectsWord: false,
    });
    fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    const el = document.getElementById(elementId);
    term.open(el);
    try { fitAddon.fit(); } catch (_) {}
    term.onData((d) => ipcRenderer.send("pty-input", d));

    // Copy / Paste shortcuts (Ctrl+Shift+C / Ctrl+Shift+V)
    term.attachCustomKeyEventHandler((ev) => {
      if (ev.type !== "keydown") return true;
      const ctrl = ev.ctrlKey || ev.metaKey;
      if (!ctrl) return true;
      const key = (ev.key || "").toLowerCase();
      if (ev.shiftKey && key === "c") {
        copyFromTerm();
        return false;
      }
      if (ev.shiftKey && key === "v") {
        pasteIntoPty();
        return false;
      }
      // Ctrl+C with an active selection → copy (do not send SIGINT)
      if (!ev.shiftKey && key === "c" && term.hasSelection()) {
        copyFromTerm();
        return false;
      }
      return true;
    });

    // Right-click: copy selection, otherwise paste
    el.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      if (term.hasSelection()) copyFromTerm();
      else pasteIntoPty();
      try { term.focus(); } catch (_) {}
    });

    // Middle-click paste (Linux primary selection)
    el.addEventListener("mousedown", (e) => {
      if (e.button !== 1) return;
      e.preventDefault();
      pasteIntoPty();
    });

    // Native paste event (some hosts)
    el.addEventListener("paste", (e) => {
      try {
        const t = (e.clipboardData && e.clipboardData.getData("text")) || "";
        if (t) {
          e.preventDefault();
          ipcRenderer.send("pty-input", t);
        }
      } catch (_) {}
    });

    if (!ptyDataBound) {
      ptyDataBound = true;
      ipcRenderer.on("pty-data", (_e, data) => {
        if (term) term.write(data);
      });
      ipcRenderer.on("pty-exit", () => {
        if (term) term.write("\r\n\x1b[33m[shell exited — reopen Terminal to start again]\x1b[0m\r\n");
      });
    }
    term.focus();
    return { cols: term.cols, rows: term.rows };
  },

  fitTerminal: () => {
    if (!fitAddon || !term) return null;
    try { fitAddon.fit(); } catch (_) {}
    return { cols: term.cols, rows: term.rows };
  },

  focusTerminal: () => {
    if (term) {
      try { term.focus(); } catch (_) {}
    }
  },

  writeTerminal: (text) => {
    if (term) term.writeln(text);
  },

  termCopy: () => copyFromTerm(),
  termPaste: () => pasteIntoPty(),
});
