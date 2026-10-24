import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
if (existsSync(path.join(root, '.env'))) process.loadEnvFile(path.join(root, '.env'));
const windows = process.platform === 'win32';
const venvPython = path.join(root, '.venv', windows ? 'Scripts/python.exe' : 'bin/python');
const python = process.env.FDR_PYTHON || (existsSync(venvPython) ? venvPython : (windows ? 'python' : 'python3'));
const vite = path.join(root, 'frontend/node_modules/vite/bin/vite.js');
if (!existsSync(vite)) {
  console.error('Frontend dependencies are missing. Run: npm --prefix frontend ci');
  process.exit(1);
}
const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) child.kill('SIGTERM');
  process.exitCode = code;
}
function run(command, args, cwd) {
  const child = spawn(command, args, { cwd, env: process.env, stdio: 'inherit', windowsHide: true });
  children.push(child);
  child.on('error', error => { console.error(error.message); stop(1); });
  child.on('exit', code => { if (!stopping) stop(code ?? 1); });
}
run(python, ['-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', process.env.BACKEND_PORT || '8001'], root);
run(process.execPath, [vite, '--host', '127.0.0.1', '--port', '5173', '--strictPort'], path.join(root, 'frontend'));
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
