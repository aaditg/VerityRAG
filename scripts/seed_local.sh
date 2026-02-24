#!/usr/bin/env bash
set -euo pipefail

psql "postgresql://postgres:postgres@localhost:5432/rag" <<'SQL'
INSERT INTO tenants (id, name, created_at)
VALUES ('11111111-1111-1111-1111-111111111111', 'demo-tenant', now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO workspaces (id, tenant_id, name, created_at)
VALUES ('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'demo-workspace', now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO users (id, tenant_id, email, display_name, is_active, created_at)
VALUES ('33333333-3333-3333-3333-333333333333', '11111111-1111-1111-1111-111111111111', 'user@example.com', 'Demo User', true, now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO user_identities (id, user_id, provider, provider_user_id, metadata_json, created_at)
VALUES (
  '44444444-4444-4444-4444-444444444444',
  '33333333-3333-3333-3333-333333333333',
  'google',
  'google-user-1',
  json_build_object('workspace_id', '22222222-2222-2222-2222-222222222222'),
  now()
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO user_identities (id, user_id, provider, provider_user_id, metadata_json, created_at)
VALUES (
  '55555555-5555-5555-5555-555555555555',
  '33333333-3333-3333-3333-333333333333',
  'slack',
  'U123456',
  json_build_object('workspace_id', '22222222-2222-2222-2222-222222222222'),
  now()
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO groups (id, tenant_id, external_group_id, name)
VALUES ('66666666-6666-6666-6666-666666666666', '11111111-1111-1111-1111-111111111111', 'group-sales', 'Sales')
ON CONFLICT (id) DO NOTHING;

INSERT INTO group_memberships (id, group_id, user_id, created_at)
VALUES ('77777777-7777-7777-7777-777777777777', '66666666-6666-6666-6666-666666666666', '33333333-3333-3333-3333-333333333333', now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO personas (id, tenant_id, key, name, description, created_at)
VALUES
('88888888-8888-8888-8888-888888888881', '11111111-1111-1111-1111-111111111111', 'sales', 'Sales', 'Client-safe sales persona', now()),
('88888888-8888-8888-8888-888888888882', '11111111-1111-1111-1111-111111111111', 'exec', 'Executive', 'Executive data persona', now()),
('88888888-8888-8888-8888-888888888883', '11111111-1111-1111-1111-111111111111', 'engineering', 'Engineering', 'Engineering technical persona', now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO sources (id, workspace_id, connector_type, name, config_json, status, created_at)
VALUES (
  '99999999-9999-9999-9999-999999999999',
  '22222222-2222-2222-2222-222222222222',
  'upload',
  'Q1 Notes',
  json_build_object(
    'external_id', 'seed-q1-notes',
    'title', 'Q1 Enterprise Notes',
    'canonical_url', 'https://example.local/q1',
    'text', '# Pipeline\nACME expansion is strong in enterprise segment.\n# Risks\nSecurity review extends deal cycles.',
    'acl', json_build_array(json_build_object('principal_type', 'public', 'principal_id', 'all'))
  ),
  'active',
  now()
)
ON CONFLICT (id) DO NOTHING;
SQL

echo "Seed complete."
