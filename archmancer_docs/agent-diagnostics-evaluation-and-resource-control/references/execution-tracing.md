# Execution tracing

## 1. Premise and boundary

Read this leaf only when a run's internal steps, cross-process path or timing cannot be reconstructed adequately from simpler records. A trace is diagnostic evidence, not the authority for a run decision, effect or charge. The [diagnostics chapter](diagnostics-evaluation-and-resource-control.md) chooses evidence by question; [cost accounting](cost-accounting.md) owns paid-attempt settlement. Treat a trace link as optional where sampling, exporter failure or retention can remove it.

## 2. Identity and span contract

Define a table of concepts, minting owner, lifetime, carrier, trusted source and receiving hops. A run names the admitted task; an attempt or generation names one ownership period; a logical turn names progress across recovery; an operation key names an intended effect; a model invocation can contain several provider attempts; a trace and span name diagnostic records. A request id can be local to one hop. These identities need not have the same cardinality, and correlation identifiers confer no authority. The host and action owners define durable identity and recovery in [durable execution](../../agent-runtime-and-interaction/references/durable-execution-and-recovery.md) and [action and tool boundary](../../agent-harness-model-and-tools/references/action-and-tool-boundary.md).

If delegation crosses processes, preserve trusted parent and root lineage in the run record or propagate trace links, and test every receiving hop. Reconstruct child scope from authorized parent state rather than trusting incoming ancestry. Background jobs may have a job identity and no run, invocation or span; inventory their actual coverage. A run can produce zero, one or several traces, so associate them with attempts using available generation, timing and logs; mark ambiguous links rather than counting traces as retries.

If paid retrieval belongs in a run total, propagate trusted scoped run attribution to its producer even when no span exists; reconcile its paid attempt separately as unlinked. If history filters depend on producer classification, define and preserve the required classification fields at every producer and persistence hop; missing classification must be visible, not silently filtered away. Check a spanless retrieval and each filtered producer against the authoritative records.

A useful span records a scoped identity, kind, start and end, status, safe error category and, where permitted and needed, input and output. Model spans can carry model, route, invocation identity and available usage; tool spans carry the tool, arguments and result without invented token counts. Preserve raw presence: an absent usage key is unavailable, not zero, even if the store fills numeric columns with zero. Retain the capture boundary and payload omission policy so a reader knows what the span can prove.

## 3. Decisions under pressure

| Pressure | Minimal option | Extension and trade-off |
|---|---|---|
| Cross-process correlation | Scoped application ids in records and logs | Propagated trace context provides a waterfall when every hop can preserve and validate it; retain application lineage for recovery and cost. |
| Many events obscure a path | Structured events with timestamps | Span tree or linked traces show nesting; qualify parent links and missing spans. |
| Large or sensitive payloads | Metadata and references to permitted evidence | Governed capture with bounded access, retention and deletion only when the question needs it and policy permits it. |
| High event volume | Unsampled records within capacity | Sampling with explicit coverage; head sampling cannot guarantee an error discovered later, so use a bounded tail buffer or separate unsampled error record if that guarantee matters. |
| Cost per invocation | Run-level attributed totals | Join invocation ids to attempt rows, partitioning unmatched attempts and preserving unknown amounts. |
| Trace navigation needs exceed an existing reader | Use the existing reader | Add a focused viewer only for a demonstrated gap, with server-side authorization and explicit partial results. |

Choose propagated trace context or scoped application-id joins according to the receiving hops and diagnostic needs. Qualify lineage and outbound-capture coverage on the selected route; neither option establishes complete capture by itself.

Use local structured records first when they answer the decision; a span tree buys cross-boundary timing and nesting but adds propagation, storage, export and reader-maintenance work. Sampling can lower that volume while making reconstruction incomplete, especially for errors discovered after a head-sampling decision. This is a recorded design judgment, not a measured overhead estimate. Add tracing only for a named evidence gap, declare sampled coverage, and keep any required durable audit or billable-attempt record outside an optional sampled diagnostic path.

Payload capture buys direct inspection and potentially replayable evidence, but collecting and serializing bodies can add caller-visible latency, storage cost and sensitive-data exposure; metadata alone is cheaper and safer but may leave a semantic cause unknown. This is a recorded design judgment; an observed overhead on one workload is not a portable estimate. Start with safe identities, phase timings and references, then capture only the permitted content needed to distinguish the remaining hypotheses, with bounded access, duration, retention and verified protection before export.

## 4. Protection, joins and failure contracts

