#!/usr/bin/env python3
"""5단계 진입점: data/laws/raw/**/*.md 전체(60개 파일)를 orchestration
pipeline(law_structure + svo + edge_type_mapping + entity typing)에 돌려
RDB/AGE/OpenSearch 3-store에 적재한다. CLAUDE.md "5단계 > 실행 체크리스트"
"완료 조건" 참고.

Usage:
    PYTHONPATH=src python scripts/run_pipeline.py               # 전체 60개
    PYTHONPATH=src python scripts/run_pipeline.py --limit 3      # 앞 3개만(디버그)
    PYTHONPATH=src python scripts/run_pipeline.py --truncate     # 재적재 전 3-store 비우기
    PYTHONPATH=src python scripts/run_pipeline.py --skip-age --skip-opensearch  # RDB만
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    # psycopg's async pool can't run on Windows' default ProactorEventLoop
    # (needs a selector-based loop) — see psycopg docs "Async support".
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from graphdb.ingest.age_loader import load_to_age, truncate_age  # noqa: E402
from graphdb.ingest.opensearch_loader import load_to_opensearch, truncate_opensearch  # noqa: E402
from graphdb.ingest.rdb_loader import load_to_rdb, read_rdb_load_result, truncate_rdb  # noqa: E402
from graphdb.pipeline import load_documents, run_pipeline  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_pipeline")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="처리할 문서 파일 수 제한(디버그용)")
    parser.add_argument("--truncate", action="store_true", help="적재 전 RDB/AGE/OpenSearch 기존 데이터 삭제")
    parser.add_argument("--skip-age", action="store_true")
    parser.add_argument("--skip-opensearch", action="store_true")
    parser.add_argument("--skip-rdb", action="store_true", help="RDB 적재 건너뛰기(디버그/파이프라인만 검증할 때)")
    parser.add_argument(
        "--reload-from-rdb",
        action="store_true",
        help="파이프라인/LLM 재실행 없이 기존 RDB 데이터로 AGE/OpenSearch만 다시 적재(--truncate와 함께 사용)",
    )
    args = parser.parse_args()

    if args.reload_from_rdb:
        if args.truncate:
            if not args.skip_age:
                logger.info("--truncate: AGE 비우는 중")
                asyncio.run(truncate_age())
            if not args.skip_opensearch:
                logger.info("--truncate: OpenSearch 인덱스 삭제 중")
                truncate_opensearch()
        rdb_result = read_rdb_load_result()
        logger.info(
            "RDB에서 읽음: document=%d entity=%d relation=%d",
            len(rdb_result.document_ids),
            len(rdb_result.entities),
            len(rdb_result.relations),
        )
        if not args.skip_age:
            asyncio.run(load_to_age(rdb_result))
        if not args.skip_opensearch:
            load_to_opensearch(rdb_result)
        logger.info("--reload-from-rdb 적재 완료")
        return 0

    documents = load_documents()
    logger.info("문서 %d개 발견 (data/laws/manifest.json 기준)", len(documents))
    if args.limit is not None:
        documents = documents[: args.limit]
        logger.info("--limit %d 적용, %d개 문서만 처리", args.limit, len(documents))

    t0 = time.monotonic()
    result = run_pipeline(documents)
    t1 = time.monotonic()

    logger.info("파이프라인 완료 (%.1fs)", t1 - t0)
    logger.info("=== extraction_method별 relation 건수 ===")
    method_counts: dict[str, int] = {}
    for rel in result.relations:
        method_counts[rel.extraction_method] = method_counts.get(rel.extraction_method, 0) + 1
    for method, count in sorted(method_counts.items(), key=lambda kv: -kv[1]):
        logger.info("  %-20s %6d", method, count)
    logger.info("=== 기타 통계 ===")
    for key, value in sorted(result.stats.items()):
        logger.info("  %-40s %6d", key, value)

    if args.skip_rdb:
        logger.info("--skip-rdb 지정, RDB/AGE/OpenSearch 적재 생략하고 종료")
        return 0

    if args.truncate:
        logger.info("--truncate: RDB 비우는 중")
        truncate_rdb()
        if not args.skip_age:
            logger.info("--truncate: AGE 비우는 중")
            asyncio.run(truncate_age())
        if not args.skip_opensearch:
            logger.info("--truncate: OpenSearch 인덱스 삭제 중")
            truncate_opensearch()

    rdb_result = load_to_rdb(result)
    logger.info(
        "RDB 적재 완료: document=%d entity=%d relation=%d",
        len(rdb_result.document_ids),
        len(rdb_result.entities),
        len(rdb_result.relations),
    )

    if not args.skip_age:
        asyncio.run(load_to_age(rdb_result))

    if not args.skip_opensearch:
        load_to_opensearch(rdb_result)

    logger.info("5단계 파이프라인 적재 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
