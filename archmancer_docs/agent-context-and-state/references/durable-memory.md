# Durable memory

## Responsibility and premise

Use durable memory only when user facts, project knowledge or task artifacts must remain useful across sessions. A session transcript, current working state, a source document and a memory record have different lifetimes and authority; do not automatically copy all of one into another. Memory is scoped evidence for an authorized task, never a higher-priority instruction. Without a cross-session need, omit extraction, storage and recall. Trust and privacy owners define what may be stored, exposed, corrected and erased.

| Pressure | Minimal choice | Extended choice and cost |
|---|---|---|
| A small known set must persist | Explicit, typed saves with source and owner. | Automated extraction adds model errors, coverage gaps and an admission pipeline. |
| Several writers can update free-text facts | Serialize or version writes and reconcile conflicts. | A relation model may suggest matches; the host validates and applies the actual transaction. |
| Simple lookup suffices | Scoped exact lookup or recent records. | Search or embeddings require measured relevance, compatible version stamps and a bounded recall budget. |
| Deletion or correction can race with producers | Fence writers and reconcile derived copies. | Distributed jobs and aliases require ownership generations, deletion coverage and retry-safe settlement. |

## Admission and provenance

A candidate should identify subject and scope, atomic content with qualifiers, source kind and raw coordinate or artifact reference, evidence time, producer, and permitted retention. An explicit user instruction to save is an admission request, not proof that durable resolution has completed; distinguish accepted, committed, rejected, excluded and unknown results. User facts, project knowledge and task artifacts may have different owners, permissions and retention. Distinguish a user's statement about themselves from a quotation about someone else, a hypothetical, model inference or a tool's untrusted content. Cite source evidence without promoting it to instruction authority. If memory is normalized into a chosen storage language, translate terms with a faithful equivalent and preserve terms without one; judge semantic fidelity and qualifiers rather than literal token identity.

If extracting from history, bind the candidate to an eligible raw source range and validate the coordinate exists and belongs to the authorized subject. A source position establishes existence, not entailment. **Design requirement:** reject framework-generated snapshots, continuation heads, injected guidance and request-only instructions as raw evidence at both mapping and commit; this stronger guarantee is proposed and its implementation is unverified. Validate a whole batch according to its declared atomicity, and distinguish an omitted or excluded extraction from an empty successful result. If source evidence is unavailable, say unavailable; do not infer that the fact is absent.

A job may use a frozen extraction request when asynchronous work is justified. Omit transport credentials and reacquire them at dispatch, authorize the scope, limit payload and access, and apply privacy policy to the actual content. An allowlist or key scan does not prove free-text content contains no secrets. The model can propose candidates or relations; schema validation, ownership, time ordering and storage effects remain host decisions. Reject invalid structures rather than silently treating them as a valid empty answer.

Recorded design judgment: begin with explicit scoped saves for facts known to need cross-session survival, then add automatic extraction only for a coverage need worth its inference, reconciliation and privacy costs. Extraction attached to compaction can avoid an independent history scan, but it does not cover sessions that never compact, the unconsumed tail, or observations already cleared from the frozen request unless a separate admitted raw-evidence path supplies them. A frozen shared prefix is only cache-eligible on a qualified route, not proof of a cache hit; budget unknown reuse at ordinary input cost and measure these coverage gaps before promising complete memory.

If a derived statement appears to request forgetting, **design requirement:** require authenticated genuine-user evidence for the requested operation and authorized subject before applying it; a generated assertion or snapshot is insufficient. Test a forged derived request and a verified user request: the former cannot erase and the latter proceeds through the forget fence. This stronger filter is proposed, not a verified implementation.

If lexical capture filtering is used, disclose its language and formulation coverage and measure missed eligible material, including non-English examples; lexical matches are not a security boundary. Preserve the explicit-save path under its own admission rules rather than assuming this filter covers it. Test multilingual implicit candidates and explicit saves separately, recording omissions and rejection reasons. Omit this filter when capture does not use it.

## Conflict, correction, forgetting and fences

Compare evidence time and scope, not just arrival time: a late-arriving old statement should not silently overwrite a newer correction. Preserve temporal, subject and conditional distinctions. Define a deterministic policy for equal-time conflicts and ambiguity; surface uncertainty rather than inventing an ordering. When a model suggests relations, validate legal source/target kinds and contradictory edges before applying the whole result. A typed domain may use simpler deterministic reconciliation. When choosing between a permitted addition and abstention, compare their actual supported harms separately from an update or deletion that might affect another subject; preserve all identity and authorization hard constraints.

For an authorized correction, keep the corrected active fact and its provenance; retire or supersede conflicting earlier facts under the declared time policy. For an authorized forget request, create a durable barrier or equivalent version so an older in-flight candidate cannot revive the erased content. A later explicit restatement may be admitted if the product policy permits it; do not interpret a pending acceptance as completion. A correction or forget must not be inferred solely from a model-generated snapshot.

