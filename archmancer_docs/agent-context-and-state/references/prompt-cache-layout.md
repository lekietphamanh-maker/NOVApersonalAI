# Prompt cache layout

## Premise and decision

Use this leaf only when a model route can reuse a prefix and repeated requests make reuse potentially valuable. Correct authorized content and task quality take priority over hit rate: a privacy repair, correction, revocation or required policy change must happen even when it invalidates a prefix. Without eligible reuse, omit markers, cache objects and cache-specific state. Cache behavior belongs to the exact model, endpoint, adapter version, request controls and account scope, not merely a provider name.

| Pressure | Minimal choice | Extension and evidence needed |
|---|---|---|
| No repeated prefix or no cache visibility | Normal calls; account for ordinary input. | Do not add caching infrastructure. |
| Automatic reuse is available | Order stable content before volatile content where that preserves authority and semantics. | Measure cold, warm and changed requests on the actual route. |
| An explicit cache is supported | Compare against the best automatic baseline. | Create a scoped resource only if savings after creation, storage, misses and maintenance justify its lifecycle and correctness burden. |
| Rewrites break useful history reuse | Retain stable raw history and perform bounded, necessary rewrites. | Persist a selected edit plan per checkpoint only if the implementation can replay it safely. |

## Effective layout and contract

If eligibility depends on prefix size, count or estimate tokens in the actual candidate prefix after relevant transformations, using the route's counter and recording uncertainty. Character count and total conversation size can misclassify a shorter marked prefix. Test a large suffix with a short candidate and differing token-to-character ratios; the decision follows the candidate tokens, not either proxy.

A typical layout is stable tool declarations and trusted instructions, then replayable history, then the current snapshot and input, followed by transient reminders or steps. This is an example, not a universal provider order: adapters may move system messages, normalize content blocks, filter tool schemas or alter request controls. Compare ordered **provider-effective content and legal boundaries** after all transformations, not object-key order or a whole-body byte-prefix assertion. If a per-run snapshot is inserted before the current user input and history is persisted, replay the stored snapshot with its identity on later turns; if caller-owned history cannot replay it, do not assume cross-turn reuse. A deliberate configuration change creates a legitimate new variant.

Put volatile data in its declared snapshot, correlated result or request-only tail, not in a stable instruction prefix. Protect call/result identity. If marking a prefix while excluding ephemeral messages, define the boundary explicitly and verify that excluded messages really form the suffix; a count alone is unsafe if transient messages are interleaved. Tool availability and schemas must follow authorization and task quality; a fixed declared set is an option, not a reason to expose unauthorized actions. The executor independently authorizes every action.

On a necessary history rewrite, record the transition and replay the resulting projection stably where possible. A frozen edit selection must use stable unique identifiers, preserve tool structure and protect current required state; privacy readmission and new authoritative observations can legitimately change it. Compare final projections including request-only decoration, provider conversion and privacy repair. Do not suppress a correction to preserve cache reuse.

For an explicit cache resource, define model, credential/project scope, visibility, lifetime, key inputs and who can use it. Reconstruct the original request semantically from resource plus generation suffix: no instruction, message, tool or control may be duplicated or lost. Test legal resource boundaries and the selected adapter's behavior when no resource is created. Handle resource lookup, creation and generation as distinct operations with their own accounting and authorized send budgets. A resource may contain sensitive data: scope it, authorize reuse separately, and expire or delete according to the applicable retention policy. An offline equivalence check is a design recommendation, not evidence that an existing adapter implements it.

## Usage, cost and break-even

Normalize counters according to their producer: where prompt total includes ordinary input U, cache reads R and writes W, compute U = total − R − W; where native input excludes cached buckets, total is U + R + W. Preserve absent, invalid and measured zero as distinct states. For streaming, merge deltas or take the final record only when the adapter guarantees cumulative usage; do not sum repeated cumulative totals. An abandoned stream or a deferred client without usage reporting cannot establish zero cache use.

Compute total cost from ordinary input, reads, writes, output and any explicit creation and storage charges, using the route's actual prices and units. Do not count the same token twice or infer free creation from automatic caching. Capture the creation receipt even if generation later fails; unknown generation, storage duration or price remains unknown and may need external reconciliation. Distinguish estimated lifetime from observed lifetime or invoice.

For a simple explicit resource, let p be the ordinary cost of its reusable prefix per generation, q its cached-read cost per generation, s its storage cost per hour, h the retained hours and c the one-time creation cost. With N total generations including the first, explicit reuse breaks even against uncached generation when `N × (p − q) ≥ c + s × h`, provided p > q. This omits other differences; compare actual automatic caching, miss probability, lookup latency, output and invalidation as well. If there is no trustworthy usage or cost data, label the result unmeasured rather than treating unknown as zero.

