# Architecture

## System Overview
- Slack-first interaction layer (`/slack/commands`, `/slack/events`, `/slack/interactive`) plus API entrypoint (`/ask`).
- Identity anchored in Google Workspace. Slack identities map to Google identities through `user_identities`.
- Data plane:
  - Postgres + pgvector for relational metadata + embeddings.
  - Redis for hot answer/tool cache.
  - SQS for ingestion/sync jobs.
  - S3 for ingestion artifacts (normalized snapshots, optional parse traces).
- Compute:
  - FastAPI API service on ECS Fargate behind ALB.
  - Worker service consuming SQS.

## Data Model
Core entities implemented:
- Tenancy: `tenants`, `workspaces`
- Identity: `users`, `user_identities`, `groups`, `group_memberships`
- Persona policy: `personas`, `persona_rules`, `persona_defaults`
- Content: `sources`, `documents`, `document_tags`, `document_acl`, `chunks`, `embeddings`, `chunk_tags`
- Connectors: `connectors`, `connector_accounts`, `connector_credentials` (Secrets Manager ARN only)
- Sync control: `source_cursors`, `sync_jobs`
- Cost control: `tool_cache`, `answer_cache`
- Governance: `audit_logs`, `feedback`

## ACL Enforcement (Retrieval-Time)
- Retrieval query performs ACL join/exists predicates before ranking result set.
- Allowed principal matches include:
  - user UUID
  - user email
  - group membership
  - public marker
- No post-retrieval filtering. Unauthorized chunks are excluded from vector candidate set.

## Caching Strategy
- `tool_cache`:
  - Primary: Redis (key `tool:<cache_key>`, TTL by tool policy)
  - Fallback: Postgres `tool_cache` table with `expires_at`
- `answer_cache`:
  - Key: `sha256(normalized_query + persona + context_hash)`
  - Context hash derived from retrieved chunk text to invalidate automatically when retrieval context changes
  - If cache hit, no LLM/tool call

## Cost Controller
- Retrieval before generation always.
- Skip LLM on answer cache hit.
- High-confidence retrieval can return `citations_only` mode without LLM.
- External tools should check `tool_cache` first.
- Ingestion embeds only changed chunks (`text_hash` compare per chunk position).

## Connector Security
- Connector credentials are represented by Secrets Manager ARN in `connector_credentials.secret_arn`.
- OAuth callbacks should exchange code server-side then write token payload to Secrets Manager.
- Current MVP has TODO hooks where provider secrets should be persisted and rotated.

## AWS Deployment Layout
- VPC + subnets
- ALB fronting ECS service
- ECS Fargate services for API and worker
- RDS Postgres (with pgvector extension enabled by migration)
- ElastiCache Redis
- SQS sync queue
- S3 artifacts bucket
- Secrets Manager for OAuth refresh tokens and API credentials
- IAM task role should include least-privilege access to SQS/S3/Secrets Manager.

## Extending Personas
1. Insert row in `personas`.
2. Add `persona_rules` (retrieval filters, tool allowlist, output template, safety rules, cache TTL).
3. Optionally add defaults in `persona_defaults`.
4. Update policy engine mapping if keeping in-code defaults.

## Extending Connectors
1. Add connector type to schema enum and migration.
2. Add setup endpoint under `/connectors/...`.
3. Add sync job type and worker handler.
4. Implement parser -> normalized text -> chunk/embedding upsert.
5. Add retrieval/tool policy integration per persona.
