"""Step 1 of the law knowledge-graph pipeline: 형태소분석으로 법령 원문의
동사(구)를 파악한다.

Kiwi(kiwipiepy)를 사용한다. 법률문은 대부분 "체언(NNG/NNP/XR) + 하다/되다
(XSV/XSA)" 결합이라, 형태소 태그를 그대로 세면 "하다/되다"만 압도적으로
잡혀 의미 정보가 사라진다. 그래서 체언+파생접미사를 하나의 "동사구"로
합쳐서 센다 (예: "선임"+NNG "하"+XSV -> "선임하다").

의무/금지/재량 같은 양상(modality)은 동사구 자체가 아니라 그 뒤에 붙는
어미/보조용언 사슬("-어야 하다", "-아니 되다", "-ㄹ 수 있다")에 실려
있으므로, 이 단계에서는 별도로 분리해 "양상 후보" 버킷에만 모아 둔다
(정식 양상 판정은 3단계: 주어/목적어 추출과 함께 처리).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from kiwipiepy import Kiwi

_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ESCAPED_DOT_RE = re.compile(r"\\\.")
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_HEADER_RE = re.compile(r"^#+\s*", re.MULTILINE)

_VERBALIZING_SUFFIXES = {"XSV", "XSA"}  # 하다/되다/스럽다 등 체언->용언 파생 접미사
_CONTENT_TAGS = {"NNG", "NNP", "XR"}  # 체언/어근 (동사구의 의미 핵심)
_BARE_PREDICATE_TAGS = {"VV", "VA"}  # 독립된 동사/형용사 어간

# 체언과 결합하지 않고 단독으로 나타나는 이 어간들은 대개 "행위"가 아니라
# 의무/금지/재량을 나타내는 양상 표현의 일부다 (예: "~할 수 있다"의 "있다",
# "~하여서는 아니 된다"의 "되다"). 행위 동사구 집계에서는 제외하고 별도
# 버킷으로 모은다.
_MODAL_BARE_PREDICATES = {"있", "없", "되", "아니", "못하", "말"}

_kiwi: Kiwi | None = None


def get_kiwi() -> Kiwi:
    global _kiwi
    if _kiwi is None:
        _kiwi = Kiwi()
    return _kiwi


def add_domain_words(words: list[tuple[str, str]]) -> None:
    """분석 전에 법률/금융 도메인 복합명사를 사용자 사전에 등록한다.
    예: [("업무집행책임자", "NNG"), ("금융복합기업집단", "NNG")]
    """
    kiwi = get_kiwi()
    for form, tag in words:
        kiwi.add_user_word(form, tag)


def clean_markdown(text: str) -> str:
    text = _FRONTMATTER_RE.sub("", text)
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _ESCAPED_DOT_RE.sub(".", text)
    text = _HEADER_RE.sub("", text)
    return text


@dataclass
class VerbPhrase:
    lemma: str  # 예: "선임하다"
    head_form: str  # 예: "선임"
    head_tag: str  # NNG/NNP/XR/VV/VA


def extract_verb_phrases(text: str) -> tuple[list[VerbPhrase], list[str]]:
    """(행위 동사구 목록, 양상 후보 어간 목록)을 반환한다."""
    kiwi = get_kiwi()
    tokens = kiwi.tokenize(text)
    phrases: list[VerbPhrase] = []
    modal_candidates: list[str] = []

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.tag in _CONTENT_TAGS and i + 1 < n and tokens[i + 1].tag in _VERBALIZING_SUFFIXES:
            suffix = tokens[i + 1]
            phrases.append(
                VerbPhrase(lemma=f"{tok.form}{suffix.form}다", head_form=tok.form, head_tag=tok.tag)
            )
            i += 2
            continue
        if tok.tag in _BARE_PREDICATE_TAGS:
            if tok.form in _MODAL_BARE_PREDICATES:
                modal_candidates.append(f"{tok.form}다")
            else:
                phrases.append(VerbPhrase(lemma=f"{tok.form}다", head_form=tok.form, head_tag=tok.tag))
            i += 1
            continue
        i += 1

    return phrases, modal_candidates


@dataclass
class CorpusStats:
    verb_phrase_counts: Counter
    modal_candidate_counts: Counter
    files_processed: int
    sentences_processed: int = 0


def analyze_corpus(paths: list[Path]) -> CorpusStats:
    verb_counter: Counter = Counter()
    modal_counter: Counter = Counter()
    for path in paths:
        text = clean_markdown(path.read_text(encoding="utf-8"))
        phrases, modals = extract_verb_phrases(text)
        verb_counter.update(vp.lemma for vp in phrases)
        modal_counter.update(modals)
    return CorpusStats(
        verb_phrase_counts=verb_counter,
        modal_candidate_counts=modal_counter,
        files_processed=len(paths),
    )
