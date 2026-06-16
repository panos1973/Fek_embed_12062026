"use strict";
// Static contract check between the Electron shell and the Python core.
// No GUI needed — verifies IPC channels, the exposed api surface, the CLI
// subcommands the shell spawns, and the restored-layout paths.
//   node lawgic_electron/test_contract.js
const fs = require("fs");
const path = require("path");

const here = __dirname;
const rd = (p) => fs.readFileSync(p, "utf8");
const all = (s, re) => [...s.matchAll(re)].map((m) => m[1]);

const main = rd(path.join(here, "main.js"));
const preload = rd(path.join(here, "preload.js"));
const renderer = rd(path.join(here, "renderer", "renderer.js"));
const cli = rd(path.join(here, "..", "lawgic_pipeline", "cli.py"));

const mainHandlers = new Set(all(main, /ipcMain\.(?:handle|on)\(\s*['"]([^'"]+)['"]/g));
const mainSends = new Set(all(main, /webContents\.send\(\s*['"]([^'"]+)['"]/g));
const preInvoke = all(preload, /ipcRenderer\.(?:invoke|send)\(\s*['"]([^'"]+)['"]/g);
const preOn = all(preload, /ipcRenderer\.on\(\s*['"]([^'"]+)['"]/g);
const preApi = new Set(all(preload, /(\w+):\s*\([^)]*\)\s*=>/g));
const rendApi = new Set(all(renderer, /window\.api\.(\w+)/g));
const cliCmds = new Set(all(cli, /add_parser\(['"]([^'"]+)['"]\)/g));

let fails = 0;
const check = (cond, msg) => {
  console.log(`  ${cond ? "ok  " : "FAIL"} ${msg}`);
  if (!cond) fails++;
};

console.log("electron <-> core contract:");
for (const c of preInvoke) check(mainHandlers.has(c), `renderer invoke '${c}' handled in main`);
for (const c of preOn) check(mainSends.has(c), `renderer listens '${c}' which main sends`);
for (const m of rendApi) check(preApi.has(m), `renderer uses api.${m} exposed by preload`);
for (const cmd of ["ingest", "status", "review", "retry"])
  check(cliCmds.has(cmd), `cli.py defines subcommand '${cmd}'`);
check(/['"]--json['"]/.test(main) && /cli\.py/.test(main), "main spawns cli.py with --json");
check(/path\.join\(__dirname,\s*'\.\.',\s*'lawgic_pipeline'\)/.test(main),
  "coreDir default -> ../lawgic_pipeline (sibling layout)");
check(/renderer',\s*'index\.html'/.test(main), "loads renderer/index.html");

console.log(fails ? `\nFAILED (${fails})` : "\nALL CONTRACT CHECKS PASSED");
process.exit(fails ? 1 : 0);
