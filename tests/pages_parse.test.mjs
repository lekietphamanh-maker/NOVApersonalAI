// Run: node --test tests/pages_parse.test.mjs. Every page script must parse as a module: one bad quote in a
// string stops the whole HUD from loading, and `node --check file.js` doesn't catch it for these files.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import test from "node:test";

for (const file of ["ui/app.js", "ui/core.js", "ui/mindmap.js", "ui/world.js", "ui/workplace.js", "ui/build.js", "creative/creative.js", "creative/lenses.js", "creative/gestures.js"]) {
  test(`${file} parses`, () => {
    const result = spawnSync(process.execPath, ["--input-type=module", "--check"], { input: readFileSync(file) });
    assert.equal(result.status, 0, String(result.stderr));
  });
}

// The phone, TV, deck and setup pages keep their scripts inline: classic ones, and modules that load the HUD's core.
for (const file of ["phone/index.html", "phone/tv.html", "phone/deck.html", "phone/setup.html"]) {
  test(`${file} scripts parse`, () => {
    const scripts = [...readFileSync(file, "utf8").matchAll(/<script( type="module")?>([\s\S]*?)<\/script>/g)];
    assert.ok(scripts.length > 0, "no inline script found");
    for (const [, module, script] of scripts) {
      const result = spawnSync(process.execPath, [`--input-type=${module ? "module" : "commonjs"}`, "--check"], { input: script });
      assert.equal(result.status, 0, String(result.stderr));
    }
  });
}

// The circuit bench (ui/circuit/, the owner's Robotics Lab workbench) in the Workplace. The HUD's CSP has no inline scripts,
// so no import map: every import is a relative path to a file that exists, three.js included.
function sourceFiles(folder) {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? sourceFiles(join(folder, entry.name)) : entry.name.endsWith(".js") ? [join(folder, entry.name)] : []);
}
const IMPORT = /(?:\bimport\s+(?:[^'"()`]*?\sfrom\s+)?|\bexport\s+[^'"()`]*?\sfrom\s+|\bimport\()\s*(['"])([^'"`]+)\1/g;
for (const file of sourceFiles("ui/circuit")) {
  const name = relative("ui/circuit", file).replaceAll("\\", "/");
  test(`circuit/${name} parses and imports only files that exist`, () => {
    const source = readFileSync(file, "utf8");
    const result = spawnSync(process.execPath, ["--input-type=module", "--check"], { input: source });
    assert.equal(result.status, 0, String(result.stderr));
    for (const [, , specifier] of source.matchAll(IMPORT)) {
      assert.ok(specifier.startsWith("."), `${name} imports "${specifier}": a bare name needs an import map, which the HUD's CSP forbids`);
      assert.ok(existsSync(join(dirname(file), specifier)), `${name} imports ${specifier}, which isn't there`);
    }
  });
}

test("every part module the bench loads by name is there", () => {
  const lab = readFileSync("ui/circuit/lab/lab.js", "utf8");
  const ids = [...lab.match(/const MODULE_IDS = \[([^\]]+)\]/)[1].matchAll(/'([a-z0-9-]+)'/g)].map((match) => match[1]);
  assert.ok(ids.length >= 14);
  for (const id of ids) assert.ok(existsSync(`ui/circuit/lab/modules/${id}.js`), `lab/modules/${id}.js is missing`);
});

// A named import its module doesn't export stops the whole page at load, and `--check` can't see it: creative mode was
// dead for days from `import { VOICES } from "./handmusic.js"` (VOICES lives in handmusic-audio.js). So every import of
// every HUD and creative module must name something its target exports. Creative's page has an import map for three.js.
const CREATIVE_IMPORTS = JSON.parse(readFileSync("creative/index.html", "utf8").match(/<script type="importmap">([\s\S]*?)<\/script>/)[1]).imports;
const STATIC_IMPORT = /\bimport\s+([^'"`;]*?)\s*from\s*(['"])([^'"`]+)\2/g;
const DYNAMIC_IMPORT = /\bimport\(\s*(['"])([^'"`]+)\1\s*\)/g;

function resolveImport(file, specifier) {
  if (specifier.startsWith(".")) return join(dirname(file), specifier);
  if (!file.startsWith("creative")) return null; // the HUD's CSP rules out an import map: bare names can't load there
  const prefix = Object.keys(CREATIVE_IMPORTS).find((key) => key.endsWith("/") ? specifier.startsWith(key) : specifier === key);
  return prefix && join("creative", CREATIVE_IMPORTS[prefix] + specifier.slice(prefix.length));
}

const exportCache = new Map();
function exportsOf(file) {
  if (exportCache.has(file)) return exportCache.get(file);
  const source = readFileSync(file, "utf8"), names = new Set();
  exportCache.set(file, names);
  for (const [, list] of source.matchAll(/\bexport\s*\{([^}]*)\}/g)) {
    for (const item of list.split(",")) { const name = item.trim().split(/\s+as\s+/).pop(); if (name) names.add(name); }
  }
  for (const [, name] of source.matchAll(/\bexport\s+(?:default\s+)?(?:async\s+)?(?:function\s*\*?|class|const|let|var)\s*([\w$]+)/g)) names.add(name);
  if (/\bexport\s+default\b/.test(source)) names.add("default");
  for (const [, name] of source.matchAll(/\bexport\s*\*\s*as\s+([\w$]+)/g)) names.add(name);
  for (const [, , specifier] of source.matchAll(/\bexport\s*\*\s*from\s*(['"])([^'"`]+)\1/g)) {
    for (const name of exportsOf(resolveImport(file, specifier))) if (name !== "default") names.add(name);
  }
  return names;
}

function importedNames(clause) {
  const named = clause.match(/\{([^}]*)\}/)?.[1].split(",").map((item) => item.trim().split(/\s+as\s+/)[0]).filter(Boolean) ?? [];
  return /^[\w$]/.test(clause.trim()) ? [...named, "default"] : named;
}

const pageModules = [...sourceFiles("ui"), ...sourceFiles("creative"), ...readdirSync("creative").filter((name) => name.endsWith(".mjs")).map((name) => join("creative", name))]
  .filter((file) => !file.split(/[\\/]/).includes("vendor"));
test("every HUD and creative import names something its module exports", () => {
  assert.ok(pageModules.length > 30, `only ${pageModules.length} modules found`);
  const problems = [];
  for (const file of pageModules) {
    const source = readFileSync(file, "utf8");
    for (const [, , specifier] of source.matchAll(DYNAMIC_IMPORT)) {
      const target = resolveImport(file, specifier);
      if (!target || !existsSync(target)) problems.push(`${file}: import("${specifier}") has no file`);
    }
    for (const [, clause, , specifier] of source.matchAll(STATIC_IMPORT)) {
      const target = resolveImport(file, specifier);
      if (!target || !existsSync(target)) { problems.push(`${file}: "${specifier}" has no file`); continue; }
      const available = exportsOf(target);
      for (const name of importedNames(clause)) if (!available.has(name)) problems.push(`${file}: ${specifier} doesn't export ${name}`);
    }
  }
  assert.deepEqual(problems, []);
});
