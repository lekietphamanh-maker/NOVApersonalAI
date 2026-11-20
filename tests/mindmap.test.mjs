// The brainstorm map's tree: outline in and out, paths for saved positions, moving and deleting ideas.
import { test } from "node:test";
import assert from "node:assert/strict";
import { LIMITS, contains, moveNode, parentOf, parseOutline, pathsOf, removeNode, serialize, typedIdeas } from "../ui/mindmap.js";

const labels = (list) => list.map((node) => node.label);

test("ideas, sub-ideas by '>' and by indentation, with their editor lines", () => {
  const roots = parseOutline("Gameplay\n  Combat\n  - Stealth\nStory > Endings\n\n1. Art\nStory > Choices");
  assert.deepEqual(labels(roots), ["Gameplay", "Story", "Art"]);
  assert.deepEqual(labels(roots[0].children), ["Combat", "Stealth"]);
  assert.deepEqual(roots[1].children.map((child) => [child.label, child.line]), [["Endings", 3], ["Choices", 6]]);
  assert.equal(roots[2].line, 5);
});

test("deeper levels, and a chain like A > B > C", () => {
  const roots = parseOutline("World\n  Cities\n    Hanoi\n      Old Quarter\nGame > Systems > Combat");
  assert.deepEqual(labels(roots[0].children[0].children[0].children), ["Old Quarter"]);
  assert.deepEqual(labels(roots[1].children[0].children), ["Combat"]);
  assert.equal(serialize(roots), "World\n  Cities\n    Hanoi\n      Old Quarter\nGame\n  Systems\n    Combat");
  assert.deepEqual(parseOutline(serialize(roots)).map((root) => root.label), ["World", "Game"]); // round trip
});

test("limits keep the map readable", () => {
  assert.equal(parseOutline(Array.from({ length: 40 }, (_, i) => `Idea ${i}`).join("\n")).length, LIMITS.roots);
  assert.equal(parseOutline("Hub\n" + Array.from({ length: 20 }, (_, i) => `  Sub ${i}`).join("\n"))[0].children.length, LIMITS.children);
  const deep = parseOutline("a\n  b\n    c\n      d\n        e");
  assert.deepEqual(labels(deep[0].children[0].children[0].children), ["d"]);
  assert.deepEqual(deep[0].children[0].children[0].children[0].children, []); // a fifth level is dropped
});

test("paths name every idea, even repeated names", () => {
  const roots = parseOutline("Art\n  Ideas\nCode\n  Ideas\n  Ideas");
  assert.deepEqual([...pathsOf(roots).values()], ["art", "art > ideas", "code", "code > ideas", "code > ideas #2"]);
});

test("moving an idea under another, to the top, never into itself; deleting with its sub-ideas", () => {
  const roots = parseOutline("A\n  A1\nB");
  const [a, b] = roots, a1 = a.children[0];
  assert.equal(moveNode(roots, b, a1), true);
  assert.equal(serialize(roots), "A\n  A1\n    B");
  assert.equal(moveNode(roots, a, b), false); // A contains B
  assert.ok(contains(a, b));
  moveNode(roots, a1, null);
  assert.equal(serialize(roots), "A\nA1\n  B");
  assert.equal(parentOf(roots, b).parent, a1);
  removeNode(roots, a1);
  assert.equal(serialize(roots), "A");
});

test("typed or pasted ideas: lines, semicolons, bullets and A > B paths", () => {
  assert.deepEqual(typedIdeas("Combat; Stealth\n- Story > Endings\n\n  2. Art  "),
    [["Combat"], ["Stealth"], ["Story", "Endings"], ["Art"]]);
  assert.deepEqual(typedIdeas("  ;  \n"), []);
});
