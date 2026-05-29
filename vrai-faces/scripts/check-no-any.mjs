#!/usr/bin/env node
// CI guardrail per VRAI_Faces_Claude_Code_Guide.md §4.1:
// fail if a new `any` type / `@ts-ignore` / `eslint-disable` appears in src/.
//
// The `any` check must match the TypeScript *keyword* (`: any`, `as any`,
// `any[]`, `Promise<any>`, `x | any`, …), NOT the English word "any" that
// shows up in prose comments ("if any.", "avoid `any`", "from any module").
// So before testing for the keyword we blank out comments and string/template
// literals — what remains is code, where a bare `any` token is the type.
// Block comments and unterminated template literals carry state across lines.
//
// `@ts-ignore` / `eslint-disable` are comment directives, so those two are
// matched against the raw line (they live inside comments on purpose).
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const rootArg = process.argv[2] ?? 'src';
const root = resolve(rootArg);

const SKIP_DIR = new Set(['node_modules', 'dist', 'coverage', '.vite']);

/**
 * Return the line with comments and string/template literal *contents*
 * removed, so a regex can scan real code. `state` carries multi-line block
 * comment / template literal status between consecutive lines of a file.
 */
function stripCommentsAndStrings(line, state) {
  let out = '';
  let i = 0;
  const n = line.length;
  while (i < n) {
    const c = line[i];
    const c2 = line[i + 1];

    if (state.inBlock) {
      if (c === '*' && c2 === '/') { state.inBlock = false; i += 2; }
      else { i += 1; }
      continue;
    }
    if (state.inTemplate) {
      if (c === '\\') { i += 2; continue; }
      if (c === '`') { state.inTemplate = false; i += 1; continue; }
      i += 1;
      continue;
    }

    if (c === '/' && c2 === '/') break;            // line comment: drop rest
    if (c === '/' && c2 === '*') { state.inBlock = true; i += 2; continue; }

    if (c === '"' || c === "'") {                  // single-line string
      const q = c; i += 1;
      while (i < n) {
        if (line[i] === '\\') { i += 2; continue; }
        if (line[i] === q) { i += 1; break; }
        i += 1;
      }
      continue;
    }
    if (c === '`') {                               // template literal
      i += 1;
      let closed = false;
      while (i < n) {
        if (line[i] === '\\') { i += 2; continue; }
        if (line[i] === '`') { i += 1; closed = true; break; }
        i += 1;
      }
      if (!closed) state.inTemplate = true;
      continue;
    }

    out += c;
    i += 1;
  }
  return out;
}

function walk(dir) {
  for (const name of readdirSync(dir)) {
    if (SKIP_DIR.has(name)) continue;
    const p = join(dir, name);
    const s = statSync(p);
    if (s.isDirectory()) walk(p);
    else if (/\.(ts|tsx)$/.test(name)) check(p);
  }
}

let bad = 0;
function check(path) {
  const lines = readFileSync(path, 'utf8').split('\n');
  const state = { inBlock: false, inTemplate: false };
  lines.forEach((line, i) => {
    // Always advance scanner state, even on opted-out lines.
    const code = stripCommentsAndStrings(line, state);
    if (line.includes('// vrai-allow:')) return;   // explicit per-line opt-out

    if (/\bany\b/.test(code)) {
      console.error(`${path}:${i + 1}  forbidden token: any`);
      bad++;
    }
    if (/@ts-ignore/.test(line)) {
      console.error(`${path}:${i + 1}  forbidden token: @ts-ignore`);
      bad++;
    }
    if (/eslint-disable/.test(line)) {
      console.error(`${path}:${i + 1}  forbidden token: eslint-disable`);
      bad++;
    }
  });
}

walk(root);
if (bad > 0) {
  console.error(`\nFAIL: ${bad} forbidden token(s) in ${root}.`);
  console.error('Add an inline justification + `// vrai-allow: <reason>` to suppress.');
  process.exit(1);
} else {
  console.log(`OK: no forbidden tokens in ${root}.`);
}
