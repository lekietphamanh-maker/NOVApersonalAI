# Erasure and forget

Read this leaf only when sensitive data must be erased or forgotten while durable copies, active work, external effects or recoverable writers may exist. [Sensitive data lifecycle](sensitive-data-lifecycle.md) owns the inventory, minimization, retention and provider-retention choices that determine this leaf’s deletion scope; [protected references and admission](protected-references-and-admission.md) covers the protected mappings and reference authorization that deletion affects.

## 1. Interface and failure contract

Receive a trusted deletion request and canonical subject plus alias set; return complete only when each covered store and writer has reached the promised state. Return incomplete with recoverable progress if a covered store, writer or effect cannot be reconciled. Keep any already-exported or external copies and retained audit records explicit in the exposure inventory. A process or job cancellation is not evidence that an already-dispatched remote effect stopped.

## 2. Erasure and forget fences

If jobs were queued before an identity merge, retain the identity captured at admission and resolve it against the current canonical identity and erasure generation before any effect; include captured aliases in the forget scope. A stale job must not recreate erased data or act for a different owner. Pause a queued job across merge and erasure, then resume it and check both the effect and the fence; unavailable resolution or fencing leaves the job incomplete.

**If deletion is promised**, identify the trusted entrypoint and canonical subject plus aliases, enumerate every in-scope writer and copy, and persist the deletion operation and its progress where interruption can occur. Fence new admission and commit paths; register or otherwise account for in-flight writers before checking the fence, then establish quiescence, stop active work, erase or scrub each covered store and derived artifact, and acknowledge only after the stated coverage is verified. Writers and recovered checkpoints must check the current deletion generation at commit so stale work cannot recreate erased data. Retrying a partially completed deletion must converge; an unavailable store, orphan registration, expired fence, unresolved remote operation or unproven stopped writer is incomplete, not success. A missing heartbeat alone does not prove an in-flight transaction stopped. The host owns scheduling and recovery; the privacy owner defines the subject fence and deletion receipt.

**Design requirement — durable forget coordination:** when a process, shared store or fence may fail before quiescence is established, keep deletion state and fence ownership recoverable until all writers are proven stopped or fenced at their commit owners. This proposed requirement is not evidence that the selected implementation satisfies it. Pause a writer past lease expiry, interrupt deletion and restart the coordinator; acknowledgement fails if the writer can later commit or the fence disappears before recovery. Include direct writers outside any worker registry.

Declare exclusions for backups, provider retention, external exports, traces, accounting and client copies, and specify their separate expiry, deletion or inability to recall. A tombstone or audit record may remain linkable and must be disclosed. A subject's erase must not delete another subject's data; a repeated erase must preserve the erased state, not necessarily report zero internal updates.

## 3. Causal lesson

**Premise:** a deletion overlaps a slow writer. **Symptom:** deleted data reappears after acknowledgement. **Cause and evidence status:** expiry-based registration pruning can precede completion of an already-started insert; the target interleaving and distributed quiescence require verification. **Rule and reason:** do not infer stopped writes from lease expiry; fence at commit and retain an incomplete state until quiescence is proven. **Check and expected evidence:** delay a write beyond its lease, erase and resume it; the write is rejected or acknowledgement remains incomplete. **Does not apply when:** no concurrent or recoverable writer can exist and that constraint is enforced.

## 4. Build, debug and optimize checks

- **If erasure is promised:** seed all declared stores and aliases with synthetic data, retain identities needed to inspect tombstones and confirm other subjects remain usable, race direct and registered writers, interrupt handoffs, fail a downstream erase, retry, test fence expiry and recovery, and inspect each store plus retained markers, including ciphertext and lookup-material removal where a vault is used. Missing caller wiring, untracked writers or unreachable stores make the relevant guarantee incomplete.

- **If identity merge spans commits:** interrupt after the mapping move and before identity completion, fail the first retry, then attempt a different target. The original target remains pinned, the conflicting target is refused, and a same-target retry can converge; an untracked split-store state fails.
- **If a bulk deletion tool is used:** rehearse on disposable representative storage with no production credentials; check refusal guards, a non-mutating dry run, a deliberately omitted step that must fail, retained data hashes and a repeat that makes no further changes. A passing sequential rehearsal does not prove concurrent writer quiescence.

## 5. Worked example — one implementation under stated premises

Premises: a persistent assistant has concurrent jobs, subject-scoped history and a separate reference mapping; a user can request erasure. The deletion coordinator records an operation, blocks new subject writes and fences commit owners, waits for or stops existing work, erases covered history and mappings, and checks all receipts. A writer delayed beyond its lease cannot commit under the old generation. If a provider copy is outside the promise or a covered store is unreachable, the response identifies that limitation and reports incomplete for the covered store.
