"use strict";

const { app, BrowserWindow, ipcMain, dialog, Menu, shell } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

let mainWindow = null;
let engineProc = null;
let engineUrl = null;
let sessionId = null;
let ptyProcess = null;

const isDev = !app.isPackaged;
app.setName("Team Forensic Framework");
if (process.platform === "linux") {
  app.commandLine.appendSwitch("class", "Team Forensic Framework");
}

function repoRoot() {
  if (isDev) return path.resolve(__dirname, "..");
  return path.resolve(process.resourcesPath);
}

function engineDir() {
  if (isDev) return path.join(repoRoot(), "engine");
  return path.join(process.resourcesPath, "engine");
}

function webDir() {
  if (isDev) return path.join(repoRoot(), "web");
  return path.join(process.resourcesPath, "web");
}

function pythonBin() {
  return process.env.TFOR_PYTHON || "python3";
}

function stopEngine() {
  if (engineProc && !engineProc.killed) {
    try {
      engineProc.kill("SIGTERM");
    } catch (_) {}
  }
  engineProc = null;
  engineUrl = null;
}

function sendProgress(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("open-progress", payload);
  }
}

function sendOpenError(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("open-error", payload);
  }
}

function explainOpenFailure(raw, imagePath) {
  const text = String(raw || "");
  const low = text.toLowerCase();
  const ext = path.extname(imagePath || "").toLowerCase();
  let title = "Could not open image";
  let message = text.split("\n").find((l) => /^error:/i.test(l)) || "";
  message = message.replace(/^error:\s*/i, "").trim();
  const detailLine = text.split("\n").find((l) => /^detail:/i.test(l));
  const detail = detailLine ? detailLine.replace(/^detail:\s*/i, "").trim() : "";
  // Prefer real exception text when CLI only emitted a generic "error:" line
  if (
    detail &&
    (!message ||
      /^opening the image failed\.?$/i.test(message) ||
      /^could not open evidence\.?$/i.test(message) ||
      message.length < 24)
  ) {
    message = detail;
  }
  if (!message) message = text.trim() || "Unknown error";

  let suggestion =
    text.split("\n").find((l) => /^hint:/i.test(l)) || "";
  suggestion = suggestion.replace(/^hint:\s*/i, "").trim();

  if (!suggestion) {
    if (low.includes("xmount") && (low.includes("not found") || low.includes("no such") || low.includes("missing"))) {
      title = "xmount missing";
      suggestion = "Install: sudo apt install xmount";
    } else if (low.includes("qemu-img") || low.includes("qemu-utils")) {
      title = "qemu-img missing";
      suggestion = "Install: sudo apt install qemu-utils";
    } else if (low.includes("sleuthkit") || low.includes("mmls") || low.includes("fls")) {
      title = "Sleuth Kit missing";
      suggestion = "Install: sudo apt install sleuthkit";
    } else if (low.includes("externally-managed") || low.includes("impacket") || low.includes("requirements")) {
      title = "Python deps missing";
      suggestion = "From the repo: ./install.sh   (creates .venv on Kali)";
    } else if (low.includes("timed out") || low.includes("timeout")) {
      title = "Taking too long";
      suggestion = ext === ".ova"
        ? "OVA extract/convert can take many minutes. Retry with more free space in /tmp."
        : "Retry; ensure the image is local (not a slow network path).";
    } else if (low.includes("python") || low.includes("enoent") || low.includes("no module named")) {
      title = "Python engine failed";
      suggestion = "Run: cd T-Forensic && ./install.sh && tforensic deps";
    } else if (low.includes("unsupported") || low.includes("not an ad1")) {
      title = "Unsupported or invalid image";
      suggestion = "Check Formats tab. Use .ad1 / .E01 / .dd / .ova / .vdi / .qcow2 / .pcap.";
    } else {
      suggestion =
        "Run in a terminal: tforensic deps\n" +
        "Then: sudo apt install xmount sleuthkit qemu-utils\n" +
        "Retry open, or: tforensic serve /path/to/image";
    }
  }

  // Persist for support (menu launch log dir)
  try {
    const logDir = path.join(os.homedir(), ".cache", "tforensic");
    fs.mkdirSync(logDir, { recursive: true });
    fs.appendFileSync(
      path.join(logDir, "open-errors.log"),
      `\n======== ${new Date().toISOString()} ========\n` +
        `image: ${imagePath || "?"}\n` +
        `title: ${title}\n` +
        `message: ${message}\n` +
        `suggestion: ${suggestion}\n` +
        `raw:\n${text}\n`
    );
  } catch (_) {}

  return {
    title,
    message: message.slice(0, 600),
    suggestion,
    detail: (detail || text).slice(0, 1200),
  };
}