Agree a per-sink policy before export: authorized principals, purpose, retention, deletion, permitted fields, supported serialized carriers and failure response. A protection interface returns a safe record or an explicit withhold outcome. Where the promise says raw data cannot leave a process, protect names, keys, resources, values, numbers, encoded structures, exception events and attachments before any retaining sink. If a carrier is unsupported or protection fails, withhold it. A second scope can suppress instrumentation during raw handling; end it before an asynchronous generator yields so suppression does not leak into its consumer. See [sensitive data lifecycle](../../agent-trust-and-privacy/references/sensitive-data-lifecycle.md).

Install and verify protection before enabling exporters. When an SDK uses a set-once global provider, verify the provider actually published is the protected candidate; on collision do not shut down the host-owned provider. A later best-effort scrub or a store-side pass cannot establish a pre-export promise. Check all registration paths: suppressing callbacks alone might not disable an independently configured tracer. If a clean-text cache survives rule changes, invalidate it or bind the rule version; where a literal all-input privacy guarantee applies, a digest-only equality shortcut cannot prove equality.

Diagnostic failure normally should not replace an execution outcome or call the wrapped operation twice; a system requiring durable audit before effects instead needs an explicit admission and audit-failure policy. Mark exporter drops, disabled sinks, partial initialization, missing payload and unavailable attributes. If export delivery is repeatable, deduplicate on scoped span identity. If a trace expires, its product record must survive and show the soft link unresolved. Neither missing spans nor local cancellation prove that a dispatched effect failed.

If an exporter is process-global and runs overlap, select the destination from trusted per-run scope for each record or isolate exporters; one static process identity cannot distinguish concurrent scopes. Exercise interleaved scopes and missing or forged carriers and verify destination isolation. When wrapping a hook, retain and invoke the original exactly once, preserve its outcome, and handle absent parent context without inventing lineage; check normal, error and no-parent paths.

If analytics can drop or duplicate events, identify independent authoritative sources for attempts and completions, reconcile event identity and delivery coverage, and use those sources as denominators rather than treating a lossy analytics count as the whole population. Test drops and replay duplicates.

For per-invocation cost, join on authorized scope and invocation id; a single invocation may have multiple attempt rows. Report known settled cost, unknown or unsettled count, and completeness for the named population. Reconcile separately span-linked attempts, attempts with no invocation id, and attempts with an id but no observed span. A complete span-linked subtotal does not establish complete run spend; avoid adding a library estimate to recorded spend. A refusal before reservation may have no ledger row.

A framework span may show the request before guard transformation, cache markers or provider adaptation. Compare provider-effective requests at the actual relevant seams before making a cache-prefix claim; a redacted capture proves only retained content and structure, not equality of removed raw bytes. [Cache layout](../../agent-context-and-state/references/prompt-cache-layout.md) owns the comparison method.

If a reader is offered, authorize each project and span server-side from the authenticated principal; a selector is not authority. Distinguish empty, not found, unauthorized, unavailable and partial; return cursors and omission counts; retain earlier pages after a later failure and discard stale responses after a new selection. Report metric coverage and avoid double-counting cumulative parent attributes.

For each reader, define independently the population of traces, spans and conversations and the scope of each search, facet and filter. A matching span subset or filtered trace list is not the whole conversation population. Exercise nested matches, multiple traces per conversation and filters with different scopes; label partial results and counts accordingly.

## 5. Causal lessons

**Premise:** a delegated action completes in another process. **Symptom:** its work is missing from the parent's trace. **Cause and evidence status:** separate trace roots and a dropped carrier can look alike; the selected route is unverified until its hops are checked. **Rule and reason:** join through trusted lineage and verify every hop because a missing trace parent is not proof of missing work. **Check and expected evidence:** compare parent and child run records, propagated ids and available spans; an unmatched child is a coverage gap. **Does not apply when:** all work shares a verified in-process span context.

**Premise:** a protection processor is installed dynamically. **Symptom:** a synthetic identifier reaches a sink despite a masking helper passing in isolation. **Cause and evidence status:** processor ordering failure or an ignored install result can expose data; hardened behavior is proposed and requires verification. **Rule and reason:** verify actual ordering and the published provider before export because a later transformation races an asynchronous exporter. **Check and expected evidence:** force setup failure and a preinstalled provider, then inspect serialized sink records across carriers; no unsafe export is allowed under the stated promise. **Does not apply when:** the sink never receives any protected data and the no-export boundary is independently verified.

