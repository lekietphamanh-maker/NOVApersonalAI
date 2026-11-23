// The full report, read on screen: Markdown-lite shaping, escaped so no report text ever
// reaches the page as HTML. Pure logic, no DOM.
import { test } from "node:test";
import assert from "node:assert/strict";
import { reportToHtml, escapeHtml } from "../ui/lab.js";

test("reportToHtml escapes everything and restores only the report's own structure", () => {
  const html = reportToHtml("# Title\n\n<script>alert(1)</script>\n\n- one\n- two\n\n1. first\n2. second\n\nPlain text.");
  assert.match(html, /<h2>Title<\/h2>/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /<ul>\n<li>one<\/li>\n<li>two<\/li>\n<\/ul>/);
  assert.match(html, /<ol>\n<li>first<\/li>\n<li>second<\/li>\n<\/ol>/);
  assert.match(html, /<p>Plain text\.<\/p>/);
});

test("reportToHtml keeps code blocks intact and closed", () => {
  const html = reportToHtml("Before\n\n```python\nx = 1 < 2\n```\n\nAfter");
  assert.match(html, /<pre><code>x = 1 &lt; 2<\/code><\/pre>/);
  assert.match(html, /<p>Before<\/p>/);
  assert.match(html, /<p>After<\/p>/);
  const unclosed = reportToHtml("```\nnever closed");
  assert.match(unclosed, /<\/code><\/pre>$/);
});

test("escapeHtml covers quotes too", () => {
  assert.equal(escapeHtml(`a "b" & 'c' <d>`), "a &quot;b&quot; &amp; &#39;c&#39; &lt;d&gt;");
  assert.equal(reportToHtml(""), "");
});
