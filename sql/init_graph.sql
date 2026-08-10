-- Apache AGE extension + base graph setup for the
-- financial holding company internal control system knowledge graph.

CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Single graph holds both the explicit domain model (org/regulation/control/risk/...)
-- and entities/relations auto-extracted from source documents. They are kept
-- distinguishable via the `source` property on nodes/edges (see src/graphdb/schema.py).
SELECT create_graph('internal_control')
WHERE NOT EXISTS (
    SELECT 1 FROM ag_graph WHERE name = 'internal_control'
);

-- Helpful btree indexes on the AG catalog tables backing our label types.
-- AGE stores each label as its own table (ag_catalog.<graph>."<Label>"), so
-- indexes are created per-label after the labels are first used. See
-- scripts/init_indexes.sql, which is idempotent and safe to (re)run after
-- scripts/seed_graph.py has created the labels.
