# Corpus lifecycle

Read this leaf only when the product owns a corpus and must ingest, update, withdraw or delete its sources. For direct reads of an existing file, SQL database or search API, use the [home chapter](evidence-and-knowledge-access.md) and omit this lifecycle.

## Identity and visibility

Give a logical source an explicit owner and scope, a stable identity within that scope, and a distinct lifetime or revision identity. Keep raw-source fingerprint, normalized-body fingerprint and indexing recipe distinct: equal raw bytes do not establish that an earlier failed indexing operation succeeded. Define unchanged, retry, replacement and concurrent conflict separately. Scope is an authorized input, not inferred from whatever identifiers happen to be present; children and derived artifacts inherit a verified scope. A mutable existing source does not silently widen its visibility.

If stored children reference a parent within an isolated owning scope, enforce same-scope referential integrity at the storage boundary as well as the separate authorized read and exact-target write predicates. A composite scope-and-parent foreign key is one option when the store supports it; another store needs an equivalent atomic constraint. Check a direct cross-scope child insert and reassignment: both fail without creating a reference, while a valid same-scope insert succeeds.

If history survives deletion, a recreated source must not reuse a source-id/revision pair for different content. A deterministic id combined with a reset revision can retain an earlier body under the new revision; a lifetime identity or monotonic revision namespace is a proposed remedy, not a verified fix. Test delete, recreate with changed content, then compare the exact historical body and live body. Retention and immutability are separate policy choices; an append-only application role is not proof against every administrator or storage operation.

## Replacement and publication

