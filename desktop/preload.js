"use strict";

const { contextBridge, ipcRenderer } = require("electron");

let term = null;
let fitAddon = null;
let ptyDataBound = false;

contextBridge.exposeInMainWorld("tforensic", {
  pickAndOpen: () => ipcRenderer.invoke("pick-and-open"),
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
  ptyResync: () => ipcRenderer.send("pty-resync"),
  ptyKill: () => ipcRenderer.send("pty-kill"),
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
    });
    fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    const el = document.getElementById(elementId);
    term.open(el);
    // slight delay so layout has height before fit
    try { fitAddon.fit(); } catch (_) {}
    term.onData((d) => ipcRenderer.send("pty-input", d));
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
});
