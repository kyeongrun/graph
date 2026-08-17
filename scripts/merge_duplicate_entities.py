#!/usr/bin/env python3
"""One-off migration: merge RDB entity rows that `resolve_alias` (dictionary
alias map + junk-prefix stripping, see `graphdb.typing.dictionaries`) now
considers the same real-world entity, but were inserted as separate rows
before this fix existed (2026-08-18). Only touches RDB — AGE/OpenSearch
should be reloaded from RDB afterward via
`scripts/run_pipeline.py --reload-from-rdb --truncate` (no need to re-run
the SVO/LLM pipeline, RDB stays the SSOT).

For each entity whose `resolve_alias(name)` differs from its stored name:
- If an entity with (label, resolved_name) already exists: repoint every
  `relation.source_entity_id`/`target_entity_id` referencing the duplicate
  to the canonical entity's id, then delete the duplicate row.
- If no such entity exists yet: just rename the row in place (nothing to
  merge into).

Usage:
    PYTHONPATH=src python scripts/merge_duplicate_entities.py           # dry run, prints what it would do
    PYTHONPATH=src python scripts/merge_duplicate_entities.py --apply   # actually applies changes
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psycopg  # noqa: E402

from graphdb.config import get_rdb_settings  # noqa: E402
from graphdb.typing.dictionaries import resolve_alias  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("merge_duplicate_entities")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="실제로 적용(기본은 dry-run)")
    args = parser.parse_args()

    settings = get_rdb_settings()
    conn = psycopg.connect(settings.dsn)
    cur = conn.cursor()

    cur.execute("SELECT id, label, name FROM entity")
    entities = cur.fetchall()

    # (label, name) -> id, for locating merge targets
    by_label_name: dict[tuple[str, str], str] = {
        (label, name): str(eid) for eid, label, name in entities
    }

    renamed = 0
    merged = 0
    relations_repointed = 0

    for eid, label, name in entities:
        resolved = resolve_alias(name)
        if resolved == name:
            continue

        target_id = by_label_name.get((label, resolved))
        if target_id is None:
            logger.info("RENAME  [%s] %r -> %r (id=%s)", label, name, resolved, eid)
            renamed += 1
            if args.apply:
                cur.execute("UPDATE entity SET name = %s WHERE id = %s", (resolved, eid))
                by_label_name[(label, resolved)] = str(eid)
                by_label_name.pop((label, name), None)
            continue

        if target_id == str(eid):
            continue  # already pointing at itself somehow

        logger.info(
            "MERGE   [%s] %r (id=%s) -> %r (id=%s)", label, name, eid, resolved, target_id
        )
        merged += 1
        if args.apply:
            cur.execute(
                "UPDATE relation SET source_entity_id = %s WHERE source_entity_id = %s",
                (target_id, eid),
            )
            n1 = cur.rowcount
            cur.execute(
                "UPDATE relation SET target_entity_id = %s WHERE target_entity_id = %s",
                (target_id, eid),
            )
            n2 = cur.rowcount
            relations_repointed += n1 + n2
            cur.execute("DELETE FROM entity WHERE id = %s", (eid,))

    if args.apply:
        conn.commit()
        logger.info(
            "적용 완료: rename=%d merge=%d relation FK 재연결=%d건",
            renamed, merged, relations_repointed,
        )
    else:
        logger.info(
            "DRY RUN (변경 없음): rename 대상=%d merge 대상=%d — 실제 적용하려면 --apply",
            renamed, merged,
        )

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
