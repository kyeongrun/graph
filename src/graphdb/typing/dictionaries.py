"""Dictionary-first entity typing rules (CLAUDE.md "5단계" role table:
"고유명사·정부기관은 사전 매칭 우선, ... 문맥 의존 표현만 LLM"). Nouns are
an open vocabulary (unlike the closed ~1,500-verb set), so these lists are
deliberately coarse suffix/keyword heuristics, not an exhaustive dictionary
— anything they miss falls through to LLM typing in entity_typing.py.

Suffix lists are ordered by how specific/safe the match is; entity_typing.py
tries them in a fixed order (law instrument names first, since a wrong
LegalDocument/Organization split is the most visible mistake) and stops at
the first hit.
"""

from __future__ import annotations

# 금융위=금융위원회=금융감독위원회(구 명칭) 같이 CLAUDE.md에 명시적으로
# 나온 동일 지시어만 우선 흡수한다. 사전에 없는 후보는 LLM이 보강하는
# 대신(alias_hints.py 참고, 이번 패스는 사전만으로 처리 — 아래 모듈
# docstring 참고), 최소한 이 목록만은 결정론적으로 항상 맞춰둔다.
ALIAS_MAP: dict[str, str] = {
    "금융위": "금융위원회",
    "금융감독위원회": "금융위원회",  # 구 명칭
    "감독위원회": "금융위원회",
    "금감원": "금융감독원",
    "감독원": "금융감독원",
    "한은": "한국은행",
    "예보": "예금보험공사",
    "공정위": "공정거래위원회",
}

# 법령명 판정에서 "위법/불법/준법/탈법/무법/편법"처럼 "법"으로 끝나지만
# 실제로는 법령이 아니라 개념(Concept)인 단어들 — 접미사만 보고 걸러내면
# 오분류가 나서 명시적으로 예외 처리한다.
_LAW_SUFFIX_BLACKLIST = {"위법", "불법", "준법", "탈법", "무법", "편법", "합법"}

LAW_INSTRUMENT_SUFFIXES: tuple[str, ...] = (
    "법률",
    "시행령",
    "시행규칙",
    "감사원규칙",
    "고시",
    "훈령",
    "예규",
    "법",
)

PERSON_ROLE_SUFFIXES: tuple[str, ...] = (
    "위원장",
    "이사장",
    "대표이사",
    "사외이사",
    "상근감사",
    "감사위원",
    "임직원",
    "위원",
    "이사",
    "감사",
    "임원",
    "직원",
    "근로자",
    "대리인",
    "수탁자",
    "신고자",
    "소비자",
    "채권자",
    "채무자",
    "원장",
    "청장",
    "처장",
    "장관",
    "대통령",
    "총재",
    "총장",
    "행장",
    "회장",
    "사장",
    "부사장",
    "전무",
    "상무",
    "본부장",
    "지점장",
    "책임자",
    "관리자",
    "담당자",
    "대리",
    "검사역",
    "심사역",
    "조사역",
    "청문감사인",
    "준법감시인",
    "내부감사인",
    "선임계리사",
    "계리사",
    "회계사",
    "변호사",
    "발기인",
    "청산인",
    "파산관재인",
    "관리인",
    "보증인",
    "대표자",
    "발행인",
    "인수인",
    "매수인",
    "매도인",
    "임차인",
    "임대인",
    "이해관계인",
    "주주",
    "출자자",
    "투자자",
    "예금자",
    "가입자",
    "피보험자",
    "보험계약자",
    "수익자",
    "위탁자",
    "당사자",
    "신청인",
    "청구인",
)

ORG_SUFFIXES: tuple[str, ...] = (
    "금융지주회사",
    "지주회사",
    "저축은행",
    "종합금융회사",
    "여신전문금융회사",
    "자산운용회사",
    "자산운용사",
    "보험회사",
    "증권회사",
    "은행",
    "보험사",
    "증권사",
    "캐피탈",
    "카드사",
    "신탁회사",
    "위원회",
    "이사회",
    "총회",
    "협의회",
    "심의회",
    "공사",
    "공단",
    "협회",
    "연합회",
    "조합",
    "금고",
    "기금",
    "센터",
    "기관",
    "단체",
    "법인",
    "그룹",
    "회사",
    "본부",
    "청",  # 국세청/관세청/경찰청/특허청 등 정부기관 — 2026-08-18 추가
)

CONCEPT_KEYWORDS_SUFFIXES: tuple[str, ...] = (
    "내부통제",
    "지배구조",
    "자기자본",
    "신용정보",
    "금융투자상품",
    "금융상품",
    "집합투자증권",
    "집합투자기구",
    "위험관리",
    "리스크관리",
    "리스크",
    "제도",
    "기준",
    "원칙",
    "절차",
    "체계",
    "정책",
    "계획",
    "전략",
    "채권",
    "주식",
    "펀드",
    "신탁재산",
    "자산",
    "부채",
    "자본금",
    "손익",
    "수익",
    "비용",
    "정보",
)


# SVO extraction sometimes glues a preceding generic/filler noun phrase
# onto an entity mention with no natural break, fragmenting one real
# organization into many spurious node names — live-verified 2026-08-18:
# "금융위원회" alone had 25 distinct node names in the graph (e.g.
# "경우금융위원회", "기간동안금융위원회", "때금융위원회", "등금융위원회"),
# only 1 of which was the bare canonical name. Root cause is presumably in
# svo.py's noun-phrase-run merging, but nlp/ is off-limits to fix directly
# (CLAUDE.md: "손대지 않는다, 버그를 발견해도 여기선 고치지 말고 별도로
# 보고만 한다") — so this is a post-hoc dealiasing pass at the entity
# resolution layer instead, same spirit as ALIAS_MAP above.
#
# Deliberately narrow and conservative: only strips a prefix that exactly
# matches one of these known filler fragments, and only when what's left
# after stripping is one of a small curated list of canonical organization
# names — NOT a general "any prefix in front of a known suffix" rule. That
# distinction matters: e.g. "감사원장"/"한국은행총재"/"금융감독원장" all
# CONTAIN a canonical name but are genuinely different entities (the
# officeholder, a Person) — they have the extra text as a *suffix*, so
# `name.endswith(target)` is already false for them and this function
# leaves them alone. Only prefix-glued junk in front of the exact
# canonical name is touched.
_JUNK_PREFIXES = (
    "해당기간동안", "기간동안", "경우등", "경우", "기간등", "보완기간등",
    "사람등", "정보통신망이용등", "명칭등", "여부등", "청산대상거래등",
    "증권등", "자산비율등", "행위등", "공동사용금지등", "거래조건기타",
    "취득가격기타", "자구수정등", "내용등", "이상", "때", "등",
)

_CANONICAL_DEALIAS_TARGETS = (
    "금융위원회", "금융감독원", "한국은행", "감사원", "금융정보분석원",
    "공정거래위원회", "예금보험공사", "한국거래소", "한국자산관리공사",
    "한국산업은행", "중소기업은행",
)


def strip_junk_prefix(name: str) -> str:
    for target in _CANONICAL_DEALIAS_TARGETS:
        if name != target and name.endswith(target):
            prefix = name[: -len(target)]
            if prefix in _JUNK_PREFIXES:
                return target
    return name


def resolve_alias(name: str) -> str:
    stripped = strip_junk_prefix(name)
    return ALIAS_MAP.get(stripped, stripped)


def looks_like_law_instrument(name: str) -> bool:
    if name in _LAW_SUFFIX_BLACKLIST:
        return False
    return any(name.endswith(suf) and len(name) > len(suf) for suf in LAW_INSTRUMENT_SUFFIXES)
