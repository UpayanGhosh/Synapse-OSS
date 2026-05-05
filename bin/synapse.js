#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { spawn, spawnSync } = require("child_process");

const COMMANDS = new Set(["install", "onboard", "reset", "start", "stop", "doctor", "chat"]);
const PYTHON_VERSION = process.env.SYNAPSE_PYTHON_VERSION || "3.12";
const UV_INSTALL_SH = "https://astral.sh/uv/install.sh";
const UV_INSTALL_PS1 = "https://astral.sh/uv/install.ps1";

function productHome() {
  if (process.env.SYNAPSE_HOME) {
    return path.resolve(process.env.SYNAPSE_HOME);
  }
  const baseHome = process.platform === "win32" ? process.env.USERPROFILE : process.env.HOME;
  if (!baseHome) {
    throw new Error("Cannot resolve home directory. Set SYNAPSE_HOME.");
  }
  return path.join(baseHome, ".synapse");
}

function packageRoot() {
  return path.resolve(__dirname, "..");
}

function venvBin(home) {
  return path.join(home, ".venv", process.platform === "win32" ? "Scripts" : "bin");
}

function pythonPath(home) {
  return path.join(venvBin(home), process.platform === "win32" ? "python.exe" : "python");
}

function synapsePath(home) {
  return path.join(venvBin(home), process.platform === "win32" ? "synapse.exe" : "synapse");
}

function uvPath(home) {
  return path.join(home, "runtime", "uv", process.platform === "win32" ? "uv.exe" : "uv");
}

function npmPath() {
  return process.platform === "win32" ? "npm.cmd" : "npm";
}

function ensureDirs(home) {
  for (const rel of [
    "runtime",
    "runtime/tmp",
    "runtime/uv",
    "runtime/uv-cache",
    "runtime/uv-tools",
    "runtime/uv-tool-bin",
    "runtime/pythons",
    "runtime/python-bin",
    "runtime/python-cache",
    "runtime/playwright",
    "logs",
    "state",
  ]) {
    fs.mkdirSync(path.join(home, rel), { recursive: true });
  }
}

function runtimeEnv(home) {
  const runtimeTmp = path.join(home, "runtime", "tmp");
  return {
    ...process.env,
    SYNAPSE_HOME: home,
    PLAYWRIGHT_BROWSERS_PATH: path.join(home, "runtime", "playwright"),
    TEMP: runtimeTmp,
    TMP: runtimeTmp,
    TMPDIR: runtimeTmp,
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8",
  };
}

function installEnv(home) {
  return {
    ...runtimeEnv(home),
    UV_INSTALL_DIR: path.join(home, "runtime", "uv"),
    UV_NO_MODIFY_PATH: "1",
    UV_CACHE_DIR: path.join(home, "runtime", "uv-cache"),
    UV_PYTHON_INSTALL_DIR: path.join(home, "runtime", "pythons"),
    UV_PYTHON_BIN_DIR: path.join(home, "runtime", "python-bin"),
    UV_PYTHON_CACHE_DIR: path.join(home, "runtime", "python-cache"),
    UV_TOOL_DIR: path.join(home, "runtime", "uv-tools"),
    UV_TOOL_BIN_DIR: path.join(home, "runtime", "uv-tool-bin"),
    UV_PROJECT_ENVIRONMENT: path.join(home, ".venv"),
  };
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    env: options.env || process.env,
    cwd: options.cwd,
    shell: false,
  });
  if (result.error) {
    console.error(result.error.message);
    return 1;
  }
  return result.status === null ? 1 : result.status;
}

