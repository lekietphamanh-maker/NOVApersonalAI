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
