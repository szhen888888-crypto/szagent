#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const configDir = path.join(root, 'config');
const rolesDir = path.join(configDir, 'roles');
const generatedDir = path.join(configDir, 'generated');

function loadEnv(file) {
  if (!fs.existsSync(file)) return {};
  const env = {};
  for (const rawLine of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).trim();
    env[key] = value;
  }
  return env;
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function mergeDeep(base, override) {
  if (Array.isArray(base) || Array.isArray(override)) return override ?? base;
  if (!isObject(base) || !isObject(override)) return override === undefined ? base : override;
  const out = { ...base };
  for (const [key, value] of Object.entries(override)) {
    if (key === 'role' || key === 'roleTitle') continue;
    out[key] = mergeDeep(out[key], value);
  }
  return out;
}

function isObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value);
}

function expandPlaceholders(value, vars) {
  if (typeof value === 'string') {
    return value.replace(/\$\{([A-Z0-9_]+)\}/g, (_, name) => vars[name] ?? '${' + name + '}');
  }
  if (Array.isArray(value)) return value.map(item => expandPlaceholders(item, vars));
  if (isObject(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, expandPlaceholders(item, vars)]),
    );
  }
  return value;
}

const base = readJson(path.join(configDir, 'base.nanobot.json'));
const env = { ...loadEnv(path.join(root, '.env')), ...process.env };
fs.mkdirSync(generatedDir, { recursive: true });

for (const name of fs.readdirSync(rolesDir).filter(file => file.endsWith('.json')).sort()) {
  const roleConfig = readJson(path.join(rolesDir, name));
  const role = roleConfig.role || path.basename(name, '.json');
  const roleTitle = roleConfig.roleTitle || role;
  const merged = mergeDeep(base, roleConfig);
  const expanded = expandPlaceholders(merged, {
    ...env,
    SZAGENT_ROOT: root,
    ROLE: role,
    ROLE_TITLE: roleTitle,
  });
  const out = path.join(generatedDir, `${role}.config.json`);
  fs.writeFileSync(out, JSON.stringify(expanded, null, 2) + '\n');
  console.log(`generated ${path.relative(root, out)}`);
}
