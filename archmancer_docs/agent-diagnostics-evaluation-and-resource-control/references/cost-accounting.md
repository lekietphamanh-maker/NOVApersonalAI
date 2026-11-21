# Cost accounting and control

## 1. Premise and boundary

Read this leaf only when paid-resource visibility, attribution, budget enforcement or reconciliation is required. A small local prototype can begin with a manually inspected provider report; introduce durable accounting when missing attempts, shared billing, concurrent limits or audit needs make that insufficient. The [model boundary](../../agent-harness-model-and-tools/references/model-boundary.md) owns the actual call contract; accounting records what can be established about its resource use.

## 2. Minimal interface and state

Inventory each paid producer and operation, including retries, embeddings, auxiliary calls, cache creation, background work and evaluation traffic. Define the accounting grain before dispatch: an invocation is a logical model call, while an attempt identifies an admitted send or an explicitly bounded set of billable suboperations. If every physical send must be audited, allocate each a stable identity before sending and relate it to its invocation. Provider response ids are useful reconciliation evidence but may never arrive. If a gateway can retry or fan out internally, account for each send or prevent that behavior under the chosen grain.

A versioned attribution envelope names the authenticated scope, initiator, producer, operation, charge target and optional run or invocation ids. Bind its claims to trusted credential and server-owned scope, including optional provenance, and reject inconsistent identities. Explicitly define which operations may charge which targets and which dimensions are required; an opaque correlation id is not authority. Background jobs persist a non-secret scope and rebuild and reauthorize it at execution, rather than persisting expired credentials. Distinguish platform or shared work from subject work according to the product's actual policy.

Represent attempt identity, attribution validity, charge level, outcome, cost status, usage and price basis as separate fields. Reservation measures are unknown until evidence arrives. A valid attribution can have unknown cost; a priced zero is valid only with evidence of zero charge. A failed or cancelled call that reached a provider may still be billable. Preserve component-level known and unknown values and never add overlapping usage buckets.

If recovery wrappers nest, define separate counts and bounds for accepted responses, accepted corrections, completion retries and transport sends. A correction can cause another completion and each completion can cause several sends; specify whether discarded corrections count toward the raw-completion bound and whether transport retries are outside it; multiplying only one wrapper's bound understates potential cost. Check exhausted and successful branches against actual dispatch records and the declared raw-completion bound; this distinction is unnecessary when there is only one verified send path.

If attribution depends on credential metadata, validate types and allowed field combinations against authoritative trusted metadata before selecting a charge target; reject malformed, contradictory or unauthorized combinations. When metadata changes, verify replacement and cache invalidation in every process that can attribute calls, including a process holding an old cached value; until then the effective attribution is unverified.

## 3. Choice under pressure

| Pressure | Minimal option | Extension and trade-off |
|---|---|---|
| Occasional cost visibility | Provider report and scoped run identifiers | Attempt ledger when producer-level attribution and missing-call detection matter. |
| Untraceable spend unacceptable | Durable acknowledged identity record before dispatch; refuse if unavailable | A local durable journal plus replay can prioritize availability, but adds a failure domain and is proposed and requires verification. |
| A limit is advisory | Compare known settled spend with a stated policy | This is soft: concurrent and unsettled liability can overshoot without a finite bound from that check alone. |
| A hard monetary limit | No hard-cap claim until it is enforced | Atomic scoped hold covering conservative maximum liability, admission of all paid paths, settlement and safe release; qualify estimator and unresolved liability. |
| Per-step accounting | Run-level total | Scoped invocation join to attempts; report unlinked populations separately. |
| Financial audit | Attempt rows and usage/rate basis | Independent provider or invoice reconciliation and a repair process when evidence and retention support it. |

The identity reservation and the monetary hold have different purposes and state machines. A reservation that carries no amount cannot protect a cap. A monetary hold is a proposed cap mechanism, not a verified implementation; an estimate endpoint alone does not prove admission enforcement.

A hold or shared-credential budget is a policy choice, not universally rejected: assess whether conservative liability estimates are accurate enough for the intended bound and whether the charge identity is authoritative. If either premise is missing, a hold can misallocate capacity or the budget can charge the wrong owner; qualify both with disputed and concurrent cases before relying on them.

## 4. Conditional invariants

When untraceable spend is unacceptable, create the trusted attempt record and verify its matching acknowledgement before provider dispatch. A lost acknowledgement can leave a committed record even when the caller refuses to send; do not infer absence or delete it. Freeze settlement payloads for retry, deduplicate repeat delivery by attempt identity, preserve known measures and terminal outcomes, and quarantine conflicting charge identities rather than merging fields into an identity nobody asserted. Where older attempt-less evidence exists, reconcile or take it over without double counting; document any weaker legacy merge.

