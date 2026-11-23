// The API brain form's model field across provider changes: a provider's automatic default
// is replaced by the next provider's default, while a model the owner typed stays theirs.
import { test } from "node:test";
import assert from "node:assert/strict";
import { nextModelValue } from "../ui/api_model.js";

test("an empty field takes the provider's default", () => {
  assert.equal(nextModelValue("", "", "auto"), "auto");
});

test("the previous automatic value is replaced by the new provider's default", () => {
  // The reported bug: OmniRoute filled "auto", then switching provider left "auto" in the field.
  assert.equal(nextModelValue("auto", "auto", "gpt-4o"), "gpt-4o");
});

test("a model the owner typed is kept when the provider changes", () => {
  assert.equal(nextModelValue("llama-x", "auto", "gpt-4o"), "llama-x");
});

test("a provider with no default clears the previous automatic value", () => {
  assert.equal(nextModelValue("auto", "auto", ""), "");
  assert.equal(nextModelValue("auto", "auto", undefined), "");
});

test("a field the owner cleared by hand stays empty", () => {
  assert.equal(nextModelValue("", "auto", "gpt-4o"), "");
});

test("an empty field with a provider that has no default stays empty", () => {
  assert.equal(nextModelValue("", "", ""), "");
});

test("a manual value that happens to equal the new default is unchanged", () => {
  assert.equal(nextModelValue("gpt-4o", "auto", "gpt-4o"), "gpt-4o");
});
