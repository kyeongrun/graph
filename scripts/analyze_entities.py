#!/usr/bin/env python3
"""엔티티 스키마 설계용 근거자료: data/laws/raw 전체에서 명사(구) 빈도를
집계한다. analyze_verbs.py(동사구 집계)와 같은 목적의 명사판이다.

동사와 다르게 명사는 개방집합이라(동사구는 1,490종으로 끝났지만 명사는
훨씬 많고 다양함) 이 결과를 verb_groups.jsonl처럼 전수 그룹핑하지는
않는다. 대신 상위 빈도를 사람(+LLM)이 보고 엔티티 스키마(노드 타입)를
직접 설계하는 데 참고자료로만 쓴다 — 왜 이런 방식 차이를 두는지는
CLAUDE.md 4단계 이후 섹션 참고.

NNP(고유명사): 기관명/법령명 등 실제 개체명이 그대로 잡힘.
2개 이상 연속 체언(NNG/NNP): 복합명사 근사치("금융위원회", "감사위원회"
같은 조직명이 형태소분석기 사전에 개별 등록 안 돼 있어도 이렇게 잡힘).
단일 NNG: 나머지 일반명사.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(ROOT / "src"))

from graphdb.nlp.morphology import clean_markdown, get_kiwi  # noqa: E402

OUT_FILE = ROOT / "data" / "laws" / "entity_noun_frequency.json"


def main() -> int:
    kiwi = get_kiwi()
    files = sorted((ROOT / "data" / "laws" / "raw").glob("**/*.md"))

    nnp_counter: Counter = Counter()
    nng_counter: Counter = Counter()
    compound_counter: Counter = Counter()

    for f in files:
        text = clean_markdown(f.read_text(encoding="utf-8"))
        tokens = kiwi.tokenize(text)
        i, n = 0, len(tokens)
        while i < n:
            t = tokens[i]
            if t.tag == "NNP":
                nnp_counter[t.form] += 1
            if t.tag in ("NNG", "NNP"):
                j = i
                buf = []
                while j < n and tokens[j].tag in ("NNG", "NNP"):
                    buf.append(tokens[j].form)
                    j += 1
                if len(buf) >= 2:
                    compound_counter["".join(buf)] += 1
                else:
                    nng_counter[t.form] += 1
                i = j
                continue
            i += 1

    OUT_FILE.write_text(
        json.dumps(
            {
                "nnp": nnp_counter.most_common(),
                "compound": compound_counter.most_common(),
                "nng": nng_counter.most_common(),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    print(f"파일 {len(files)}개 처리")
    print(f"NNP {len(nnp_counter)}종, 복합명사 {len(compound_counter)}종, 단일NNG {len(nng_counter)}종")
    print(f"저장: {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