Classify reservations as pending, then settled, overdue or explicitly unresolved according to evidence. A late valid settlement converges on the same attempt. A stream that never reports final usage, a lost creation response or an in-flight cancellation can leave billability unknown. A proven local refusal before any upstream send may be certified zero; a timeout or client disconnect alone cannot. Report known recorded spend with an unknown-attempt count and the population and time window; unknown is not zero.

For price calculation, retain route, model, currency, effective rate basis and the usage categories necessary to reproduce the bill when that reproducibility is required. Normalize ordinary input, cache reads, cache writes, output and reasoning only after checking whether each provider's reported buckets overlap. Missing rate, tier or count remains unknown; a numeric library result is not proof that all rates existed. Explicit cache creation and scheduled storage may be additive; label a lifetime-based storage calculation as an estimate. Recompute a record against its own usage and effective rates.

If separate actors settle or repair the ledger, use a second witness and compare the same scope and time boundary. An overdue sweep should expose stuck reservations independently of optional repair; bound scans, record incomplete pages, retain a durable repair watermark only through fully processed ranges, and leave unparseable rows for adjudication. An aggregate invoice difference can expose a bypass but cannot price each unknown attempt. Retain independent egress or credential controls when complete coverage is promised.

When enforcing a limit, define its owner, dimensions, window and the population that counts; do not derive a charge target merely from a provenance field. Validate non-finite, negative, missing and explicitly zero settings separately. A soft settled-spend gate must name excluded pending and in-flight liability; synchronize concurrent admission in a check to measure exposure. A hard hold must atomically admit against committed spend plus all unresolved and in-flight maximum liabilities, then settle actuals, releasing only amounts known not to have been dispatched. Accounting records contain only allowed metadata; retention and erasure policies cover both the ledger and independent witnesses without pretending an opaque subject identifier is anonymous.

If authorization maps operations to charges, derive the operation from the trusted principal and apply an explicit allowlist of permitted operation and target combinations; reject an unknown principal or unpermitted target. Check forged operation and target inputs against the server decision.

If independent caps apply, define each predicate, owner, counted population, event-time window and settlement lag separately. Compare reports to gates only over matching boundaries; demonstrate late settlement and events at each window edge, because totals can legitimately differ.

If local prices calculate charges, qualify the actual route's final usage and every effective rate component against an independent authoritative price source for the applicable tier and time. Compare the selected map with that source, then independently recompute using the recorded units; arithmetic agreement with the same wrong map is not price validation, and neither is invoice proof. Streaming headers or interim estimates remain provisional until final evidence arrives. If price reload fails, retain the last known map with an explicit stale status, alert or refuse according to policy, and do not certify current rates without independent evidence. Test a missing cache-write rate, an altered rate, failed reload and final-usage replacement.

If cache creation or storage is separately billed, assign stable identities to each operation and correction, bind creation to its resource and matching model, derive storage from evidenced token count, lifetime and effective rate, apply a matching correction once, and reconcile partial creation or a lost response before reporting the final amount. A duplicate correction must not double charge; an unavailable outcome stays unresolved rather than being assumed absent.

## 5. Causal lessons

**Premise:** settlement delivery can be retried. **Symptom:** a single provider send appears twice in spend. **Cause and evidence status:** a repeated provider send and a duplicated settlement callback have different causes and require distinct identities. **Rule and reason:** identify billable attempts before send and make delivery idempotent, because a provider response id may be lost. **Check and expected evidence:** replay the same settlement concurrently and trigger an actual new attempt; one row remains for the former and distinct rows for the latter. **Does not apply when:** there is a proven single atomic send-and-accounting boundary.

**Premise:** an admission gate reads only settled cost. **Symptom:** a supposedly hard cap is exceeded by overlapping runs. **Cause and evidence status:** source analysis establishes pending and concurrent work is excluded; no finite overshoot was established. **Rule and reason:** call this a soft gate and use an atomic liability hold only when a hard ceiling is required. **Check and expected evidence:** align two admissions before settlement and then settle a previously unknown attempt; record the timeline and actual exposure. **Does not apply when:** a qualified atomic hold covers all billable paths.

**Premise:** usage evidence is incomplete after a stream stops. **Symptom:** a cost report displays zero despite possible provider billing. **Cause and evidence status:** pre-first-event and lost-response gaps were source-identified; their representative rate was not measured. **Rule and reason:** preserve unknown liability until an itemized trustworthy witness resolves it. **Check and expected evidence:** inject pre-event cancellation and late settlement; the record becomes unresolved, then converges only if matching evidence arrives. **Does not apply when:** trusted terminal evidence establishes zero usage.

