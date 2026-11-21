# Scenario evaluation and experiments

## 1. Premise and boundary

Read this leaf only when a behavioral, quality, latency or cost decision requires evidence across cases, or when a deterministic check alone cannot answer the question. Start with saved outputs and the smallest decision-bearing scenario, then add a harness or paid model calls only when needed and authorized. A scenario is an experiment design, not evidence that a runner already exists.

A proposed runner, experiment ledger or standing regression set is a design, not an existing artifact; identify which actually exist before claiming execution or regression coverage. These extensions remain proposed until their implementation is verified.

## 2. Scenario and artifact contract

Freeze each scenario's objective, actual model and route, effective configuration and version, ordered history, initial state, tools and their declarations, scripted inputs, stub results and errors, expected transitions, stressors, observable outcomes and stop conditions. For each arm and repetition reset history, state, fake stores, clock and stub cursors. Apply the same eligibility, transition and result-delivery semantics as the production path, or identify and validate an equivalent adapter. Capture ordered events with cell, turn, call and tool identities, before/after state, outcome and evidence references. An interrupted or missing cell is not a completed empty answer. When confirmation is intended to transfer to a baseline distribution, record and compare class proportions before freezing the new corpus; label an intentional change in mixture because it changes the question.

Test the data in the form the user sees it, including realistic long histories, payloads, languages and conditional facts when they affect the decision. If a feature consumes a model-produced intermediate, evaluate three saved stages: the producer against gold, the feature with gold input, and the feature with actual producer output. Check artifacts at every stage for completeness, provenance and state transitions before attributing failure or gain to the next stage. If delegation exists, isolate the child and then test through the parent to locate routing or synthesis loss. A synthetic checkpoint demonstrates behavior only under the injected checkpoint; separately observe natural triggering before claiming the runtime reaches it. A small screen with multiple bundled changes cannot isolate extraction quality.

Use deterministic checks first: schema validity, ordering, exact state transitions, operation counts, required evidence and known fact presence. Validate the extractor and counter on saved outputs with known answers, including negatives and ambiguous cases; deterministic code can still be wrong. For semantic judgments without a reliable counter, freeze a rubric with criteria, evidence quotations and an undecidable state, and aggregate criterion results deterministically. Validate a model grader on saved outputs against human adjudication before any paid run; inspect outliers, hard-gate cases and disagreements in their original artifacts. A scanner warning is evidence to adjudicate, while a proven recorder, accounting or safety failure follows the frozen stop rule.

If an ordering check depends on question or semantic boundaries absent from the input structure, first annotate those boundaries with a validated structured or semantic method, then apply the deterministic ordering oracle. Check ambiguous and counterexample boundaries; determinism after incorrect annotation does not establish correctness. For any candidate comparison, prove the candidate path was exercised and include a negative control that fails when the candidate is bypassed; otherwise the comparison is invalid.

A work-practice analogy is preregistration: human investigators fix outcomes and stopping rules before seeing results to reduce post-hoc choice. Stochastic model outputs have the same analytical risk; unlike a person, a captured request may be replayed, but replay does not make a later model explanation proof of its earlier cause.

## 3. Decision table

| Need | Minimal mechanism | Extension when justified |
|---|---|---|
| One observable regression | Saved artifact and manually verified deterministic oracle | Versioned regression set when the case recurs. |
| Multi-turn behavior | Scripted scenario with production-equivalent state updates | Simulator only if needed, with frozen route, instructions, cap and termination. |
| Semantic quality | Human adjudication of saved outputs | Model grader with validated rubric and unresolved state when volume justifies it. |
| Candidate comparison | Paired cases, fixed inputs and explicit uncertainty | Repetitions and held-out set when noise and advancement decision warrant them. |
| Repeated evaluations | Small runner, recorder and manifest | Durable checkpoints and attempt ledger when interruption or resumption matters. |
| Offline claim | Mechanically enforce a no-network boundary | A limited socket guard only with explicit limitations and tests across processes and transports. |

A validated deterministic check is cheap, fast and repeatable for an exact condition, but can repeatedly certify the wrong interpretation; human adjudication handles ambiguity at reviewer-time cost, while model grading scales volume at extra calls, latency and grader error. This is a recorded design judgment, not a measured ranking of graders. Begin with saved outputs and checks whose positives and counterexamples have known answers, use human review for undecidable meaning, and add a calibrated semantic grader only when the decision's volume justifies its cost; preserve an unresolved state instead of forcing certainty.

When paid evaluation is needed, select stages for the decision: an authorized wire smoke establishes adapter and route, inexpensive exploration can discard weak options, and acceptance uses the routes and roles relevant to the intended deployment. Skip stages that cannot affect the decision; a cheap-route result alone cannot establish acceptance on a different route. Measure prompt simplification on the actual task and model, since a scoped result does not establish a universal prompt rule.

