#!/usr/bin/env python3
"""Load one or more domain YAML files into the AGE graph.

Usage:
    python scripts/seed_graph.py data/domain/sample_internal_control.yaml
    python scripts/seed_graph.py data/domain/*.yaml
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from graphdb.connection import GraphConnection  # noqa: E402
from graphdb.ingest.domain_loader import load_domain_file  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def main(paths: list[Path]) -> int:
    conn = GraphConnection()
    await conn.open()
    exit_code = 0
    try:
        for path in paths:
            stats = await load_domain_file(conn, path)
            if stats.errors:
                exit_code = 1
                for err in stats.errors:
                    logging.error("%s: %s", path.name, err)
    finally:
        await conn.close()
    return exit_code


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    file_paths = [Path(p) for p in sys.argv[1:]]
    raise SystemExit(asyncio.run(main(file_paths)))