**Premise:** the reservation write and acknowledgement cross a failure boundary. **Symptom:** dispatch is refused after an acknowledgement is lost, yet a reservation exists. **Cause and evidence status:** a commit before lost acknowledgement is possible by protocol reasoning, not an observed outage. **Rule and reason:** reconcile the existing attempt row rather than assuming no write; a genuinely new request receives a new attempt identity. **Check and expected evidence:** interrupt after commit before acknowledgement and verify no upstream send and one reconcilable row. **Does not apply when:** the write and acknowledgement are an atomic local operation.

## 6. Provider and client deltas

| Concern | Anthropic | OpenAI | Gemini |
|---|---|---|---|
| Usage buckets | Native input and cache buckets may be separate; verify the pinned adapter before arithmetic. | Cached input may be included within a prompt total; verify actual adapter fields and effective rates. | Cache creation, reads and storage can differ on a route; treat each operation and rate as distinct. |
| Streaming and incomplete evidence | Qualify terminal usage and cancellation for the actual route. | Same; reasoning fields may overlap output and must not be added twice. | Same; explicit cache creation or storage may remain unknown after a lost response. |

Provider behavior and prices change; source examples are not current rate cards. Qualify every supported model, route, adapter version and price tier as implemented, fallback, unsupported or unmeasured; do not infer one provider from another.

For each enabled non-chat route, specify its billable unit, usage fields, operation identity and conversion to charge; validate the actual adapter's types and required fields before arithmetic. Reject booleans as numeric counts, negative and non-finite values; an absent or malformed count, including an uncertified zero, stays unknown. Exercise distinct operations, malformed fields and route-specific units against independently qualified rates.

## 7. Build, debug and optimize checks

- **If attribution is required:** enumerate producers and use a boundary fixture for each; an omitted paid path or a forged scope that is accepted fails coverage.
- **If reserve-before-send is selected:** force lost acknowledgement, rejected credential, duplicate reservation, malformed settlement and late delivery; expect zero sends without an accepted reservation and one convergent record per admitted attempt.
- **If cost is reported:** exercise known zero, unknown, partially priced, cancelled, retry and cache-creation paths; expect separate status, known amount and unknown count. Check price arithmetic against each attempt's own usage.
- **If a hard cap is claimed:** test parallel admissions, cancellation before dispatch, lost usage after dispatch and late settlement; admission must preserve the conservative unresolved liability and never exceed the declared bound.
- **If repair is used:** exercise a long outage, first enable without a watermark, page truncation and capped writes; report the exact covered range and unresolved entries. Invoice totals do not repair individual rows without itemized evidence.

## 8. Worked example — one implementation under stated premises

Premises: a hosted assistant shares a provider account, must attribute every paid send, and accepts a soft daily limit. Its dispatch boundary binds an authenticated scope and records attempt A before a call. A streamed request disconnects without final usage; A remains billability unknown. A later retry creates attempt B and settles with known usage. The report lists B's known amount and A as unresolved; the gate is described as soft because it excludes A and simultaneous work. A later itemized provider record may resolve A, while a monthly aggregate alone cannot.

If a paid batch route is enabled, qualify admission, per-item or per-attempt identity, terminal usage and its effective discount before treating it as covered. Where a non-billable lookup precedes cache creation and generation, use separate send allowances for the billable operations so the lookup cannot consume the generation allowance. If an existing summary reader uses weakly consistent pages, use a consistent aggregate snapshot for a financial total rather than adding page results.

If a usage reader paginates scoped records, bind its cursor to the authenticated scope and all effective filters and enforce isolation server-side on every page. Label pages weakly consistent when writes may change the population between requests; test cursor reuse across scopes and changed filters, and do not present a paged sum as a consistent financial snapshot.

If accounting delivery runs asynchronously, measure its backlog and settlement lag; an awaited failure hook can still delay a response, so qualify each path independently. A rejected accounting credential can block every dispatch in a fail-closed design. Test delivery limits and lost acknowledgements under the target workload instead of transferring source defaults.

For every enabled paid route, state whether it passes the same attribution and limit boundaries; a run-admission gate does not automatically enforce a limit on background or service-key calls. Validate required report dimensions, separate missing from explicit zero and reject malformed scopes instead of returning zero. A selected storage adapter may preserve emitted outcome detail only in part: read the persisted row and its evidence carrier before claiming the detail survived. Compare the same admitted identity across context and cost paths, reject transport control characters, and preserve validated opaque identity bytes.
