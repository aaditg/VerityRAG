# Verity TODO

Last updated: 2026-02-18

Use this as the running backlog for items deferred to later phases (especially cloud scaling).

## You Add (Product/Direction)

- [ ] Cloud deployment target and budget guardrails for model serving (latency/cost/SLA).
- [ ] Preferred general-knowledge scope for v1 cloud rollout (math/science/legal/business/etc.).
- [ ] Trust policy for external/general answers vs internal answers (when to abstain).
- [ ] Evaluation target metrics by persona (accuracy, relevance, response length, citation precision).
- [ ] Priority integrations order after Drive (Notion/GitHub/Salesforce/Looker/Slack).
- [ ] Decide response format default by channel/persona: conversational paragraph vs bullet list.

## I Do (Engineering/Implementation)

- [ ] Replace patchwork basic-query handlers with robust cloud-scale general-knowledge path:
  - Route general queries to a dedicated model/index lane.
  - Keep deterministic fast path only for obvious arithmetic.
  - Add strict abstain behavior for low-relevance retrieval.
- [ ] Add offline/CI evaluation harness for correctness + relevance + citation precision.
- [ ] Add source trust tiers and enforce them in retrieval/citation ranking.
- [ ] Add UI toggle for strict relevance mode (aggressive abstain vs best-effort).
- [ ] Add background status polling in UI for `Sync Learnset` jobs.
- [ ] Add structured fact extraction at ingestion to reduce synthesis drift.
- [ ] Add cloud migration task: move Ollama/model serving to managed GPU compute and benchmark throughput.
- [ ] Add monitoring for retrieval misses and wrong-lane routing (general vs internal).

## Notes

- Important: current basic/general correctness is improved, but not yet cloud-grade.
- At cloud scale, general knowledge should be handled as a first-class lane, not incremental pattern patches.