function runRequired(command, args, options = {}) {
  const code = run(command, args, options);
  if (code !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed with exit code ${code}`);
  }
}

function runNpm(args, options = {}) {
  if (process.platform !== "win32") {
    return runRequired(npmPath(), args, options);
  }
  const command = process.env.ComSpec || "cmd.exe";
  return runRequired(command, ["/d", "/s", "/c", npmPath(), ...args], options);
}

function installUv(home) {
  const uv = uvPath(home);
  if (fs.existsSync(uv)) {
    return uv;
  }
  const env = installEnv(home);
  if (process.platform === "win32") {
    runRequired("powershell.exe", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-Command",
      `irm ${UV_INSTALL_PS1} | iex`,
    ], { env, cwd: home });
  } else {
    runRequired("sh", ["-c", `curl -LsSf ${UV_INSTALL_SH} | sh`], { env, cwd: home });
  }
  if (!fs.existsSync(uv)) {
    throw new Error(`uv installer completed but ${uv} was not created`);
  }
  return uv;
}

function installPythonRuntime(home, uv) {
  const env = installEnv(home);
  runRequired(uv, [
    "python",
    "install",
    PYTHON_VERSION,
    "--install-dir",
    path.join(home, "runtime", "pythons"),
  ], { env, cwd: home });
  if (!fs.existsSync(pythonPath(home))) {
    const venvPath = path.join(home, ".venv");
    const venvArgs = ["venv", venvPath, "--python", PYTHON_VERSION];
    if (fs.existsSync(venvPath)) {
      venvArgs.push("--clear");
    }
    runRequired(uv, venvArgs, {
      env,
      cwd: home,
    });
  }
  runRequired(uv, ["pip", "install", "--python", pythonPath(home), packageRoot()], {
    env,
    cwd: packageRoot(),
  });
}

function runSynapse(home, args) {
  const synapse = synapsePath(home);
  if (!fs.existsSync(synapse)) {
    throw new Error(`Synapse is not installed at ${home}. Run: synapse install`);
  }
  return run(synapse, args, { env: runtimeEnv(home), cwd: home });
}

function requirePython(home) {
  const python = pythonPath(home);
  if (!fs.existsSync(python)) {
    throw new Error(`Synapse Python runtime missing at ${home}. Run: synapse install`);
  }
  return python;
}

function installBrowser(home) {
  const code = run(pythonPath(home), ["-m", "playwright", "install", "chromium"], {
    env: runtimeEnv(home),
    cwd: home,
  });
  if (code !== 0) {
    console.warn("Playwright browser install failed; web browsing may be degraded.");
  }
}

function installBridge(home) {
  const bridge = path.join(home, "bridges", "baileys");
  if (!fs.existsSync(path.join(bridge, "package.json"))) {
    return;
  }
  runNpm(["install", "--omit=dev"], {
    env: runtimeEnv(home),
    cwd: bridge,
  });
}

function runInstall(home) {
  ensureDirs(home);
  const uv = installUv(home);
  installPythonRuntime(home, uv);
  runRequired(synapsePath(home), ["install-home"], {
    env: runtimeEnv(home),
    cwd: home,
  });
  installBrowser(home);
  installBridge(home);
  console.log(`Synapse installed at ${home}`);
  return 0;
}

function pidFile(home) {
  return path.join(home, "state", "gateway.pid");
}

function logFile(home) {
  return path.join(home, "logs", "gateway.log");
}

function isRunning(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function stopProcessTree(pid) {
  if (!pid || !isRunning(pid)) {
    return;
  }
  if (process.platform === "win32") {
    const result = spawnSync("taskkill", ["/T", "/PID", String(pid)], {
      stdio: "ignore",
      shell: false,
    });
    if (result.status !== 0 && isRunning(pid)) {
      spawnSync("taskkill", ["/F", "/T", "/PID", String(pid)], {
        stdio: "ignore",
        shell: false,
      });
    }
    return;
  }
  process.kill(pid);
}

function runStart(home) {
  const python = requirePython(home);
  const pidPath = pidFile(home);
  if (fs.existsSync(pidPath)) {
    const pid = Number(fs.readFileSync(pidPath, "utf8").trim());
    if (pid && isRunning(pid)) {
      console.log(`Synapse gateway already running (pid ${pid}).`);
      return 0;
    }
  }
  fs.mkdirSync(path.dirname(logFile(home)), { recursive: true });
  fs.mkdirSync(path.dirname(pidPath), { recursive: true });
  const out = fs.openSync(logFile(home), "a");
  const host = process.env.SYNAPSE_GATEWAY_HOST || "127.0.0.1";
  const port = process.env.SYNAPSE_GATEWAY_PORT || "8000";
  const child = spawn(python, [
    "-X",
    "utf8",
    "-m",
    "uvicorn",
    "sci_fi_dashboard.api_gateway:app",
    "--host",
    host,
    "--port",
    port,
    "--workers",
    "1",
  ], {
    cwd: home,
    detached: true,
    env: runtimeEnv(home),
    stdio: ["ignore", out, out],
  });
  child.unref();
  fs.writeFileSync(pidPath, String(child.pid));
  console.log(`Synapse gateway started (pid ${child.pid}).`);
  return 0;
}

function runStop(home) {
  const pidPath = pidFile(home);
  if (!fs.existsSync(pidPath)) {
    console.log("Synapse gateway is not running.");
    return 0;
  }
  const pid = Number(fs.readFileSync(pidPath, "utf8").trim());
  if (pid && isRunning(pid)) {
    stopProcessTree(pid);
  }
  fs.rmSync(pidPath, { force: true });
  console.log("Synapse gateway stopped.");
  return 0;
}

function utcTimestamp() {
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

function parseResetArgs(args) {
  const opts = {
    scope: "config",
    yes: false,
    reonboard: false,
    flow: "quickstart",
  };
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === "--yes" || arg === "-y") {
      opts.yes = true;
    } else if (arg === "--reonboard") {
      opts.reonboard = true;
    } else if (arg === "--scope" || arg === "-s") {
      i += 1;
      opts.scope = args[i] || "";
    } else if (arg.startsWith("--scope=")) {
      opts.scope = arg.slice("--scope=".length);
    } else if (arg === "--flow") {
      i += 1;
      opts.flow = args[i] || "";
    } else if (arg.startsWith("--flow=")) {
      opts.flow = arg.slice("--flow=".length);
    } else if (arg === "-h" || arg === "--help") {
      opts.help = true;
    } else {
      throw new Error(`Unknown reset option: ${arg}`);
    }
  }
  return opts;
}

function printResetHelp() {
  console.log("Usage: synapse reset [--scope config|config+creds+sessions|full] [--yes] [--reonboard] [--flow quickstart|advanced]");
}

function moveIfExists(src, backupDir) {
  if (!fs.existsSync(src)) {
    return;
  }
  const dest = path.join(backupDir, path.basename(src));
  fs.renameSync(src, dest);
  console.log(`Moved ${src} -> ${dest}`);
}

function runReset(home, args) {
  const opts = parseResetArgs(args);
  if (opts.help) {
    printResetHelp();
    return 0;
  }
  const scopes = new Set(["config", "config+creds+sessions", "full"]);
  if (!scopes.has(opts.scope)) {
    console.error(`Invalid reset scope: ${opts.scope}`);
    printResetHelp();
    return 1;
  }
  if (!opts.yes) {
    console.log(`Synapse home: ${home}`);
    console.log("Reset moves matching files into <synapse-home>/backups/<timestamp>/.");
    console.log("Re-run with --yes to confirm.");
    return 1;
  }

  fs.mkdirSync(home, { recursive: true });
  const backupDir = path.join(home, "backups", utcTimestamp());
  fs.mkdirSync(backupDir, { recursive: true });

  if (opts.scope === "config") {
    moveIfExists(path.join(home, "synapse.json"), backupDir);
  } else if (opts.scope === "config+creds+sessions") {
    moveIfExists(path.join(home, "synapse.json"), backupDir);
    moveIfExists(path.join(home, "credentials"), backupDir);
    moveIfExists(path.join(home, "sessions"), backupDir);
    moveIfExists(path.join(home, "state"), backupDir);
  } else if (opts.scope === "full") {
    for (const child of fs.readdirSync(home)) {
      if (child === "backups") {
        continue;
      }
      moveIfExists(path.join(home, child), backupDir);
    }
  }

  console.log(`Reset complete. Backup at: ${backupDir}`);
  if (opts.reonboard) {
    if (opts.scope === "full" || !fs.existsSync(synapsePath(home))) {
      runInstall(home);
    }
    return runSynapse(home, ["onboard", "--flow", opts.flow]);
  }
  return 0;
}

function printHelp() {
  console.log("Usage: synapse <install|onboard|reset|start|stop|doctor|chat> [args...]");
}

function main(argv) {
  const [command, ...args] = argv;
  if (!command || command === "-h" || command === "--help") {
    printHelp();
    return 0;
  }
  if (!COMMANDS.has(command)) {
    console.error(`Unknown command: ${command}`);
    printHelp();
    return 2;
  }
  const home = productHome();
  try {
    if (command === "install") {
      return runInstall(home);
    }
    if (command === "start") {
      return runStart(home);
    }
    if (command === "stop") {
      return runStop(home);
    }
    if (command === "reset") {
      return runReset(home, args);
    }
    return runSynapse(home, [command, ...args]);
  } catch (error) {
    console.error(error.message);
    return 1;
  }
}

process.exitCode = main(process.argv.slice(2));