A small decision-bearing screen can reject an unsuitable option quickly with limited spend, but cannot establish population reliability, resolve an unmeasured noise band or qualify a different route. Representative paired cases, justified repetitions and an independently sealed set buy stronger acceptance evidence at call, annotation, reset and maintenance cost. This is a recorded design judgment: choose the smallest check that can change the decision, then expand only for the remaining uncertainty and required acceptance; do not use exposed tuning cases as a fresh seal or relax a hard condition to make the cheap screen sufficient.

## 4. Freeze policy and protect validity

Before any model call, bind the question, decisions, arms, case matrix, fixtures, implementation, scorer and versions into a manifest. Define each metric's numerator, denominator, units, missing-data handling, aggregation and uncertainty; necessary conditions; hard constraints; noise estimation or predeclared tolerance; ordered classification; stop conditions; call and spend limits; advancement threshold; and what happens on a miss or trade-off. A necessary-condition failure invalidates dependent measurements, and a hard-constraint violation fails on its own regardless of rate. Measure noise from appropriate repeated reference runs or declare a justified rule in advance; small pilot counts remain descriptive.

If a capability is explicitly best-effort across tiers, the owner may propose a strong-route acceptance gate and separately defined smaller-route floors and provider priorities; freeze the numerical floors, floor-only routes, comparison against capability-off and priority rationale before observations. This is a proposed policy, not a verified implementation or universal ranking. Diagnose a miss on any tier, including the strongest route, against prompt conflict, fixture or scorer validity, provider behavior and task difficulty; classify it as a potentially general prompt issue, capability ceiling, scorer noise or unresolved cause before deciding a remedy; do not tune to evaluation labels. Safety, security and other declared hard constraints apply to every route and cannot be waived by a tier floor. Test floor misses and hard violations independently.

If statistical bounds are used, state and assess their independence and fixed-distribution assumptions; adaptive turns in one conversation can be correlated and an oracle bound is not a system bound. Use a justified unit of independence or a method accounting for correlation, otherwise report the limitation and avoid a misleading bound.

Before approving a paid experiment budget, re-price every actual model and route and every paid component, including cache writes, storage, graders and retries, against effective independent price evidence; bound unresolved liability. Stale or missing rates make the budget uncertain rather than zero.

Define cell validity and denominator before execution. An invalid fixture, missing capture, route error, missing result or stop-censored cell does not disappear from the declared matrix. A legitimate autonomous limit stop may be a valid behavioral failure if the frozen policy says so. Distinguish invalid or undecidable from an observed failure, and do not compare a censored arm with a completed arm as if both had full coverage.

Complete the approved matrix despite ordinary isolated failures unless the predeclared stop function fires. Stop on exhausted call or spend authority, any rate limit, user stop, safety or authority failure, failed necessary condition or hard constraint, a verified fault invalidating remaining measurements, or a declared sequential rule. Record each failure as verified defect, supported noise or undetermined. Do not change the tolerance after seeing results.

If paid calls are authorized, mechanically count every real call including graders, retries, preflights and auxiliary calls. Admit only when committed spend plus unresolved and in-flight maximum liability plus the next call's bound fits the approved cap. A reservation without a proven no-send decision remains potentially dispatched after a crash. Reconcile before resending, and stop for manual reconciliation if neither outcome nor verified idempotent replay can be established. Checkpoint response, events, state, tool effects and cursors before advancing; retain void or censored evidence and spend.

If the run is offline, use a tested deny-network boundary inherited by child processes, including loopback, before imports; a patch of one HTTP library does not prove process-wide isolation. If only a socket-level fallback exists, state its limits and cover allowed child paths. These are proposed controls whose implementation must be verified.

If an offline fake endpoint is used, verify the route in the executing process and observe the first fake receipt before continuing; configuration at the caller alone may be overwritten downstream. A fake receipt does not replace the inherited process-wide network denial; a missing or unexpected receipt stops the affected run.

## 5. Comparative verdict and lessons

Before labels, group each arm's failures by kind and observed user consequence; state sample-level gains and losses together and label inferred consequences. Against the frozen comparison, classify enhancement, trade-off, regression or undetermined; preserve a verified defect even if its rate is uncertain. Separately report pass or fail against the advancement threshold. Keep an enhancement that misses threshold as a checkpoint; use it as a working reference only within authorized optimization, retaining the original for cumulative comparison. Reject hard-constraint violations and regressions; settle a trade-off under the declared policy or the owner's reserved decision. A result grants no spend or release authority. For undetermined results, identify the cheapest discriminating check from saved evidence first and stop at the authorized boundary.

Report each partial gate and its evidence separately from owner interpretation, route qualification and actual rollout proof; a partial result or configured choice does not prove acceptance or activation. Compare latency, resource savings and factual loss separately on the same relevant workload; report missing measurements.

**Premise:** a scenario spans multiple turns. **Symptom:** a candidate appears to repeat a state-writing action unnecessarily. **Cause and evidence status:** a recorded fixture failed to apply the state change the runtime would have applied. **Rule and reason:** evolve state after each accepted result so the next call sees the same state as production. **Check and expected evidence:** compare event order and before/after state on saved outlier transcripts; a static fixture fails. **Does not apply when:** the production path truly does not mutate that state.