function progressForLine(line, imagePath) {
  const t = line.trim();
  if (!t) return null;
  const ext = path.extname(imagePath || "").toLowerCase();

  const prog = t.match(/^PROGRESS:\s*([\d.]+)(?:\s*\|\s*(.*))?$/i);
  if (prog) {
    const fraction = Math.max(0, Math.min(1, parseFloat(prog[1])));
    const stage = (prog[2] || "").trim();
    return {
      title: stage ? stage.charAt(0).toUpperCase() + stage.slice(1) + "…" : "Loading…",
      message: path.basename(imagePath || "") || stage,
      hint: `${Math.round(fraction * 100)}% loaded` + (stage ? ` · ${stage}` : ""),
      progress: fraction,
    };
  }
  if (/^loaded:\s*(\d+)%/i.test(t)) {
    const m = t.match(/^loaded:\s*(\d+)%(?:\s*[—-]\s*(.*))?/i);
    if (m) {
      const fraction = parseInt(m[1], 10) / 100;
      return {
        title: "Loading…",
        message: m[2] || path.basename(imagePath || ""),
        hint: `${m[1]}% loaded`,
        progress: fraction,
      };
    }
  }

  const etaSec = t.match(/^ETA_SECONDS:\s*([\d.]+)/i);
  if (etaSec) {
    const seconds = parseFloat(etaSec[1]);
    return {
      title: "Opening image…",
      message: path.basename(imagePath || ""),
      hint: `Rough ETA ${formatEta(seconds)} (watch % loaded — ETA can be off)`,
      etaSeconds: seconds,
      progress: 0.1,
    };
  }
  if (/^ETA:/i.test(t)) {
    return {
      title: "Opening image…",
      message: path.basename(imagePath || ""),
      hint: t.replace(/^ETA:\s*/i, "") + " · ETA is approximate",
      progress: 0.1,
    };
  }
  if (/^ETA_STAGE:/i.test(t)) {
    const parts = t.replace(/^ETA_STAGE:\s*/i, "").split("|");
    return {
      title: parts[0] || "Working…",
      message: parts[2] || "In progress",
      hint: parts[1] ? `Stage est. ${formatEta(parseFloat(parts[1]))}` : "",
    };
  }
  if (/mounting with xmount/i.test(t)) {
    return {
      title: "Mounting with xmount…",
      message: "Creating a read-only virtual disk via FUSE.",
      hint: "70% · xmount FUSE mount (local images are usually under a minute)",
      progress: 0.7,
    };
  }
  if (/parsing evidence/i.test(t)) {
    return {
      title: ext === ".ad1" ? "Parsing AD1…" : "Parsing evidence…",
      message: "Building the session workspace.",
      hint: "55% · almost ready",
      progress: 0.55,
    };
  }
  if (/^Opening /i.test(t)) {
    return {
      title: "Opening image…",
      message: t.replace(/^Opening\s+/i, "").replace(/\s*…$/, ""),
      hint: "5% · starting",
      progress: 0.05,
    };
  }
  if (/extract ova/i.test(t)) {
    return {
      title: "Extracting OVA…",
      message: "Unpacking the virtual appliance (large files take time).",
      hint: "25% · unpacking OVA",
      progress: 0.25,
    };
  }
  if (/convert disk|qemu-img/i.test(t)) {
    return {
      title: "Converting disk…",
      message: "qemu-img is converting the virtual disk for analysis.",
      hint: "50% · converting disk",
      progress: 0.5,
    };
  }
  if (/step: ready/i.test(t)) {
    return {
      title: "Starting UI…",
      message: "Evidence is ready; bringing up the viewer.",
      hint: "98% loaded",
      progress: 0.98,
      etaSeconds: 0,
    };
  }
  return null;
}

