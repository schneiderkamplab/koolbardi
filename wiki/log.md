# Knowledge Bundle Update Log

## 2026-09-04

- Completed the controlled campaign with 535,930 Danish and 528,926 English
  audited conversations and 2.313B native rendered tokens. Enabled
  `retain_surplus` so finalization preserves every qualifying row while still
  enforcing all complexity-by-length minima.
- Recorded the targeted English near-limit replenishment, final queue state,
  immutable source checksum, and publication to two language-specific DFM11
  Hugging Face datasets.

## 2026-09-03

- Superseded the temporary 1.1M Danish cap with an exact balanced release
  target of 500K Danish plus 500K English rows. Added restart-safe response and
  audit selectors, a 5% pre-audit buffer, exact complexity/length finalization,
  target-shortfall refusal, and stable-superset extension semantics.
- Capped Danish response generation at a projected 1.11M complete rows by
  atomically holding 1,862 surplus shards and deterministically selecting
  1,502 pending shards across underrepresented complexity/length cells. The
  selected pool retains all 136 topics and 20 modes with near-perfect entropy;
  held shards remain available for post-audit replenishment.
- Switched both model-judge phases to vLLM/OpenAI strict JSON Schema outputs,
  eliminating prompt-only malformed-JSON retries, and changed queue advancement
  from thousands of synchronous SQLite commits to one atomic bulk transaction.
- Verified the restarted path on a fresh 100-row production sample: all rows
  passed exact 4K-aware structural checks, and the judge accepted 100/100
  conversations and 200/200 assistant turns.
- A second live sample focused on 100 recent long-band, four-exchange rows;
  all 400 assistant turns and all conversations passed, with median rendered
  length 2,831 tokens and no capped generation.
- Removed the 2% response partial-failure cutoff after it discarded 18 shards
  that were still 95--98% complete. Every complete row is now persisted and
  unresolved rows are recorded separately; only all-row failure retries a
  whole shard.
- Paused response generation at atomic shard boundaries, archived all 406
  pre-fix response shards and 59 audits, and implemented finish-reason-aware
  user/assistant retries with Danish-calibrated word budgets and deterministic
  endpoint checks. A same-row pilot emitted 99/100 complete medium/long rows
  and the judge accepted 98; an extreme-band pilot emitted and accepted 25/25
  short and 23/25 near-limit rows, with near-limit lengths of 3,159--3,911.
  Unresolved rows are recorded rather than emitted incompletely.
- Audited 100 instruction-gated Danish medium/long conversations. Although
  prompts, language, relevance, and diversity were strong, 81 contained a turn
  that hit its exact token cap and ended incompletely; the model judge missed
  39. Danish uses a median 1.916 Gemma tokens/word, so the existing 0.60 words
  per token-budget instruction requests about 1.15 times available capacity.
  Recorded finish-reason capture, retry, language-specific budget, and
  deterministic truncation rejection as required corrections.

## 2026-09-02

- Changed repeated malformed instruction-judge JSON from a whole-shard failure
  into an explicit rejection of only the unjudgeable row. This followed one
  medium Danish shard exhausting four shard attempts because one of 511 rows
  exhausted every parse retry; the other 510 verdicts must be retained.
- Raised the live instruction-audit saturation trial from eight to twelve
  workers by adding four atomic queue consumers without interrupting active
  shards. Tightened the completion handoff to wait for all audit claims before
  invoking downstream phases. Twelve workers sustained 38.0 shards/minute over
  two minutes, 9.8% above eight workers, but drove KV occupancy as high as 99%,
  queued roughly 580 requests/server at the peak, and caused about 676--703
  preemptions/GPU over the interval. Keep twelve for this phase; do not raise it.
- Raised live instruction-audit fan-out from four to eight workers after four
  synchronized 512-row waves left periodic one-second GPU gaps and used only
  about 48% of KV cache. Added an idempotent completion handoff because the
  original coordinator tracks only its initially launched worker PIDs.
  The first 113-second eight-worker interval sustained 34.6 shards/minute,
  about 34% faster than 25.8 with four workers. A 90-second utilization sample
  had no all-GPU zero trough; live KV use was 50--61% with no waiting requests.
- Added an optional pre-response instruction-audit phase and enabled it for the
  controlled million-row campaign. Deterministic checks plus the pinned Gemma
  judge now gate language, topic/mode adherence, realism, answerability,
  persona coherence, usefulness, and safety before expensive responses. Added
  an atomic live-queue guard and automatic old-to-new coordinator handoff.
- Verified that the live coordinator entered instruction audit directly and
  retired the redundant fallback watcher. Its first 702,808 verdicts accepted
  99.921% of requests; 30-minute throughput was 25.8 shards/minute.
- Added bounded per-row retries and partial-shard preservation for rare
  persistent instruction length caps, after two 512-row production shards each
  failed because one otherwise isolated row remained capped.
- Rolled the partial-shard behavior into the live campaign at an atomic shard
  boundary. A brief GPU-idle interval was the intentional worker drain plus the
  idempotent SQLite initialization pass; all 24 workers then resumed and the
  three affected shard rows returned to the queue.
- Implemented and launched the controlled million-row restart with 136 topics,
  20 modes, all 1M Nemotron-USA personas, and all 5K Danish personas. Sampling
  remains temperature 1.0/top-p 1.0. The 1% gate represented every topic and
  mode with normalized entropy above 0.99999 and no 100-row sample pair above
  0.75 TF-IDF cosine similarity. Added staged automatic full-campaign resume.
- Recommended restarting the million campaign with controlled diversity while
  preserving current artifacts: only about 3.4% of response shards were done,
  so continuing would spend nearly all expensive response compute on prompts
  already known to exhibit severe topic collapse. No process was stopped.
- Proposed deterministic, quota-balanced topic/persona/interaction-mode
  conditioning for future generations, using Nemotron USA personas for English
  and the existing Danish persona source. Recorded compatibility, metadata,
  copied-input, privacy, and corpus-audit requirements.
- Extended the topic-diversity audit to 100 requests per language. Travel made
  up 57% of English and 96% of Danish requests; 45% of all sampled Danish rows
  concerned Copenhagen. Surface near-duplicate rates remained low, showing
  semantic template collapse rather than simple verbatim duplication.
- Recorded a deterministic 20-conversation response sample. Content was usually
  coherent, but only 4/10 Danish versus 9/10 English conversations were
  structurally complete, and topic diversity was poor. Identified discarded
  API finish reasons and missing corpus-level diversity checks as follow-up.
- Recorded that higher temperature is only a secondary diversity lever because
  initial generation already uses temperature 1.0/top-p 1.0; future campaigns
  require explicit topic/archetype allocation and semantic deduplication.
- Created Koolbardi's own OKF v0.2 bundle and local validation command.
- Recorded the architecture, exact 4K data contract, campaign and recovery
  runbooks, Gemma 4 A4B serving constraints, concurrency measurements, and the
  active bilingual million-row campaign.
- Recorded the measured replacement of 4,096-way initial generation with the
  equally productive, preemption-free 3,072-way configuration.