If an uninterrupted coherent serving version is required, build a new generation separately and promote it atomically only after its declared checks succeed. Keep the previous version serving while work is in progress and after a failed replacement. Derive the target version once per logical operation, not anew on every attempt. A revision-qualified read, owned by the [home chapter](evidence-and-knowledge-access.md#freshness-and-version-qualified-reads), is still needed across separate requests.

If workers can be reclaimed, the execution host owns leases and attempt generations; this component compares current ownership and source version at every publication or destructive commit. A paused old worker cannot finalize after a newer owner takes over. Recover uncertain effects before retry; permit replay only when the same operation and payload are verified idempotent, otherwise stop for manual reconciliation. Distinguish retryable checkpoints, terminal failures and superseded work, and define who cleans each stage. Check a lost acknowledgement, a late old writer and a replacement failure; no stale writer may change the serving version.

When reusing a checkpoint, compare its source, version, split recipe and actual content before treating it as valid. A replacement path that reuses a job-owned stage without checking its split recipe can retain incompatible content; extending that validation is proposed, not verified. If a checkpoint cannot be verified, rebuild it or report the unresolved state rather than assuming reuse is safe.

## Parsing, splitting and indexing

Preserve original bytes where retention permits, and make extraction format, warnings, normalization, chunking and versioned recipes observable. An empty scan, partially extracted image and complete extraction have different outcomes. Test tables, late rows, repeated forms, names and mixed image/text pages against independent source facts; a nonempty parse, high model confidence or a smoke test is not a fidelity oracle. A model-based rescue is conditional and may fail or invent; label fallback and propagate a safe warning without exposing sensitive provider errors.

If optional polish or rescue fails in a handled way, retain usable primary extraction with a fixed safe warning and a quality limitation; if the primary body is empty, report the empty or skipped outcome rather than a successful ingest. Unexpected errors follow the declared failure policy rather than silently becoming a successful fallback. Inject a handled polish failure for both a usable and an empty primary body and inspect the body, warning and ingest outcome. Handling a specific polish error does not establish that every failure is handled.

If scan detection routes documents to a different extractor, calibrate that decision against independently labelled representative target documents, including textless, mixed and ordinary pages. Measure false routing and lost source facts on each branch; a small or unrepresentative sample cannot establish detector accuracy. This check is unnecessary when no detection-based route exists.

If a downstream model has an input limit, enforce separate body, metadata and combined limits before dispatch; qualify tokenizer headroom with the actual route and representative languages. Split oversized structures at meaningful boundaries, repeat headers where possible and preserve characters under a bounded fallback; report when structure cannot survive. If semantic vectors are used, verify cardinality, dimensions, finite values and input-to-output order before activation. Equal dimensions do not prove compatible spaces. Provide a scoped rebuild path rather than assuming identical-byte upload repairs a degraded index.

For changing vector models or recipes, recording model and document-recipe identity with each vector generation and separately versioning query preparation are proposed extensions whose implementation requires verification. Qualify compatible query/document encodings and retrieval on the target corpus before activation; rebuild affected stored vectors for a changed document recipe, and qualify a query-only change against the existing generation. Test mismatched recipes and model identities: incompatible combinations cannot silently activate. Measure token counts and headroom against the selected provider-native route on representative languages and difficult layouts; overflow or lost content fails the chosen limit.

## Agent-assisted ingestion

If an agent edits or summarizes staged material, bind every read and write to the host-issued principal, job, exact target, revision, operation and current admission. Persist admitted targets and mode before dispatch, then verify the committed artifacts independently of the agent's completion text. Echo the source identity with the body to prevent adjacent-unit misassociation. A generation fence alone does not distinguish two overlapping invocations within the same generation; a fresh per-invocation nonce is a proposed requirement needing implementation and verification. Test missing, forged, stale and wrong-revision claims, unadmitted reads and writes, and assert no mutation.

For authorized callers, distinguish a target outside the persisted admission from an expired or stale generation with safe outcomes, while refusing both mutations; preserve any policy that hides resource existence. Do not rely on a particular transport status code. Check an unadmitted target in the same source and a previously admitted target after generation change: each yields its declared distinct cause and neither changes storage.

Use bounded work and require strict progress if multiple invocations are needed. Choose grouping only after measuring cost, fidelity and failure recovery on the same workload. A glossary is an unbuilt option if measured vocabulary drift harms retrieval, not a default memory system. Timeout or malformed response leaves the remote result unknown; fence and reconcile committed artifacts before any replay.

## Asynchronous ingestion

If ingestion outlives the request and must survive process failure, record durable intent with stable submission identity, scope, source version and fingerprint before dispatch, or explicitly specify and verify an equivalent recoverable protocol. A message can carry a pointer and fingerprint while durable state records work; avoid expiring bearer URLs in durable messages. Client retry alone cannot recover a dispatch lost after acceptance; a transactional outbox is a proposed option, not a verified fix. Even with an outbox, an object written before the transaction can be orphaned and needs a separate reconciliation policy.

Acknowledge at-least-once delivery only after the disposition and deduplication record commit. Match the same submission key and fingerprint as a duplicate; a reused key with different content is a conflict requiring explicit handling, not an overwrite. Verify the pinned object generation, size and digest and authority at the consumer. Separate permanent validation rejection from transient unavailable storage; retry only as the chosen policy permits. A receipt missing before consumption or a job reference without a job is unresolved, not success or failure. Batch responses report each item's outcome and partial effects.

For an owned asynchronous ingest, propagate a failed dependency to the job owner, which records retryable or terminal failure and requeues or dead-letters only under its declared policy; do not report ingestion complete merely because dispatch succeeded. Inject a dependency failure and inspect the job state, retry decision and serving version. This is separate from a query's caller-visible failure and optional polish fallback; see [retrieval result contract](retrieval-and-grounding.md#result-contract).

If independent status events are needed, persist event intent with the change, deduplicate delivery, validate scope, and apply the correct version and winner atomically with a high-water mark. A later correction may be valid while an old attempt must not overwrite the current source. Monitor conversion errors as well as transport failures: an invalid event at the head of a batch can block later events even when transport retry counters remain unchanged. Process already-stored status before advancing a due stage so a late completion cannot race a needless successor. Publication is not indexing success. Exercise crash before acknowledgement, duplicate key, conflicting fingerprint, out-of-order events, stuck conversion, uncertain publication and deadline expiry.

If the product enables a real ingestion path, save each item’s acceptance and correlation key, resolve its status within the deadline, inspect serving content and verify one authorized lookup for a known marker. A pending receipt, a skipped job or a success report without a readable source fails this acceptance check.

## Deletion and derived state

If withdrawal or deletion is supported, define when serving reads stop, which versions and copies remain, and when physical purge is complete. **Design requirement:** advance a deletion or policy generation and enforce it at commit so an in-flight editor, indexer or derived-state writer cannot resurrect content. Policy updates should reject stale versions; an absolute monotonic register is not automatically compare-and-swap. Delete a shared blob only after no authorized live reference needs it. Distinguish logical deletion, asynchronous physical purge and complete erasure across histories, backups and external caches; do not claim the last from a successful row delete.

If derived overviews or caches exist, invalidate every affected scope transactionally with a mutation. Publish only after checking the current input digest, recipe and generation, and fence a reclaimed worker's late result. Return stale or unavailable rather than an old body. A fallback to a broader scope must be authorized and must not turn a stale narrower result into a fresh one. An overview is navigation, not an exhaustive inventory. Verify the real producer and reader together under their actual scope; a scope mismatch can omit an intended overview; its correction requires verification. Test deletion and scope withdrawal while generation is paused; stale publication is rejected.

## Decision and checks

| Pressure | Option | Check |
|---|---|---|
| Synchronous small source | Direct validation and transactional update | A rejected update leaves the old content intact. |
| Long or crash-prone ingest | Durable intent and host recovery | A lost acknowledgement resolves to the same operation or remains unknown. |
| Concurrent readers require uninterrupted content | Stage and atomic serving pointer | Readers see only an eligible generation; version-qualified reads span calls. |
| Search quality requires an index | Select an index from measured need | Rebuild and recall checks preserve required facts and scope. |
| Deletion can race with writers | Tombstone or generation fence and copy inventory | A paused pre-delete writer cannot restore any covered derivative. |

**Premise:** a PDF or table adapter can discard content. **Symptom:** retrieval misses a fact present in the original. **Cause and evidence status:** extraction can sample rows or omit images; model polish lacks a complete loss oracle. **Rule and reason:** compare the canonical served body to independently checked source facts before tuning search. **Check and expected evidence:** plant a final-row marker and a grouped-header qualifier; both survive or an explicit limitation is returned. **Does not apply when:** the source is already an authoritative structured record with verified complete fields.

**Premise:** a replacement reuses unit identifiers. **Symptom:** old content is used to write metadata on the new generation. **Cause and evidence status:** reference analysis identified unfenced remote reads and stale editor writes as the mechanism. **Rule and reason:** fence both reads and writes by exact admitted version and claim. **Check and expected evidence:** resume an old editor after promotion; every stale access is rejected without a mutation. **Does not apply when:** no separate editor or concurrent generation exists.

## Provider and client deltas

| Concern | Anthropic | OpenAI | Gemini |
|---|---|---|---|
| Optional document rescue | Encoding and fidelity unmeasured here; qualify the exact adapter with scans. | Same; native file support alone does not prove a gateway's encoding works. | Qualify the exact rescue route and failure fallback. |
| Optional vectors | The route is unmeasured; use a separately qualified embedding provider if needed. | Qualify count, order, dimensions, token limits and retries. | A gateway can return one vector for a batch; test cardinality and order on the selected route. |

## Worked example — one implementation under stated premises

Premises: a small team owns a frequently updated handbook and readers need uninterrupted access. Each handbook source has a scope, lifetime ID and revision. A synchronous uploader validates text and writes a staged revision; after content checks, one transaction promotes it. A deletion increments a generation and removes it from serving, while retained history follows the declared policy. No queue, vector index or model editor is needed at this size.