A cache discount does not free context-window occupancy: append-only replay may retain detail and eligible cache boundaries while its growing input still crowds out useful work. Compare continued replay with a bounded edit or compaction using ordinary input, cache reads and creation, reduction output, user-visible delay and preservation quality. Prefer stable reuse while it remains correct and economical; accept necessary rewrites when their benefit warrants the affected cache loss, and do not assume an unchanged earlier registered boundary is lost with a later one.

## Provider and client deltas

| Concern | Anthropic | OpenAI | Gemini |
|---|---|---|---|
| Typical mechanism | Explicit marked breakpoints are available on some routes; legal block types, minimums, lifetime and invalidators are model/route-specific. | Automatic prefix reuse on supported routes; an adapter may strip another provider's markers. Native explicit breakpoint pass-through is route/version-specific and requires route-specific verification. | Implicit reuse may be available; explicit cached-content resources bind a selected contiguous prefix on some adapters. |
| Validation | Verify markable blocks, controls, warm-up and counters; an earlier unchanged boundary may still hit after a later edit. | Compare effective request and reported cached tokens; marker logs alone do not establish provider behavior. | Reconstruct resource plus suffix; check object scope, key, creation, storage and fallback. Compare with implicit reuse, not an assumed uncached baseline. |
| Maintenance calls | Reuse of a foreground prefix on maintenance calls is unmeasured. | Same; same alias does not prove reuse. | Same; a different client or control may change eligibility. |

Vendor minimums, prices, cache visibility and settings change; route-specific observations do not establish a current universal contract. Recheck the exact supported route before depending on them. If unmeasured, budget maintenance input at the ordinary rate.

If selecting a maintenance route, compare output quality, total cost and latency under the actual workload, with correctness first. Neither the same alias nor a different alias proves reuse or its absence; measure the effective request and supported counters on each route, and treat unmeasured reuse as unknown. Check a quality failure and an alternative with different total costs before selecting.

## Causal lessons and checks

**Premise:** a persisted conversation should reuse a growing prefix. **Symptom:** only the stable instruction region hits on each new turn. **Cause and evidence status:** a snapshot inserted for a prior turn but omitted from replay changes the effective prefix; source analysis supports this mechanism, not every observed miss. **Rule and reason:** persist and replay the correct per-run snapshot when this history contract applies. **Check and expected evidence:** inspect consecutive provider-effective requests and cold/warm usage; a replayed eligible prefix matches and counters support reuse. **Does not apply when:** history is caller-owned and prior snapshots are deliberately not replayed.

**Premise:** an eligible request reports no reads or writes. **Symptom:** a successful call appears uncached. **Cause and evidence status:** a short prefix, missing marker, expiry, eviction, unsupported counter or route variation can look alike. **Rule and reason:** combine size, actual marker decision and counter presence with request comparison; do not assign a cause from zero alone. **Check and expected evidence:** qualify an eligible cold request followed by a warm one, record decision and raw usage; if counters are absent, the result is unknown. **Does not apply when:** the route provides no reusable prefix.

**Premise:** a cache layout is being optimized. **Symptom:** a candidate looks faster or cheaper because it inherits another arm's warm entry. **Cause and evidence status:** a shared prefix contaminates sequential comparisons; cost also excludes explicit-resource charges if only generation usage is inspected. **Rule and reason:** isolate or counterbalance arms and compare total costs and correctness. **Check and expected evidence:** unique eligible prefixes, cold controls where counters support them, identical task and controls, recorded create/storage/generation costs; stop on the agreed spend or rate-limit gate. **Does not apply when:** no comparative measurement is claimed.

Build checks compare the complete post-adapter request through each reusable boundary and exercise a valid and an invalid explicit-resource reconstruction. Debug checks classify cold, warm, rewrite, privacy change and absent-usage cases without inferring causes from counters alone. Optimize checks freeze task-quality and cost criteria, use representative requests, include all billed operations and report uncertainty. Foreground observations do not establish maintenance reuse or general production savings.

If capturing provider-effective requests for a cache claim, govern sensitive full-request evidence with restricted access, short retention and no credentials; publish separately redacted summaries. This recorder and mutation suite are **proposed**, not evidence of a built facility. Mutate a tool schema and the transient-tail boundary and verify the comparison detects both; a redaction that changes equality-bearing text cannot prove byte stability. Capture the gateway-effective view separately when the claim concerns that boundary.

## Worked example — one implementation under stated premises

Premises X: an assistant sends multiple calls with stable instructions and tools over one authorized session, and its route reports cumulative cache usage. It replays stored snapshots, appends new tool pairs and uses an ephemeral reminder only at the tail. A necessary privacy correction changes earlier content, so it accepts the miss and verifies the corrected projection. It compares cold and warm calls and calculates ordinary, read, write and output cost before considering an explicit resource; no saving is claimed until the route reports sufficient evidence.
