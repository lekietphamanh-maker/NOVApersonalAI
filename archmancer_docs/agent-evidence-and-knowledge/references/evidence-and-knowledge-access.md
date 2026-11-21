# Evidence and knowledge access

## Responsibility, premise and omission

Evidence and knowledge access identifies and reads external information under verified authority, preserves lineage and reports freshness, completeness and failure. It owns the truthfulness of the evidence handoff, not admission authority, the model's next step, or the answer's presentation. A local file, database query or external search API can satisfy this responsibility without a knowledge service. Omit the call when the task requires no external evidence; do not omit an authority check merely because storage is local. Follow [flow 5](../../agent-system-engineering/references/system-flows.md#5-knowledge-grounded-answer) for the cross-component handoff.

## Minimal mechanism and request path

Given a focused information need and host-verified principal and permitted scope, identify an authoritative source and perform an authorized read. Return the source identity, its version or observation time when available, the passage or data needed, lineage, scope, and explicit status and omissions. The action boundary enforces the call contract; context management admits the result as provenance-bearing data; the harness distinguishes supported conclusions from inference. A file path alone is not a stable citation if the file can change; include a revision, content digest, snapshot or another resolvable version when exact reproduction is required. The [retrieval leaf](retrieval-and-grounding.md) gives per-need result mechanics.

Failure path: a source times out after another source responds. Preserve the usable evidence and record the unavailable source and affected need. An empty response, authorization-filtered result, omitted source, failed read and completed exhaustive search are different outcomes; none by itself proves that a fact does not exist. An authoritative source can support a negative claim only within the coverage, time and scope it actually establishes. A principal who cannot see an item must not learn its existence through an error or link.

## Decision table

| Pressure | Minimal option | Extended option and cost |
|---|---|---|
| A known file or row answers the need | Read the file or query SQL directly using the caller's permission; record identity and version. | Add a source abstraction only when multiple sources or consistent policies require it. |
| Relevant information is discoverable through an existing source | Use its search API and read original results when necessary. | Add ranking or federation only after measured recall or latency shows a need. |
| The product must accept, update or withdraw sources it owns | Maintain an owned corpus, source identities and lifecycle; see [corpus lifecycle](corpus-lifecycle.md). | Use asynchronous ingestion or generated metadata only when volume, durability or latency justifies it. |
| Exact access is insufficient at measured corpus scale | Select lexical, semantic, hybrid or another index on representative needs. | Indexes add lineage, consistency, operational and migration obligations; a vector service is not a default. |
| Search produces too much context | Return whole relevant passages with explicit budgets and omissions. | Evaluate extraction or pruning against answer-changing fact-loss controls; loss and latency may outweigh savings. |

## Scope and visibility

Derive scope from verified authority rather than model arguments. Bind authorization to the principal, resource, operation and applicable version; a credential permitting a read or a caller-provided scope header alone does not establish entitlement to that scope. See [authority and approval](../../agent-trust-and-privacy/references/authority-and-approval.md). When data has several visibility levels, write and test the actual visibility rule, including any shared and private branches. Never infer a broader scope from omitted identity fields. If the authorization service is unavailable, return unavailable or deny as policy specifies; do not assume access.

For mutable corpora, apply both visibility and serving eligibility on search, hydration, body reads, neighbours, links and any derived navigation input. Eligibility can depend on active revision, withdrawal and deletion; management/history access may intentionally use a different authorized policy so operators can see failures. Writers use the exact authorized target rather than the union of everything the caller can read. Enforce the same policy at the final read even if an earlier search filtered results. Test a foreign identity under another scope and ensure neither identity nor body leaks; other visible results may legitimately remain.

## Freshness and version-qualified reads

Name the source freshness requirement before reading: an immutable snapshot, bounded-stale data, latest available state or an explicitly mixed view. Carry source identity and revision through search, body read and citation. **Design requirement:** if an answer must cite exactly the text selected by search, qualify the body read by the selected immutable revision or snapshot and fail or restart when it changes. Search and body read can cross a promotion; version-qualified identities are a proposed requirement, not a verified fix. Check by promoting between selection and hydration; a mismatched body must not be presented as the selected revision. Where the source cannot provide a revision, report the observation time and weaker guarantee instead of inventing one.

A source can be fresh but unavailable, stale but readable, absent within a defined scope, partially returned, or excluded by policy. Return those distinctions and the scope of any negative conclusion to the harness. Cache or overview freshness must not be inferred from a successful fetch alone; a navigation overview is derived context, not exhaustive evidence.

## Grounding and citations

Treat retrieved text as data, not instructions or authorization; follow [untrusted content and injection](../../agent-trust-and-privacy/references/untrusted-content-and-injection.md). Ground each case-specific claim, value, plan premise and action input in a supporting source or another explicit basis. Preserve conditions, exceptions and the relationship between a value and its subject. Answer the supported part and name missing or conflicting evidence. An overview or a search snippet can guide a read but does not establish a fact unless the source contract makes that text authoritative and sufficient.

A citation maps a claim to a source identity, version and relevant passage or locator; verify the cited content actually supports the claim and applies to the requested entity and time. Presentation may hide internal identifiers, but retain provenance for authorized inspection. Distinguish source coverage from citation validity and factual completeness: a plausible citation is not proof of entailment.

## Making a source contract actionable

For each source, write down who owns it, which caller can request which operation, how the implementation resolves a source and its version, what scope the response covers, what freshness the source can attest, and which errors are distinguishable. A path, URL or database key identifies a location; pair it with a revision or snapshot when the content at that location can change. If a provider offers neither versioned reads nor a stable snapshot, record that limitation at the handoff and make it visible to the answerer. Define whether a missing item is indistinguishable from a forbidden item to prevent existence leaks, while allowing the trusted caller to distinguish an unavailable source from an ordinary scoped no-hit outcome.

For an answer spanning several sources, decide whether they must represent one coherent point in time. If they do, request a shared snapshot where supported or validate each source's version under a declared consistency rule; if the source systems cannot produce one, report the mixed-view limitation and avoid claiming a single atomic snapshot. If the task permits independent observations, retain the individual version and observation time instead of imposing a global transaction. A complete read at one source does not prove that an independent source was also available.

A familiar work practice is to keep source notes beside a research claim and recheck the cited passage before publication. An agent can use a similar claim-to-passage map, but its generated prose and citations do not prove it actually consulted the right version or preserved every condition. The host can verify identity, version and locator mechanically; semantic support and completeness require a suitable oracle or reviewer. Use that distinction to choose checks, not to assume a human-like memory of the source.

## Causal lessons

**Premise:** the source uses nearest-neighbour search. **Symptom:** an unrelated query returns plausible hits. **Cause and evidence status:** without a relevance cutoff, a nearest neighbour can exist even when irrelevant. **Rule and reason:** treat ranking as candidate ordering, not proof of relevance or existence. **Check and expected evidence:** use an out-of-domain question on a nonempty visible corpus; the answer rejects irrelevant passages and does not assert corpus-wide absence. **Does not apply when:** a separately calibrated relevance gate is part of the source contract, although that gate still needs false-negative checks.

**Premise:** source identity is reused across updates. **Symptom:** a citation points at content different from what was ranked. **Cause and evidence status:** statement-level eligibility without a cross-call revision token can select and read different revisions. **Rule and reason:** use a revision-qualified read when exact evidence consistency matters; atomic promotion alone does not make several reads atomic. **Check and expected evidence:** change the serving version between calls; return the pinned version or a conflict, not a silently substituted body. **Does not apply when:** the complete source is immutable for the read's lifetime.

**Premise:** a lookup fails or only part of a batch returns. **Symptom:** the answer claims no information exists. **Cause and evidence status:** reference result shapes can label all failed searches as no sources while errors distinguish them. **Rule and reason:** carry status and errors per need and describe the gap honestly. **Check and expected evidence:** inject one failure and then all failures; supported facts remain usable and failed needs are unavailable, not absent. **Does not apply when:** all requested evidence was read completely and an authoritative scoped source establishes the relevant absence.

## Provider and client deltas

| Concern | Anthropic | OpenAI | Gemini |
|---|---|---|---|
| Evidence-consuming tool schema | Qualify arrays, required fields and adapter behavior on the actual route; unmeasured here. | Qualify tool and request options on the exact model and adapter; a route-specific failure is not a family rule. | Verify array item schemas and union branches survive the adapter; a lost item schema can reject the request. |
| Embedding, if used | The embedding route is unmeasured; choose and qualify a compatible provider. | Qualify dimensions, association, token limits and retries for the chosen route. | A batch can collapse; verify cardinality and order on the actual adapter. |
| Grounding wording | Qualify on target cases; evidence is limited to particular models. | Qualify on target cases; a reminder result is not a provider-wide guarantee. | Qualify on target cases; a gap-filling observation is not a family-wide guarantee. |

No provider brand proves the selected client supports a specific encoding, retry or vector-space contract. For model request details see [model boundary](../../agent-harness-model-and-tools/references/model-boundary.md).

## Build, debug and optimize checks

- **Build:** record each source's owner, authorized principal, access path, source identity, freshness rule and expected status. Exercise valid, missing, forbidden, unavailable and partial responses; fail if any is presented as a complete successful read.
- **If mutable:** interleave promotion, withdrawal and deletion with search and body reads; check version-qualified results, eligibility and no stale resurrection. A mixed-version body fails a same-version promise.
- **If scope isolation applies:** use distinct shared and private fixtures and exercise each read path, guessed IDs and links. Verify actual protected identities and content are absent, not merely that one result list is empty.
- **Debug:** trace the exact need from source through selection, content read and final answer. Check the source actually contains the missing qualifier before changing the ranking algorithm.
- **If optimizing:** freeze representative cases, validity conditions, latency/cost and fact-loss gates; compare source recall and answer correctness separately. A successful citation count alone fails to prove supported answers. See [evaluation](../../agent-diagnostics-evaluation-and-resource-control/references/scenario-evaluation-and-experiments.md).

## Worked example — one implementation under stated premises

Premises: a local assistant answers a question about a versioned policy document accessible to its caller; no owned index is needed. It reads the file at the requested revision, retains the section heading and passage, and answers with the condition that appears in that passage. If the revision cannot be read, it says the source is unavailable. If the document explicitly defines a coverage list excluding the requested item, it states the gap in that document's scope; otherwise it leaves existence unresolved.

