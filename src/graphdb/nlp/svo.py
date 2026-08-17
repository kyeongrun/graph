"""Step 4: 항(Paragraph) 텍스트에서 결정론적 규칙으로 (주어, 동사, 목적어,
양상, 태) 튜플을 뽑는다.

## 왜 "진짜" 의존구문분석기를 안 쓰는가

kiwipiepy 0.23.2(model_type="cong")는 형태소·격조사 태깅까지만 제공하고
주어-동사 화살표 같은 의존관계 자체는 안 준다. 통계적 한국어 의존구문
분석기(KLUE-DP 등)를 붙이는 방법도 있지만, 이 프로젝트가 폐쇄망으로
옮겨갈 계획이라 무거운 모델 가중치를 새로 들이는 건 유지보수 부담만
키운다. 그래서 격조사(주격 JKS/목적격 JKO/보조사 JX)를 규칙으로 해석하는
방식을 쓴다 — 100% 결정론적이고, 왜 이 주어/목적어가 뽑혔는지 항상
설명 가능하다(이 프로젝트의 핵심 원칙).

## 핵심 난제: 목적어의 화제화(topicalization)

"원장은 국회의 동의를 받아 대통령이 임명한다"에서 "원장"은 JKS가 아니라
JX(은/는)만 붙어 있고, 진짜 주격은 "대통령이"다. 즉 "원장"은 "임명하다"의
목적어("원장을")가 문장 앞으로 빠진 것 — "대통령이 원장을 임명한다"와
같은 뜻이다. 격조사만 보는 단순 규칙은 이걸 놓친다.

규칙: 한 문장(EF로 끝나는 단위) 안에서
- JX(은/는) 표지 명사(topic)와 JKS 표지 명사(subj)가 **둘 다** 나오면
  → subj가 진짜 주어, topic은 (아직 JKO가 없다면) 목적어로 재배정.
- JKS 없이 topic만 있으면 → topic이 주어(가장 흔한 표준 패턴).
- 아무것도 없으면 → 이전 항에서 주어를 상속(pro-drop, extract_svo 밖에서
  ParagraphContext.inherited_subject로 처리).

## 능동/피동 방향 정규화

동사 파생접미사가 "하다"/"시키다"(능동)냐 "되다"/"받다"(피동)냐에 따라
문법적 주어의 의미역이 달라진다("선임하다"의 주어=행위자, "선임되다"의
주어=행위대상). 그래프 엣지는 항상 "행위자→행위대상" 방향이어야 하므로,
피동이면 위에서 구한 agent/patient를 서로 바꾼다("~에 의하여" 행위자
명시구가 있으면 그걸 agent로 쓰고, 없으면 agent=None으로 남겨 사람이
나중에 채우게 한다).

## 양상(의무/금지/재량) 판정

실측 태그 시퀀스(CLAUDE.md의 가설과 약간 다름, 실제 Kiwi 출력 기준으로
수정):
- 재량: NNB(수) + VA(있) — "~할 수 있다". 부정("~하지 아니할 수 있다")이
  앞에 있어도 재량으로 판정(재량으로 의무를 면제받는 것도 재량이므로).
  우선순위 최상위 — 이게 있으면 금지/의무보다 우선.
- 금지: EC(지) + VX(아니하|못하) — "~하지 아니한다/못한다". 재량 패턴이
  없을 때만.
- 의무: EC(어야) + VX(하) — "~하여야 한다". 위 둘 다 없을 때만.
- 그 외: NONE(명시적 양상 표지 없음 — 서술/정의문일 가능성).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from kiwipiepy import Token

from graphdb.nlp.morphology import get_kiwi

_NP_TAGS = {"NNG", "NNP", "XR", "SN", "SL"}
_VERBALIZING_SUFFIXES = {"XSV", "XSA"}
_BARE_PREDICATE_TAGS = {"VV", "VA"}
_MODAL_BARE_PREDICATES = {"있", "없", "되", "아니", "못하", "말"}
_TOPIC_FORMS = {"은", "는"}
_PASSIVE_STEMS = {"되", "받"}  # XSV 파생접미사가 이 형태면 피동
_SENTENCE_END_TAGS = {"EF", "SF"}

# stage 3 group_verbs.py의 SUFFIXES와 동일 — 여기서도 동사구 표면형에서
# 어근을 뽑아 edge_type_mapping.jsonl 조회에 써야 하므로 로직을 맞춘다.
_ROOT_SUFFIXES = ["시키다", "드리다", "받다", "되다", "하다"]


def extract_root(lemma: str) -> str:
    for suf in _ROOT_SUFFIXES:
        if lemma == suf:
            return lemma
        if lemma.endswith(suf) and len(lemma) > len(suf):
            return lemma[: -len(suf)]
    return lemma


class Modality(str, Enum):
    DUTY = "의무"
    PROHIBITION = "금지"
    DISCRETION = "재량"
    NONE = "없음"


class Voice(str, Enum):
    ACTIVE = "능동"
    PASSIVE = "피동"


@dataclass
class SVORecord:
    agent: str | None
    verb_lemma: str  # 예: "선임하다"
    verb_root: str  # 예: "선임" (edge_type_mapping 조회 키)
    patient: str | None
    modality: Modality
    voice: Voice
    agent_source: str  # "JKS" | "TOPIC" | "INHERITED" | "NONE" — 근거 추적용


def _is_np_token(tok: Token) -> bool:
    if tok.tag in _NP_TAGS:
        return True
    # "등"(NNB)은 "금융회사등/임원등"처럼 사실상 명사 접미사로 쓰이는데
    # NNB(의존명사) 태그를 받는다. "수/것/때" 같은 일반 NNB와 달리 앞
    # 체언에 바로 붙어 명사구를 연장하므로 예외로 포함시킨다.
    return tok.tag == "NNB" and tok.form == "등"


def _np_run_text(tokens: list[Token], end_idx: int) -> str | None:
    """end_idx 바로 앞까지 이어지는 체언(명사) 연속을 하나의 명사구로 합친다."""
    start = end_idx
    while start > 0 and _is_np_token(tokens[start - 1]):
        start -= 1
    if start == end_idx:
        return None
    return "".join(t.form for t in tokens[start:end_idx])


def _verb_phrase_at(tokens: list[Token], i: int) -> tuple[str, Voice, int] | None:
    """i에서 동사구가 시작하면 (lemma, voice, verb_end)를 반환, 아니면 None."""
    n = len(tokens)
    tok = tokens[i]
    if tok.tag in _NP_TAGS and i + 1 < n and tokens[i + 1].tag in _VERBALIZING_SUFFIXES:
        suffix = tokens[i + 1]
        voice = Voice.PASSIVE if suffix.form in _PASSIVE_STEMS else Voice.ACTIVE
        return f"{tok.form}{suffix.form}다", voice, i + 2
    if tok.tag in _BARE_PREDICATE_TAGS and tok.form not in _MODAL_BARE_PREDICATES:
        return f"{tok.form}다", Voice.ACTIVE, i + 1
    return None


def _detect_modality(tokens: list[Token], verb_end: int, sentence_end: int) -> Modality:
    # 양상 어미/보조용언 사슬은 그 동사 바로 뒤에 붙는다 — 다음 동사구가
    # 시작되기 전까지만 봐야 한다("A하며 B되지 아니한다"에서 A의 양상
    # 창을 B까지 넘겨보면 B의 "지 아니한다"를 A의 것으로 오판한다).
    clause_end = verb_end
    while clause_end < sentence_end and _verb_phrase_at(tokens, clause_end) is None:
        clause_end += 1
    window = tokens[verb_end:clause_end]
    forms_tags = [(t.form, t.tag) for t in window]

    for i, (form, tag) in enumerate(forms_tags):
        if tag == "NNB" and form == "수" and i + 1 < len(forms_tags):
            nform, ntag = forms_tags[i + 1]
            if ntag == "VA" and nform == "있":
                return Modality.DISCRETION

    for i, (form, tag) in enumerate(forms_tags):
        if tag == "EC" and form == "지" and i + 1 < len(forms_tags):
            nform, ntag = forms_tags[i + 1]
            if ntag == "VX" and nform in ("아니하", "못하"):
                return Modality.PROHIBITION

    for i, (form, tag) in enumerate(forms_tags):
        if tag == "EC" and form == "어야" and i + 1 < len(forms_tags):
            nform, ntag = forms_tags[i + 1]
            if ntag == "VX" and nform == "하":
                return Modality.DUTY

    return Modality.NONE


def _find_agent_phrase(tokens: list[Token], verb_start: int) -> str | None:
    """피동문의 "~에 의하여" 행위자 명시구를 verb 앞에서 찾는다.

    실제 토큰화를 보면 "의하다"는 JKB가 아니라 그 자체가 VV(동사)이고
    격조사는 그 앞의 "에"(JKB)다 — "금융위원회에 의하여" =
    금융위원회(NNG)+에(JKB)+의하(VV)+어(EC). 처음엔 "의하"/"의해"를
    JKB 태그로 잘못 찾고 있어서 이 규칙이 한 번도 안 걸렸었다(실제
    문장으로 테스트하다 발견).
    """
    for i in range(verb_start - 1, -1, -1):
        if (
            tokens[i].tag == "VV"
            and tokens[i].form == "의하"
            and i > 0
            and tokens[i - 1].tag == "JKB"
            and tokens[i - 1].form == "에"
        ):
            # "OO에 의하여"의 OO
            return _np_run_text(tokens, i - 1)
        if tokens[i].tag in _SENTENCE_END_TAGS:
            break
    return None


def extract_svo(text: str, inherited_subject: str | None = None) -> list[SVORecord]:
    """항(또는 그 안의 한 문장) 텍스트에서 SVORecord 목록을 뽑는다.

    inherited_subject: 이 항 첫 문장에 주어 표지(JKS/JX)가 전혀 없을 때
    쓸 이전 항의 주어(pro-drop 상속). 호출부(extract_paragraph_svo)에서
    항 단위로 관리한다.
    """
    kiwi = get_kiwi()
    tokens = kiwi.tokenize(text)
    n = len(tokens)

    records: list[SVORecord] = []
    record_sentence_idx: list[int] = []
    subj: str | None = None
    topic: str | None = None
    obj: str | None = None
    used_inherited = False
    sentence_idx = 0

    i = 0
    while i < n:
        tok = tokens[i]

        if tok.tag == "JKS":
            np = _np_run_text(tokens, i)
            if np:
                subj = np
                # 새 주격 명사가 등장했다는 건 새 절(문법적 프레임)이
                # 시작됐다는 뜻 — 이전 절에서 쓰던 목적어를 그대로
                # 물려주면 안 된다(예: "OO를 받아 XX가 임명한다"에서
                # "XX가"가 나온 순간 이전 절의 "OO를"은 무효화해야
                # "임명한다"가 화제화된 목적어를 제대로 잡는다).
                obj = None
            i += 1
            continue

        if tok.tag == "JX" and tok.form in _TOPIC_FORMS:
            np = _np_run_text(tokens, i)
            if np:
                topic = np
            i += 1
            continue

        if tok.tag == "JKO":
            np = _np_run_text(tokens, i)
            if np:
                obj = np
            i += 1
            continue

        verb_match = _verb_phrase_at(tokens, i)

        if verb_match is not None:
            lemma, voice, verb_end = verb_match
            sentence_end = verb_end
            while sentence_end < n and tokens[sentence_end].tag not in _SENTENCE_END_TAGS:
                sentence_end += 1
            modality = _detect_modality(tokens, verb_end, sentence_end)

            if subj is not None:
                agent, agent_source = subj, "JKS"
                patient = topic if (topic is not None and obj is None) else obj
            elif topic is not None:
                agent, agent_source = topic, "TOPIC"
                patient = obj
            elif inherited_subject is not None and not used_inherited:
                agent, agent_source = inherited_subject, "INHERITED"
                patient = obj
            else:
                agent, agent_source = None, "NONE"
                patient = obj

            if voice == Voice.PASSIVE:
                by_agent = _find_agent_phrase(tokens, i)
                agent, patient = (by_agent, agent) if by_agent else (None, agent)
                agent_source = "JKB(의하여)" if by_agent else agent_source

            records.append(
                SVORecord(
                    agent=agent,
                    verb_lemma=lemma,
                    verb_root=extract_root(lemma),
                    patient=patient,
                    modality=modality,
                    voice=voice,
                    agent_source=agent_source,
                )
            )
            record_sentence_idx.append(sentence_idx)
            i = verb_end
            continue

        if tok.tag in _SENTENCE_END_TAGS:
            subj = None
            topic = None
            obj = None
            used_inherited = True
            sentence_idx += 1
            i += 1
            continue

        i += 1

    _backfill_forward_subject(records, record_sentence_idx)
    return records


def _backfill_forward_subject(records: list[SVORecord], sentence_idx: list[int]) -> None:
    """"OO을 거쳐 XX가 명한다"처럼 진짜 주어(JKS)가 뒤쪽 절에 한 번만
    나오고 앞선 절들이 공유하는 경우, 같은 문장 안에서 뒤에 나오는 JKS
    주어를 앞의 agent=None 레코드에 역방향으로 채워 넣는다. 왼쪽→오른쪽
    한 번 훑기(단일 패스)로는 못 잡는 케이스라 사후 보정으로 처리한다.
    JKS 출처만 신뢰한다(TOPIC/INHERITED까지 역전파하면 다른 문장·항의
    주어가 잘못 새어 들어올 위험이 커서 제외).
    """
    n = len(records)
    for i in range(n):
        if records[i].agent is not None or records[i].agent_source != "NONE":
            continue
        for j in range(i + 1, n):
            if sentence_idx[j] != sentence_idx[i]:
                break
            if records[j].agent_source == "JKS":
                records[i] = SVORecord(
                    agent=records[j].agent,
                    verb_lemma=records[i].verb_lemma,
                    verb_root=records[i].verb_root,
                    patient=records[i].patient,
                    modality=records[i].modality,
                    voice=records[i].voice,
                    agent_source="JKS(순방향유추)",
                )
                break
