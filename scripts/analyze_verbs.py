#!/usr/bin/env python3
"""Step 1: data/laws/raw/**/*.md 전체에 Kiwi 형태소분석을 돌려 동사(구)
빈도를 집계한다. 결과는 2단계(동사구 그룹핑)에서 사람이 검토할 입력이다.

Usage:
    python scripts/analyze_verbs.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from graphdb.nlp.morphology import add_domain_words, analyze_corpus  # noqa: E402

RAW_DIR = ROOT / "data" / "laws" / "raw"
DICT_FILE = ROOT / "data" / "laws" / "domain_dictionary.tsv"
OUT_VERBS = ROOT / "data" / "laws" / "verb_phrase_frequency.json"
OUT_MODALS = ROOT / "data" / "laws" / "modal_candidate_frequency.json"


def load_domain_dictionary(path: Path) -> list[tuple[str, str]]:
    words = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            words.append((row["form"], row["tag"]))
    return words


def main() -> int:
    add_domain_words(load_domain_dictionary(DICT_FILE))

    md_files = sorted(RAW_DIR.glob("*/*.md"))
    if not md_files:
        print(f"'{RAW_DIR}' 에 md 파일이 없습니다. 먼저 scripts/fetch_laws.py 를 실행하세요.", file=sys.stderr)
        return 1

    stats = analyze_corpus(md_files)

    OUT_VERBS.write_text(
        json.dumps(stats.verb_phrase_counts.most_common(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    OUT_MODALS.write_text(
        json.dumps(stats.modal_candidate_counts.most_common(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"파일 {stats.files_processed}개 분석 완료")
    print(f"고유 동사구: {len(stats.verb_phrase_counts)}개 (총 출현 {sum(stats.verb_phrase_counts.values())}회)")
    print(f"양상 후보 어간: {len(stats.modal_candidate_counts)}개 (총 출현 {sum(stats.modal_candidate_counts.values())}회)")
    print()
    print("=== 동사구 상위 30 ===")
    for lemma, count in stats.verb_phrase_counts.most_common(30):
        print(f"  {count:6d}  {lemma}")
    print()
    print("=== 양상 후보 어간 (전체) ===")
    for lemma, count in stats.modal_candidate_counts.most_common():
        print(f"  {count:6d}  {lemma}")
    print()
    print(f"저장: {OUT_VERBS}")
    print(f"저장: {OUT_MODALS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
