#!/usr/bin/env python3
"""Step 2 (v3): 동사구(verb_phrase_frequency.json)를 "하나의 의미"
단위로 그룹핑한다.

v1/v2는 사람이 주제·극성 기준으로 수작업 매핑표를 만들었는데, "보호"와
"지원"처럼 방향은 같아도 뜻이 다른 동사를 같은 그룹에 넣는 문제가
반복적으로 나왔다. v3는 판단을 아예 기계적으로 바꾼다:

동사구는 대부분 "체언(한자어 어근) + 하다/되다/받다/시키다" 결합이다
(형태소분석 단계에서 이미 이 구조로 만들어짐 — 예: "보호"+XSV"하" ->
"보호하다"). 그래서 파생접미사(하다/되다/받다/시키다/당하다/드리다)를
떼어내면 남는 한자어 어근이 곧 "그 동사구가 가리키는 단 하나의 의미"가
된다. "보호하다"와 "지원하다"는 어근이 "보호"/"지원"으로 다르므로
자동으로 다른 그룹이 되고, "선임하다"/"선임되다"는 둘 다 어근이
"선임"이라 능동/피동 관계없이 자동으로 같은 그룹이 된다 (그래프
엣지 방향 정규화는 3단계에서 별도 처리 — 그룹핑과는 별개 문제).

접미사가 없는 순수 용언 어간(따르다, 크다, 다르다 등)은 어근 추출이
안 되므로 그 자체가 이미 원자적인 하나의 의미라 그대로 둔다.

사람이 "이건 비슷하니 하나로 묶자"고 판단하는 단계가 아예 없어서
의미가 섞일 여지가 없다 — 대신 그룹 수는 크게 늘어난다(주제별 재분류가
아니라 어근별 정규화이므로).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FREQ_FILE = ROOT / "data" / "laws" / "verb_phrase_frequency.json"
OUT_JSONL = ROOT / "data" / "laws" / "verb_groups.jsonl"

# 파생접미사 (긴 것부터 검사해야 "시키다"를 "하다"로 잘못 자르는 일이 없음)
# "당하다"(피동/수동)는 넣지 않는다 — "해당하다/정당하다/부당하다/타당하다/
# 상당하다/담당하다/충당하다/배당하다"처럼 어근 자체가 "당"으로 끝나는
# 사례가 많아, 이 접미사를 넣으면 "정하다"와 "정당하다"가 같은 어근
# [정]으로 잘못 합쳐지는 오탐이 다수 발생한다. 실제 형식적 법률문에서
# "-당하다"류 피동(예: 거부당하다) 구성은 드물어 얻는 것보다 잃는 게 커서
# 제외했다.
SUFFIXES = ["시키다", "드리다", "받다", "되다", "하다"]


def extract_root(lemma: str) -> str:
    for suf in SUFFIXES:
        if lemma == suf:
            return lemma  # "하다"/"되다" 단독 (일반경량동사) - 그대로
        if lemma.endswith(suf) and len(lemma) > len(suf):
            return lemma[: -len(suf)]
    return lemma  # 접미사 없는 순수 어간 (따르다, 크다 등) - 이미 원자적


def main() -> int:
    freq: list[list] = json.loads(FREQ_FILE.read_text(encoding="utf-8"))

    groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for lemma, count in freq:
        root = extract_root(lemma)
        groups[root].append((lemma, count))

    records = []
    for root, members in groups.items():
        members.sort(key=lambda x: -x[1])
        records.append(
            {
                "root": root,
                "count": sum(c for _, c in members),
                "members": [{"l": lemma, "c": count} for lemma, count in members],
            }
        )
    records.sort(key=lambda r: -r["count"])

    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    total = sum(c for _, c in freq)
    multi = [r for r in records if len(r["members"]) > 1]
    singleton = [r for r in records if len(r["members"]) == 1]

    print(f"전체 동사구: {len(freq)}종 / {total}회")
    print(f"어근 그룹 수: {len(records)}개")
    print(f"  - 2개 이상 동사구가 합쳐진 그룹: {len(multi)}개")
    print(f"  - 단독(1개) 그룹: {len(singleton)}개")
    print()
    print("=== 상위 20 그룹 ===")
    for r in records[:20]:
        members_str = ", ".join(f"{m['l']}({m['c']})" for m in r["members"])
        print(f"  {r['count']:6d}  [{r['root']}] {members_str}")
    print()
    print(f"저장: {OUT_JSONL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