**Premise:** a semantic grader assigns low quality. **Symptom:** a correct answer receives a failing score. **Cause and evidence status:** a recorded scorer was brittle to answer formatting; deterministic output did not make its interpretation correct. **Rule and reason:** validate the scorer and inspect each decisive cell before using its score. **Check and expected evidence:** saved paraphrases, negatives and human labels agree or are marked undecidable. **Does not apply when:** an exact format is itself the declared requirement.

**Premise:** a selector saves tokens. **Symptom:** the final answer loses a conditional qualification. **Cause and evidence status:** recorded experiments found repeated loss of the same fragile fact class; character reduction did not prove token savings or answer fidelity. **Rule and reason:** measure end-user outcomes and qualifiers alongside resource savings, and stop repeatedly tuning a failing selector when the alternative better serves the goal. **Check and expected evidence:** seeded conditional facts survive in the delivered answer under the frozen rule. **Does not apply when:** the selected input cannot contain such facts.

## 6. Provider and client deltas

| Aspect | Anthropic | OpenAI | Gemini |
|---|---|---|---|
| Cache experiment | Qualify minimum prefix and usage fields for the actual model and route. | Qualify gateway adaptation and automatic-cache behavior for the actual route. | Qualify explicit versus implicit cache path; evidence from one route does not establish another. |
| Evaluation request | Validate provider-specific fields after adaptation. | Validate tool and reasoning settings for the selected model. | Record thinking settings and output bounds; compare estimates with saved usage. |

Missing counters, unsupported fields and a rejected replay make the affected comparison unmeasured. Do not infer provider-wide behavior from a single route.

If testing cache or route behavior with synthetic content, use realistic benign filler and classify a provider refusal as a non-answer, not successful task behavior; a refusal can still incur cache or call cost. Compare estimated counters to provider-reported final usage for each actual route, retain measured uncertainty and mark missing evidence unmeasured. A single route or refusal cannot establish provider-wide behavior.

## 7. Checks and worked example

- **Always:** read the frozen matrix and saved input/output artifacts as the recipient would; validate counter extraction before grading. A failing necessary condition invalidates its dependent result.
- **If semantic grading is needed:** validate rubric and grader on saved positive, negative, paraphrase and ambiguous examples before a paid call; preserve disagreements for adjudication.
- **If an experiment has multiple stages:** verify producer output, gold-input feature output and real-input feature output separately; a missing intermediate cannot be converted to a downstream quality score.
- **If evaluating a change to a live boundary:** prove the actual serving revision and configuration, then exercise the relevant surface and both directions of any isolation contract under separate authorization. A replay or unit check does not prove deployment.
- **If comparing a candidate:** report per-kind failures, user consequences, sample gains and losses, two verdict axes, unresolved evidence and the frozen gate result. These are checks to perform, not results already obtained.

**Worked example — one implementation under stated premises.** A team tests whether a summarizer retains conditional eligibility while reducing input size. It freezes paired documents and a no-loss hard constraint, verifies each extracted condition on saved outputs with deterministic checks and human adjudication for paraphrases, and validates its semantic grader on those saved artifacts before any authorized paid run. One candidate saves tokens but drops a condition; it fails the hard constraint regardless of its average saving. An enhancement below the advancement threshold remains a checkpoint without permission to ship or spend more.

## 8. Calibration, sealing and recovery detail

If a held-out set supports an advancement decision, tune only on calibration data. Freeze a candidate before its sealed run; after a sealed failure, its gate remains failed. A candidate changed using exposed failures needs a fresh independently authored sealed set, because the exposed set has become calibration data. Counterbalance arm order where possible, or label order confounding; an unqualified two-repetition result is descriptive.

If a checkpointed scenario has mutable tool state, bind the saved result, graph state, local fake-store contents, logical clock, result carrier, applied-transition identities and stub cursors to the same durable checkpoint. For an authorized external effect, persist its intent and stable operation identity before dispatch and reconcile the effect owner's receipt before advancing. If the owner cannot establish the outcome and idempotent replay is not verified, mark the cell unknown and stop dependent measurements. Exercise crashes before dispatch, after acceptance and after a tool transition before checkpoint.

If a detector supplies advisory hints and the agent retains the decision, freeze appropriate precision, positive coverage and consumer harm measures rather than imposing an arbitrary zero-error threshold. If the hint can itself exercise authority or disclose protected information, apply the relevant hard trust constraint instead.

For an ordered comparison, first invalidate measurements whose necessary conditions failed and record any hard-constraint violation. Next classify inadequate coverage or uncertainty across the decision boundary as undetermined; classify supported target gain with a protected-metric loss as a trade-off, supported target loss as regression, and supported gain with constraints met and no protected loss as enhancement. Otherwise report no demonstrated change under the declared policy. A separate advancement result applies its frozen threshold.

If an open design requires independent alternatives, freeze their separate frames before exposing either to the other, then reconcile them with evidence; independent agreement alone does not prove a correct frame. Bound review to properties that can change the decision and avoid numerical stop criteria that lack a basis for the tested artifact. When a feature's inputs were exposed to tuning, retain their labels as calibration evidence, not as a fresh seal.