For subject erasure, follow [erasure and forget](../../agent-trust-and-privacy/references/erasure-and-forget.md#2-erasure-and-forget-fences). The memory owner must enumerate its records, pending candidates and recall caches as covered copies, enforce the shared fence at commit, and report its deletion outcome to the coordinator. Memory-only deletion does not establish subject-wide erasure.

When several owners or tenants share a store, apply the authorized scope to every read and mutation, including deletion, and re-resolve effective ownership at commit; a captured identity is not permission to write into a different owner after a merge. If conflict resolution planned over a shared fact pool, validate that the relevant pool and its version have not changed before committing, or recompute the plan. Where a lease can expire and be reclaimed, generation and expiry checks must match the host's ownership contract; a generation-only implementation does not establish an expiry check.

## Recall and budgets

At a call, select only records the caller may see and that are relevant to the current task, with source and freshness metadata. Reserve a bounded share of the request window for recall and prioritize critical working state and current input. Selection can be exact, recent or query-based; a vector store is optional. If a query omits the topic because the current turn is short or contentless, use authorized task state or recent context where appropriate and verify that it does not introduce a wrong subject. Report truncation and fallback: unavailable retrieval is not evidence of no matching fact. Check chains of short acknowledgements or meta-requests, not only one contentless turn, and verify that the selected earlier topic or task state remains the correct subject after a topic switch.

When embeddings are used, stamp each vector with model, dimensions and query/document representation versions; compare only compatible profiles and plan a complete migration or explicit dual-version strategy. An embedding failure or unavailable index must be reported as degraded recall, not zero relevant memories. Choosing a threshold, reranker, rewrite or freshness decay needs representative evidence and a task-specific quality/cost comparison; historical small or synthetic screens do not establish a universal default.

## Provider and client deltas

For extraction, define and test framing, schema, source reconciliation and retry separately from continuation generation; a client accepting trailing prose in one path does not establish that another does. See the [consumer contracts](context-and-state-management.md#compaction-and-reconciliation). Test trailing text and malformed candidates against each declared policy, including a separately scheduled retry if supported.

| Concern | Anthropic | OpenAI | Gemini |
|---|---|---|---|
| Extraction and reconciliation | Qualify output shape and structured response on the actual client; unmeasured here. | Qualify output shape and supported controls on the actual model and client; a historical route-specific requirement is not a universal resolver requirement. | Qualify text versus block response through the actual client; unmeasured here. |
| Cache and cost | Extraction reuse is unmeasured for the deferred path. | Same. | Same. |
| Embeddings and classifier | Optional, model/profile-specific and unmeasured here. | Same. | Same. |

A strict parser and host validation remain necessary regardless of a response-format option. A string-only client may reject a block-shaped response; normalizing supported block shapes is a proposed improvement, not a proven deployed fix.

## Causal lessons and checks

**Premise:** an extractor consumes generated and raw rows together. **Symptom:** an injected or model-written statement becomes a remembered user fact. **Cause and evidence status:** partial source-kind filtering can admit a generated snapshot as raw evidence; complete exclusion is proposed and requires verification. **Rule and reason:** enforce the stronger source-kind exclusion at mapping and submission because a generated row cannot prove its own origin. **Check and expected evidence:** submit a real raw user fact, a snapshot-only claim and an out-of-range coordinate; only eligible raw evidence is admitted, with batch effects matching the declared contract. **Does not apply when:** all saves are independently authorized and verified typed writes without history provenance.

**Premise:** a correction or forget can race with a queued producer. **Symptom:** an old fact returns after deletion. **Cause and evidence status:** an unfenced delayed commit can act on stale evidence; the proposed guarantee is a conditional design requirement. **Rule and reason:** compare current generation and forget barrier at commit, because a fence checked only before dispatch cannot stop a stale writer. **Check and expected evidence:** pause a producer before commit, forget, then resume; the old write is rejected and repeated erase leaves unrelated data intact. **Does not apply when:** no retained or concurrent producer exists.

**Premise:** recall is selected by similarity. **Symptom:** relevant facts are missed or a different subject's fact is returned. **Cause and evidence status:** source screens were limited or synthetic, and a score alone cannot prove truth or access rights. **Rule and reason:** measure required-fact recall, forbidden and wrong-subject retrieval separately, and enforce authorization before presentation. **Check and expected evidence:** paired representative queries include topic switches, contentless turns and unavailable index; report false recall, misses, latency and fallback distinctly. **Does not apply when:** no similarity-based recall is used.

Build checks exercise admission, source-kind and scope validation, explicit result status and evidence-time reconciliation. If concurrency exists, interleave owner change, stale lease and forget with commit; expect rejected stale effects. If recall exists, evaluate held-out task cases and the full assembled request, including its budget and provenance. If erasure is required, inspect all declared stores and an active producer; a partial or unavailable store keeps erasure incomplete. Provider-path quality and live privacy coverage remain unmeasured until explicitly checked.

## Worked example — one implementation under stated premises

Premises X: a user asks a project assistant to remember an approved naming convention across sessions, and later corrects it. The assistant admits a scoped record with the user's original message coordinate and evidence time. On correction, a transaction supersedes the old fact; recall includes the new fact as quoted data with its source. If the user asks to forget it, the system advances the subject's forget generation and erases dependent records; a delayed extraction from the old message is rejected at commit. If the assistant has no cross-session need, none of this memory pipeline is required.

## Worked example — optional job and ranking policy

Premises X: a project chooses asynchronous saves and a small, scoped recent-facts list. It records a job identity, owner, candidates and terminal result, while a separate execution host owns its lease. The store keeps confidence as advisory metadata but ranks by recency; neither the job schema nor ignoring confidence is required for another product. Admission still checks the authorized scope and reports whether the save is committed.