function formatEta(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (s < 60) return `~${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m < 60) return r ? `~${m}m ${String(r).padStart(2, "0")}s` : `~${m}m`;
  const h = Math.floor(m / 60);
  return `~${h}h ${String(m % 60).padStart(2, "0")}m`;
}

function localEtaHint(imagePath) {
  try {
    const st = fs.statSync(imagePath);
    const size = st.size || 0;
    const ext = path.extname(imagePath).toLowerCase();
    let sec = 8;
    if (ext === ".ad1") sec = 3 + size / (80 * 1024 * 1024);
    else if (ext === ".ova") sec = 15 + size / (40 * 1024 * 1024) + (size * 0.7) / (35 * 1024 * 1024);
    else if ([".e01", ".ex01", ".ewf", ".s01"].includes(ext)) sec = 8 + (size / (120 * 1024 * 1024)) * 0.15;
    else if ([".vmdk", ".vhd", ".vhdx"].includes(ext)) sec = 10 + size / (35 * 1024 * 1024);
    else sec = 6 + Math.min(20, size / (200 * 1024 * 1024) * 0.02);
    sec = Math.max(2, Math.min(sec, 6 * 3600));
    return { seconds: sec, human: formatEta(sec), size };
  } catch {
    return { seconds: 30, human: "~30s", size: 0 };
  }
}

function killPty() {
  if (!ptyProcess) return;
  const proc = ptyProcess;
  ptyProcess = null;
  try { proc.kill(); } catch (_) {}
}

function sendToRenderer(channel, ...args) {
  try {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    const wc = mainWindow.webContents;
    if (!wc || wc.isDestroyed()) return;
    wc.send(channel, ...args);
  } catch (_) {
    // Window/webContents gone — ignore (common during case reload / quit)
  }
}

function startEngine(imagePath) {
  return new Promise((resolve, reject) => {
    stopEngine();
    killPty(); // drop stale shell env from previous session
    const env = {
      ...process.env,
      PYTHONPATH: engineDir() + (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : ""),
    };
    const args = [
      "-m",
      "tforensic",
      "serve",
      imagePath,
      "--host",
      "127.0.0.1",
      "--port",
      "0",
      "--web",
      webDir(),
    ];
    const ext = path.extname(imagePath || "").toLowerCase();
    const timeoutMs = ext === ".ova" ? 15 * 60 * 1000 : 5 * 60 * 1000;
    const local = localEtaHint(imagePath);

    sendProgress({
      title: "Starting engine…",
      message: path.basename(imagePath),
      hint: `0% · rough ETA ${local.human} (watch % loaded)`,
      etaSeconds: local.seconds,
      progress: 0.02,
    });

    engineProc = spawn(pythonBin(), args, {
      cwd: engineDir(),
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let settled = false;
    let stderrBuf = "";
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        try { engineProc.kill("SIGTERM"); } catch (_) {}
        reject(new Error("Engine start timed out"));
      }
    }, timeoutMs);

    const onData = (buf) => {
      const text = buf.toString();
      process.stdout.write(text);
      text.split(/\r?\n/).forEach((line) => {
        const prog = progressForLine(line, imagePath);
        if (prog) sendProgress(prog);
      });
      const m = text.match(/TFOR_READY (http:\/\/[^\s]+) session=(\S+)/);
      if (m && !settled) {
        settled = true;
        clearTimeout(timer);
        engineUrl = m[1];
        sessionId = m[2];
        resolve({ url: engineUrl, session: sessionId });
      }
    };
    engineProc.stdout.on("data", onData);
    engineProc.stderr.on("data", (b) => {
      const t = b.toString();
      stderrBuf += t;
      process.stderr.write(t);
      t.split(/\r?\n/).forEach((line) => {
        if (/^error:|^hint:/i.test(line.trim())) {
          sendProgress({
            title: "Problem detected…",
            message: line.replace(/^(error|hint):\s*/i, ""),
            hint: "Collecting details…",
          });
        }
      });
    });
    engineProc.on("error", (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(err);
      }
    });
    engineProc.on("exit", (code) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        const detail = stderrBuf.trim() || `Engine exited early (code ${code})`;
        reject(new Error(detail));
      }
    });
  });
}

function createWindow() {
  const iconPath = [
    path.join(__dirname, "assets", "tforensic-app.png"),
    path.join(__dirname, "build", "icon.png"),
    path.join(__dirname, "assets", "icon-256.png"),
    path.join(__dirname, "assets", "tff-app.png"),
  ].find((p) => fs.existsSync(p));

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#070b12",
    title: `Team Forensic Framework v${require("./package.json").version}`,
    icon: iconPath,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  if (iconPath && process.platform === "linux") {
    try { mainWindow.setIcon(iconPath); } catch (_) {}
  }

  mainWindow.loadFile(path.join(__dirname, "shell.html"));
  mainWindow.on("closed", () => {
    killPty();
    mainWindow = null;
  });
}

function buildMenu() {
  const template = [
    {
      label: "File",
      submenu: [
        {
          label: "Open evidence…",
          accelerator: "CmdOrCtrl+O",
          click: () => ipcOpenImage(),
        },
        { type: "separator" },
        { role: "quit" },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function ipcOpenImage(filePath) {
  let imagePath = filePath;
  if (!imagePath) {
    const res = await dialog.showOpenDialog(mainWindow, {
      title: "Open forensic image",
      properties: ["openFile"],
      filters: [
        {
          name: "Forensic images",
          extensions: [
            "ad1",
            "e01", "ex01", "ewf", "s01",
            "dd", "raw", "img", "bin",
            "aff", "afd", "aaff",
            "vdi", "qcow", "qcow2",
            "vmdk", "vhd", "vhdx",
            "ova",
            "pcap", "pcapng", "cap", "dmp", "pkt",
            "snoop", "erf", "ntar", "pklg", "ipfix",
            "bfr", "rf5", "k12", "vwr", "netmon",
          ],
        },
        { name: "AD1 logical", extensions: ["ad1"] },
        { name: "EWF / E01", extensions: ["e01", "ex01", "ewf", "s01"] },
        { name: "OVA appliance", extensions: ["ova"] },
        { name: "Raw / DD", extensions: ["dd", "raw", "img", "bin", "001"] },
        { name: "Virtual disks", extensions: ["vdi", "qcow", "qcow2", "vmdk", "vhd", "vhdx"] },
        {
          name: "Network / packets",
          extensions: [
            "pcap", "pcapng", "cap", "dmp", "pkt",
            "snoop", "erf", "ntar", "pklg", "ipfix",
            "bfr", "rf5", "k12", "vwr", "netmon", "enc", "tr1",
          ],
        },
        { name: "All files", extensions: ["*"] },
      ],
    });
    if (res.canceled || !res.filePaths.length) {
      if (mainWindow) mainWindow.webContents.send("open-canceled");
      return { canceled: true };
    }
    imagePath = res.filePaths[0];
  }
  try {
    const { url, session } = await startEngine(imagePath);
    if (mainWindow) {
      mainWindow.webContents.send("case-opened", { url, session, image: imagePath });
    }
    return { ok: true, url, session, image: imagePath };
  } catch (err) {
    const friendly = explainOpenFailure(err.message || err, imagePath);
    sendOpenError(friendly);
    dialog.showErrorBox(
      friendly.title,
      `${friendly.message}\n\nTry: ${friendly.suggestion}` +
        (friendly.detail && friendly.detail !== friendly.message
          ? `\n\nDetail:\n${friendly.detail.slice(0, 500)}`
          : "")
    );
    return { ok: false, error: friendly };
  }
}

ipcMain.handle("pick-and-open", async () => {
  return await ipcOpenImage();
});

ipcMain.handle("get-state", async () => ({
  url: engineUrl,
  session: sessionId,
  engineDir: engineDir(),
  python: pythonBin(),
}));

ipcMain.handle("open-external", async (_e, url) => {
  await shell.openExternal(url);
});

// Optional PTY for embedded terminal (node-pty may fail to build on some hosts)
ipcMain.handle("pty-available", async () => {
  try {
    require("node-pty");
    return true;
  } catch {
    return false;
  }
});

function shellQuote(s) {
  return `'${String(s).replace(/'/g, `'\"'\"'`)}'`;
}

