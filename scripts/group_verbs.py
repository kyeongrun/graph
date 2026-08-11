#!/usr/bin/env python3
"""Step 2: 1단계에서 추출한 동사구(verb_phrase_frequency.json)를 50개 미만의
의미 그룹으로 묶는다.

그룹 배정은 사람이 상위 320위(전체 출현의 약 93%)까지 직접 검토해 확정한
명시적 매핑 테이블이다 (이 파일 GROUPS 참조). LLM이 아니라 사람이 읽고
결정한 규칙이므로 근거를 그대로 코드에 남긴다 — 왜 이 동사구가 이 그룹인지
설명 가능해야 하고, 나중에 틀렸으면 이 표만 고치면 된다.

장기 꼬리(321위 이하, 나머지 약 7%)는 강제로 묶지 않고 '기타'로 남긴다.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FREQ_FILE = ROOT / "data" / "laws" / "verb_phrase_frequency.json"
OUT_MAPPING = ROOT / "data" / "laws" / "verb_group_mapping.tsv"
OUT_GROUP_STATS = ROOT / "data" / "laws" / "verb_group_stats.json"

# (그룹ID, 그룹명, 설명, 소속 동사구 목록)
# 참조/정의/간주 등은 "행위"는 아니지만 조문에서 실제로 반복되는 서술 패턴이라
# 원 요구사항("전체 동사를 50개 미만으로 그룹핑") 그대로 그룹에 포함시킨다.
# 다만 그래프 스키마에 반영할 때는 이 그룹들이 REFERENCES/DEFINED_AS 같은
# 구조적 관계로 갈 가능성이 높다는 점을 이후 단계에서 감안해야 한다.
GROUPS: list[tuple[str, str, str, list[str]]] = [
    ("REF", "준거참조", "다른 조문/법령에 근거하거나 참조함 (구조적 표현)",
     ["따르다", "의하다", "관하다", "대하다", "준용하다", "준용되다", "인하다",
      "준하다", "통하다", "비추다", "인용하다", "우선하다", "위하다"]),
    ("EXC", "예외배제", "예외·제외·한정",
     ["불구하다", "제외하다", "한정하다", "한하다"]),
    ("DEF", "정의지칭", "용어 정의·지칭",
     ["말하다", "해당하다", "해당되다", "같다", "그러하다", "특정하다"]),
    ("DEEM", "간주의제", "간주·추정·인정",
     ["보다", "인정되다", "인정하다", "판단하다", "판단되다"]),
    ("INC", "포함구성", "포함·구성·구분",
     ["포함하다", "포함되다", "구성하다", "구성되다", "구분하다", "산입하다"]),
    ("DELE", "위임고시", "하위법령·고시로 위임하거나 제정함",
     ["정하다", "고시하다", "규정하다", "규정되다", "제정하다"]),
    ("ENFORCE", "시행공포", "법령의 시행·공포·개정",
     ["시행하다", "공포하다", "공포되다", "개정하다", "개정되다", "신설하다",
      "삭제하다", "폐지하다"]),
    ("PERIOD", "기간경과", "기간·시점의 경과",
     ["경과하다", "도래하다", "지나다", "끝나다", "만료되다", "연장하다",
      "시작하다", "마치다", "소요되다"]),
    ("COMPLY", "준수위반", "준수·위반·저해",
     ["준수하다", "위반하다", "위반되다", "해치다", "저해하다", "방해하다"]),
    ("APPLY", "적용운용", "적용·운용·실시·집행",
     ["적용하다", "적용되다", "운용하다", "운영하다", "실시하다", "행하다",
      "집행하다"]),
    ("ACQUIRE", "취득보유", "취득·보유·소유",
     ["취득하다", "보유하다", "소유하다", "매수하다", "인수하다", "가지다",
      "양수하다"]),
    ("DISPOSE", "처분양도", "처분·양도·이전",
     ["처분하다", "양도하다", "매도하다", "이전하다", "출자하다", "편입하다"]),
    ("ISSUE", "발행거래", "증권 등의 발행·모집·거래",
     ["발행하다", "발행되다", "모집하다", "판매하다", "매매하다", "상장되다",
      "상장하다", "거래하다", "거래되다", "매출하다", "중개하다"]),
    ("SUBMIT", "제출신청", "제출·신청·기재",
     ["제출하다", "제출되다", "제출받다", "신청하다", "청구하다", "첨부하다",
      "기재하다", "기재되다", "작성하다", "서명하다"]),
    ("REPORT", "보고공시", "보고·통지·공시·공개",
     ["보고하다", "통지하다", "통보하다", "통보받다", "신고하다", "알리다",
      "공시하다", "표시하다", "표시되다", "송부하다", "공고하다", "접수하다",
      "접수되다", "밝히다", "게시하다", "게재하다", "공개하다", "공개되다",
      "공표하다"]),
    ("APPROVE", "승인결정", "승인·의결·결정",
     ["결정하다", "의결하다", "결의하다", "확정되다", "동의하다", "협의하다",
      "소집하다"]),
    ("DEMAND", "요구명령", "요구·요청·권고",
     ["요구하다", "요청하다", "명하다", "권고하다", "권유하다", "강요하다"]),
    ("APPOINT", "선임임면", "선임·임면·위촉",
     ["선임하다", "선임되다", "해임하다", "위촉하다", "임용하다", "임명되다",
      "지명하다", "추천하다", "대리하다", "퇴임하다", "대행하다"]),
    ("REGISTER", "등록설립", "등록·설립·설치·해산",
     ["등록하다", "등록되다", "설립하다", "설립되다", "설치하다", "설치되다",
      "개설하다", "해산하다", "존속하다", "소멸하다"]),
    ("CANCEL", "취소종료", "취소·종료·해지",
     ["취소하다", "취소되다", "종료되다", "종료하다", "갈음하다", "해지하다",
      "퇴직하다"]),
    ("INSPECT", "검사확인", "검사·확인·평가·산정",
     ["확인하다", "확인되다", "검토하다", "조사하다", "증명하다", "산정하다",
      "산정되다", "산출하다", "평가하다", "점검하다", "감독하다", "합산하다",
      "심사하다", "반영하다"]),
    ("MANAGE", "관리수행", "관리·수행·이행",
     ["관리하다", "수행하다", "처리하다", "담당하다", "이행하다", "유지하다",
      "두다", "수립하다", "활용하다"]),
    ("PAY", "지급납부", "지급·납부·배상",
     ["지급하다", "납부하다", "징수하다", "부담하다", "배상하다", "보증하다",
      "변제하다", "반환하다", "회수하다", "적립하다", "보전하다", "배분하다"]),
    ("RESTRICT", "제한금지", "제한·거부·방지·면제",
     ["제한하다", "제한되다", "거부하다", "회피하다", "방지하다", "면제하다"]),
    ("SANCTION", "부과제재", "부과·처분·시정",
     ["부과하다", "처하다", "시정하다"]),
    ("CONTRACT", "계약위탁", "계약·위탁·대항",
     ["체결하다", "교부하다", "예탁하다", "위탁하다", "위탁받다", "대항하다",
      "승계하다"]),
    ("USE", "이용영위", "이용·영위·투자·종사",
     ["이용하다", "사용하다", "영위하다", "투자하다", "종사하다", "근무하다",
      "참여하다"]),
    ("REQUIRE", "요건충족", "요건 충족·미충족",
     ["갖추다", "충족하다", "적합하다", "확보하다", "미달하다"]),
    ("RELATE", "소속관련", "소속·지배·관련",
     ["소속되다", "속하다", "지배하다", "관련하다", "관련되다"]),
    ("PROTECT", "보호지원", "보호·지원·제공",
     ["보호하다", "지원하다", "제공하다", "제공받다", "제공되다"]),
    ("NECESSITY", "필요당위", "필요성·가능성·당위 (양상에 인접)",
     ["필요하다", "가능하다", "곤란하다", "불가피하다", "노력하다"]),
    ("STATE", "상태속성", "상태·속성 서술 (형용사성 술어)",
     ["건전하다", "정당하다", "적절하다", "적정하다", "공정하다", "중요하다",
      "중대하다", "동일하다", "다르다", "유사하다", "특별하다", "부당하다",
      "크다", "충분하다", "비슷하다", "명백하다", "현저하다", "경미하다",
      "불리하다", "밀접하다", "타당하다", "일정하다", "높다"]),
    ("OCCUR", "발생변동", "발생·변동·전환·진행",
     ["발생하다", "변동되다", "전환되다", "전환하다", "진행되다"]),
    ("RECORD", "기록보관", "기록·보관·비치·이첩",
     ["기록하다", "보관하다", "비치하다", "이첩하다"]),
    ("MISC_ACT", "기타서술", "그 외 저빈도 서술 동사",
     ["설명하다", "제기하다", "나다", "남다", "붙이다", "내다", "빼다",
      "합하다", "알다"]),
    ("SELECT", "선정지정", "선정·지정",
     ["선정하다", "지정하다", "지정되다"]),
    ("GENERIC", "일반경량동사", "정보량이 낮은 일반 동사 — 문맥(주어/목적어) 없이는 분류 불가, 3단계 SVO에서 재판정 필요",
     ["하다"]),
]

# 그룹 수 상한 확인 (요구사항: 50개 미만)
assert len(GROUPS) < 50, f"그룹이 {len(GROUPS)}개로 50개 이상입니다"


def build_mapping() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for group_id, _, _, lemmas in GROUPS:
        for lemma in lemmas:
            if lemma in mapping:
                raise ValueError(f"'{lemma}' 가 두 그룹({mapping[lemma]}, {group_id})에 중복 배정됨")
            mapping[lemma] = group_id
    return mapping


def main() -> int:
    freq: list[list] = json.loads(FREQ_FILE.read_text(encoding="utf-8"))
    mapping = build_mapping()
    group_meta = {g[0]: (g[1], g[2]) for g in GROUPS}

    group_counts: Counter = Counter()
    group_members: dict[str, list[tuple[str, int]]] = {g[0]: [] for g in GROUPS}
    unclassified: list[tuple[str, int]] = []

    rows = []
    for lemma, count in freq:
        group_id = mapping.get(lemma)
        if group_id is None:
            group_id = "UNCLASSIFIED"
            unclassified.append((lemma, count))
        else:
            group_counts[group_id] += count
            group_members[group_id].append((lemma, count))
        rows.append((lemma, count, group_id))

    total = sum(c for _, c in freq)
    classified_total = sum(c for _, c, g in rows if g != "UNCLASSIFIED")

    # 매핑 테이블 저장 (동사구 단위, 감사 추적용)
    with OUT_MAPPING.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["동사구", "빈도", "그룹ID", "그룹명"])
        for lemma, count, group_id in rows:
            group_name = group_meta.get(group_id, ("미분류",))[0]
            w.writerow([lemma, count, group_id, group_name])

    # 그룹별 통계 저장
    stats = {
        "총_동사구_종류": len(freq),
        "총_출현횟수": total,
        "그룹_수": len(GROUPS),
        "분류된_출현비율": round(classified_total / total * 100, 2),
        "미분류_동사구_종류": len(unclassified),
        "미분류_출현횟수": total - classified_total,
        "groups": [
            {
                "id": gid,
                "name": group_meta[gid][0],
                "description": group_meta[gid][1],
                "member_count": len(group_members[gid]),
                "occurrence_count": group_counts[gid],
                "occurrence_pct": round(group_counts[gid] / total * 100, 2),
                "members": sorted(group_members[gid], key=lambda x: -x[1]),
            }
            for gid, _, _, _ in GROUPS
        ],
    }
    stats["groups"].sort(key=lambda g: -g["occurrence_count"])
    OUT_GROUP_STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"그룹 수: {len(GROUPS)}개 (요구사항: 50개 미만)")
    print(f"분류된 출현비율: {stats['분류된_출현비율']}%  (미분류 {stats['미분류_동사구_종류']}종 / {stats['미분류_출현횟수']}회)")
    print()
    print("=== 그룹별 출현비율 (상위 15) ===")
    for g in stats["groups"][:15]:
        print(f"  {g['occurrence_pct']:5.1f}%  [{g['id']:10s}] {g['name']:8s} ({g['member_count']}개 동사구) - {g['description']}")
    print()
    print(f"저장: {OUT_MAPPING}")
    print(f"저장: {OUT_GROUP_STATS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
