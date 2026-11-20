// Run: node --test tests/pages_parse.test.mjs. Every page script must parse as a module: one bad quote in a
// string stops the whole HUD from loading, and `node --check file.js` doesn't catch it for these files.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";

for (const file of ["ui/app.js", "ui/core.js", "ui/mindmap.js", "ui/world.js", "creative/creative.js", "creative/lenses.js", "creative/gestures.js"]) {
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