function buildPtyRcFile(shellCtx) {
  const tmp = path.join(os.tmpdir(), `tff-pty-rc-${process.pid}-${Date.now()}.sh`);
  const lines = [
    "# Team Forensic Framework — interactive bash for embedded terminal",
    "export TERM=xterm-256color",
    "export COLORTERM=truecolor",
    // Drop zsh leftovers if Electron inherited them
    "unset PROMPT RPROMPT RPS1 RPS2 2>/dev/null || true",
    "[ -f /etc/bash.bashrc ] && . /etc/bash.bashrc",
    '[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"',
  ];
  if (shellCtx && shellCtx.rc_file && fs.existsSync(shellCtx.rc_file)) {
    lines.push(`. ${shellQuote(shellCtx.rc_file)}`);
  }
  // Always finish with a working bash prompt if none was set / was mangled
  lines.push(`if [[ -z "\${PS1:-}" ]]; then PS1='\\[\\e[32m\\]TFF\\[\\e[0m\\] \\w \\$ '; fi`);
  if (shellCtx && shellCtx.banner) {
    String(shellCtx.banner).split("\n").forEach((ln) => {
      if (ln) lines.push(`echo ${shellQuote(ln)}`);
    });
  } else {
    lines.push("echo 'Team Forensic Framework (TFF) — open an image to bind mounts (tfor-here)'");
  }
  lines.push("echo 'Commands: tfor-here | cdimage | cdexport | cdlast | tfor-parts'");
  lines.push("echo 'Copy/Paste: Ctrl+Shift+C / Ctrl+Shift+V  (right-click also works)'");
  fs.writeFileSync(tmp, `${lines.join("\n")}\n`);
  return tmp;
}