**Premise:** a cost view sums only traced invocations. **Symptom:** its total differs from a run-level total. **Cause and evidence status:** background or unlinked attempts can belong to the run but not the span set; an observed cache discrepancy had no established root cause. **Rule and reason:** compare identical populations and expose coverage before diagnosing a broken join. **Check and expected evidence:** enumerate all three partitions and reconcile their individually known amounts; unexplained or unknown amounts remain visible. **Does not apply when:** all paid operations have a verified one-to-one span join and complete settlement.

## 6. Provider and client deltas

| Concern | Anthropic | OpenAI | Gemini |
|---|---|---|---|
| Usage and cache counters | Span-side mapping is unmeasured; compare native usage, adapter and sink on the chosen route. | Cache and reasoning details vary by route; qualify the selected adapter. | Span-side cache mapping was unmeasured; verify actual usage and absence separately. |
| Signatures and first-token timing | Signature coverage and first-token timing are route-dependent and unmeasured. | Same; a producer timestamp is required for a first-token value. | Signature-like fields can occur in messages and tool identifiers on a route; an after-export scrub is not a privacy guarantee. |

Streaming and non-streaming readers may consume different usage carriers. Compare raw response, adapter output and each enabled sink, and record route, model and client version; unavailable stays unavailable.

## 7. Build, debug and optimize checks

- **Always:** produce an identity and hop table and drive normal, missing and malformed carriers using an authorized fixture. Expect matching scoped records or a documented refusal; an unexplained orphan fails the promised join.
- **If spans are exported:** inject exporter failure and duplicate delivery; record execution outcome, durable record, span coverage and idempotency separately. An unsafe partially initialized sink must not export under a no-leave policy.
- **If delegation or background work exists:** verify child lineage, actual job identity and span coverage; simulate stale ownership and an uncertain dispatched effect using the host's recovery contract. A missing heartbeat or trace is not proof of rollback.
- **If a reader is built:** exercise multiple pages, missing access, a failed later page and a delayed response after selection changes; expect authorization, partial coverage and no stale overwrite.
- **If optimizing:** compare overhead with representative payloads and the same logging mode; measure exporter loss, latency, storage and the user's required evidence before selecting a sampling or retention bound. These are proposed checks, not proof of a deployed system.

If a recorder uses a bounded queue, measure eligible arrival bursts, destination latency, backlog and drain under the target workload, then choose capacity and shutdown bound against a declared loss budget. If the budget cannot tolerate loss, choose durable delivery and verify its recovery contract. Exercise eligibility, captured event, replay identity, full backlog, failed send and shutdown; reconcile actual destination receipts and duplicates rather than equating local enqueue with delivery. Source sizing was unmeasured; these are qualification checks.

## 8. Worked example — one implementation under stated premises

Premises: a hosted assistant uses a separate search process, emits one model call and may retry that call; a privacy policy permits only protected payloads in telemetry. The admission record supplies a run id, each model invocation gets an id, and each provider send gets its own attempt id. The search process receives the scoped run id; a trace link is optional. The trace reader joins one model span to two attempt records and lists a separately attributed search embedding as unlinked. If the exporter fails, the run record still describes the terminal outcome while trace coverage is unavailable; if the search effect is uncertain, the owner reconciles it before any replay.

If a trace reader offers search, verify actual navigation to a matching nested or truncated value, not only that the search predicate found serialized content. Temporarily reveal the relevant ancestors and restore prior disclosure state when the search clears; apply access and retention policy to every revealed carrier. Add a cross-project list only when the operator needs a question that a selected-project reader cannot answer.

If a product turn stores a link to an agent trace, bind the link to the intended agent root rather than the first diagnostic span that happens to start; discovery can start first. Check that the stored link resolves to the scoped root, and show an unresolved link when the root is missing or expired.

If the receiver selects an isolation scope from a transport carrier, ensure the exporter supplies that trusted carrier or an equivalent verified boundary; a scope attribute alone does not authorize the read or route the write. Check simultaneous scopes, missing or malformed scope, and exporter failure.

Where intermediate graph nodes repeat the whole accumulated state, keep metadata-only nodes or a bounded output delta if doing so preserves the evidence the investigation needs; an alternate protected source must hold omitted inputs. Measure repeated masking and serialization overhead under the actual workload before adding a cache. If a display label is mutable, use a stable scoped identity for joins and distinguish environments; a label alone can fragment or combine evidence. An effective configuration fingerprint may be placed on a root span when useful, but only the configuration owner can establish which version governed the run. A background job identifier may be carried by a validated body rather than a header; document the actual carrier and verify it at the receiver.