ipcMain.on("pty-start", async (_event, size) => {
  try {
    const pty = require("node-pty");
    killPty();
    // Always bash — Kali default is zsh; sourcing bash PS1 under zsh prints raw \[\\e...\] text
    const shellBin = fs.existsSync("/bin/bash") ? "/bin/bash" : (process.env.SHELL || "bash");
    const scriptsDir = isDev
      ? path.join(repoRoot(), "scripts")
      : path.join(process.resourcesPath, "scripts");
    const wrapper = isDev
      ? path.join(scriptsDir, "tforensic")
      : path.join(process.resourcesPath, "tforensic-wrapper.sh");

    let shellCtx = null;
    if (engineUrl) {
      try {
        const res = await fetch(`${engineUrl.replace(/\/$/, "")}/api/shell/context`);
        if (res.ok) shellCtx = await res.json();
      } catch (_) {}
    }
    if (!shellCtx && sessionId) {
      const sessRoot = path.join(os.tmpdir(), "tforensic-sessions", sessionId);
      const ctxFile = path.join(sessRoot, "shell", "context.json");
      if (fs.existsSync(ctxFile)) {
        try { shellCtx = JSON.parse(fs.readFileSync(ctxFile, "utf8")); } catch (_) {}
      }
      if (shellCtx && !shellCtx.rc_file) {
        const envSh = path.join(sessRoot, "shell", "env.sh");
        if (fs.existsSync(envSh)) shellCtx.rc_file = envSh;
      }
    }

    const env = {
      ...process.env,
      SHELL: shellBin,
      TERM: "xterm-256color",
      COLORTERM: "truecolor",
      PYTHONPATH: engineDir() + (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : ""),
      TFOR_SESSION: sessionId || "",
      PATH: process.env.PATH,
    };
    delete env.ZDOTDIR;
    delete env.PROMPT;
    delete env.RPROMPT;

    if (fs.existsSync(scriptsDir)) {
      env.PATH = scriptsDir + path.delimiter + env.PATH;
    }
    if (fs.existsSync(wrapper)) {
      env.PATH = path.dirname(wrapper) + path.delimiter + env.PATH;
    }
    if (shellCtx && shellCtx.env) {
      Object.assign(env, shellCtx.env);
    }

    let cwd = os.homedir();
    if (shellCtx && shellCtx.cwd && fs.existsSync(shellCtx.cwd)) {
      cwd = shellCtx.cwd;
    } else if (shellCtx && shellCtx.image_dir && fs.existsSync(shellCtx.image_dir)) {
      cwd = shellCtx.image_dir;
    } else if (shellCtx && shellCtx.shell_dir && fs.existsSync(shellCtx.shell_dir)) {
      cwd = shellCtx.shell_dir;
    } else if (sessionId) {
      const sess = path.join(os.tmpdir(), "tforensic-sessions", sessionId);
      const shellDir = path.join(sess, "shell");
      if (fs.existsSync(shellDir)) cwd = shellDir;
      else if (fs.existsSync(sess)) cwd = sess;
    }

    const cols = Math.max(20, (size && size.cols) || 80);
    const rows = Math.max(5, (size && size.rows) || 24);

    const rcPath = buildPtyRcFile(shellCtx);
    const spawned = pty.spawn(shellBin, ["--rcfile", rcPath, "-i"], {
      name: "xterm-256color",
      cols,
      rows,
      cwd,
      env,
    });
    ptyProcess = spawned;
    spawned.onData((data) => {
      if (ptyProcess !== spawned) return;
      sendToRenderer("pty-data", data);
    });
    spawned.onExit(() => {
      if (ptyProcess === spawned) ptyProcess = null;
      sendToRenderer("pty-exit");
      try { fs.unlinkSync(rcPath); } catch (_) {}
    });
  } catch (err) {
    sendToRenderer("pty-data", `\r\n[terminal unavailable: ${err.message}]\r\n`);
  }
});

ipcMain.on("pty-input", (_e, data) => {
  if (ptyProcess) {
    try { ptyProcess.write(data); } catch (_) {}
  }
});

ipcMain.on("pty-resize", (_e, { cols, rows }) => {
  if (ptyProcess) {
    try { ptyProcess.resize(cols, rows); } catch (_) {}
  }
});

/** Re-source session env into a live PTY (tree/mounts ↔ terminal). */
ipcMain.handle("pty-resync", async (_event, opts) => {
  if (!ptyProcess) {
    sendToRenderer("pty-data", "\r\n\x1b[33m[no active terminal — open Terminal first]\x1b[0m\r\n");
    return { ok: false, error: "no-pty" };
  }
  const skipCd = !!(opts && opts.skipCd);
  try {
    let shellCtx = null;
    if (engineUrl) {
      try {
        const res = await fetch(`${engineUrl.replace(/\/$/, "")}/api/shell/context`);
        if (res.ok) shellCtx = await res.json();
      } catch (_) {}
    }
    if (!shellCtx && sessionId) {
      const sessRoot = path.join(os.tmpdir(), "tforensic-sessions", sessionId);
      const ctxFile = path.join(sessRoot, "shell", "context.json");
      if (fs.existsSync(ctxFile)) {
        try { shellCtx = JSON.parse(fs.readFileSync(ctxFile, "utf8")); } catch (_) {}
      }
      if (shellCtx && !shellCtx.rc_file) {
        const envSh = path.join(sessRoot, "shell", "env.sh");
        if (fs.existsSync(envSh)) shellCtx.rc_file = envSh;
      }
    }
    const rc = shellCtx && shellCtx.rc_file;
    if (!rc || !fs.existsSync(rc)) {
      sendToRenderer("pty-data", "\r\n\x1b[33m[no shell context yet — open an image first]\x1b[0m\r\n");
      return { ok: false, error: "no-context" };
    }
    if (shellCtx.env) {
      for (const [k, v] of Object.entries(shellCtx.env)) {
        if (typeof v === "string") {
          try { ptyProcess.write(`export ${k}=${shellQuote(v)}\n`); } catch (_) { return { ok: false }; }
        }
      }
    }
    try {
      ptyProcess.write(`. ${shellQuote(rc)}\n`);
      ptyProcess.write("echo \"[TFF] shell synced with current case\"\n");
      // skipCd: Sync will cd to the selected tree file next
      if (!skipCd) {
        if (shellCtx.cwd && fs.existsSync(shellCtx.cwd)) {
          ptyProcess.write(`cd ${shellQuote(shellCtx.cwd)}\n`);
        } else if (shellCtx.image_dir && fs.existsSync(shellCtx.image_dir)) {
          ptyProcess.write(`cd ${shellQuote(shellCtx.image_dir)}\n`);
        } else if (shellCtx.shell_dir && fs.existsSync(shellCtx.shell_dir)) {
          ptyProcess.write(`cd ${shellQuote(shellCtx.shell_dir)}\n`);
        }
      }
    } catch (_) {}
    return { ok: true };
  } catch (err) {
    sendToRenderer("pty-data", `\r\n[resync failed: ${err.message}]\r\n`);
    return { ok: false, error: String(err.message || err) };
  }
});

// Keep legacy send() callers working
ipcMain.on("pty-resync", () => {
  // no-op — use invoke; left for compatibility
});

ipcMain.on("pty-cd", (_e, payload) => {
  if (!ptyProcess) return;
  try {
    const dir = payload && payload.dir;
    const file = payload && payload.file;
    const name = payload && payload.name;
    if (dir && fs.existsSync(dir)) {
      ptyProcess.write(`cd ${shellQuote(dir)}\n`);
    }
    if (file) {
      ptyProcess.write(`export TFOR_FILE=${shellQuote(file)}\n`);
      ptyProcess.write(`export TFOR_LAST_EXPORT=${shellQuote(file)}\n`);
      ptyProcess.write(
        `echo ${shellQuote(`[TFF] selected file ready → ${name || file}`)}\n`
      );
      ptyProcess.write(`echo ${shellQuote(`  path: ${file}`)}\n`);
      ptyProcess.write(
        `echo ${shellQuote("  try:  exiftool \"$TFOR_FILE\"   |   ls -la \"$TFOR_FILE\"")}\n`
      );
      ptyProcess.write(`ls -la ${shellQuote(file)}\n`);
    } else if (dir) {
      ptyProcess.write(`pwd; ls -la\n`);
    }
  } catch (_) {}
});

ipcMain.on("pty-kill", () => {
  killPty();
});

app.whenReady().then(async () => {
  buildMenu();
  createWindow();
  const argImage = process.argv.find((a) => {
    const lower = a.toLowerCase();
    return /\.(ad1|e01|ex01|ewf|s01|dd|raw|img|bin|aff|vdi|qcow2?|vmdk|vhd|vhdx|ova)$/i.test(lower);
  });
  if (argImage && fs.existsSync(argImage)) {
    await ipcOpenImage(argImage);
  }
});

app.on("window-all-closed", () => {
  stopEngine();
  killPty();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  stopEngine();
  killPty();
});
