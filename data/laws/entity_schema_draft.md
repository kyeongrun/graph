# 엔티티(노드) 스키마 초안 (v4, Article도 노드에서 제외)

`scripts/analyze_entities.py` 결과(전체 60개 법령 파일 NNP/복합명사/
단일NNG 빈도 — 원본은 `data/laws/entity_noun_frequency.json`)를 근거로
설계했다. 명사는 개방집합이라 verb_groups처럼 전수 어근 추출→그룹핑
방식은 안 맞고, 실제 말뭉치 상위 빈도를 사람이 보고 귀납적으로
카테고리를 잡았다(방식 자체는 형태소분석에 안 묶여도 된다는 사용자
판단에 따름 — 빈도는 근거자료일 뿐, 분류는 사람 판단).

## v2 → v3: 왜 라벨을 27개 → 6개로 줄였나

v2는 "조직/기관"만 9개, "사람/직위"도 7개 등 대분류별로 NodeLabel을
세분화했다. 사용자가 지적한 문제: **`Consumer`(소비자) 같은 라벨은
그 노드의 본질적 타입이 아니라 특정 관계 안에서의 일시적 역할이다.**
같은 회사가 어떤 조문에서는 "채권자", 다른 조문에서는 그냥 "규제대상
금융회사"일 수 있는데 이런 역할마다 라벨을 만들면 라벨이 무한정
늘어난다.

이건 edge_type 정리 때 배운 원칙과 정확히 같은 문제다: "같은 방향·같은
기능인데 표현만 다른 건 합치고, 세부 차이는 property로 얹는다." 그
원칙을 노드에도 그대로 적용한다 — **"무엇인가(존재론적 타입)"만
NodeLabel로 삼고, "이 관계에서 어떤 역할인가"는 property나 그냥 edge
자체가 암시하게 둔다.**

구체적으로:
- `Consumer`/`DebtorCreditor`/`Whistleblower`/`Officer`/`Employee`/
  `RegulatorOfficial`은 전부 `Person`(또는 조직이 그 역할을 할 때는
  `Organization`) + `role_hint` 속성으로 흡수. "채권자/채무자"는 아예
  속성으로도 안 만든다 — PAYS 엣지 자체가 이미 "누가 누구에게"를
  담고 있어서 별도 role 저장이 중복이다.
- `FinancialInstitution`/`FinancialHoldingGroup`/`RegulatoryBody`/
  `StatutoryInstitution`/`GovernmentAgency`/`InternalOrgUnit`/
  `CorporateEntity`/`ListedCompany`/`CollectiveInvestmentVehicle`/
  `MarketParticipant`(총 10개)는 전부 `Organization` + `category`
  속성으로 흡수.
- `Statute`/`PresidentialDecree`/`MinistrialRule`/`InternalRegulation`
  은 `LegalDocument` + `doc_type` 속성으로 흡수.
- `FinancialProduct`/`FinancialInstrument`/`FinancialBusinessLicense`/
  `Standard`/`Procedure`/`InternalControlConcept`은 `Concept` +
  `concept_type` 속성으로 흡수.
- `Article`은 v3까지 독립 라벨로 남겨뒀었는데(구조적 단위라 역할
  통합 대상이 아니라고 판단), **v4에서 완전히 제거**했다. 이유는 "그래프
  구조: 엔티티 직접 연결" 절 참고 — 요약하면, 그래프가 담아야 하는 건
  법의 "내용"(엔티티 간 관계)이지 "위치"(몇 조 몇 항)가 아니다. 위치는
  이미 엣지의 `article_no`/`paragraph_no` 속성으로 처리하기로 했는데,
  그러면 Article 노드가 실제로 하는 일이 없다 — 조문 원문이 필요하면
  그래프가 아니라 `data/laws/raw/*.md` 원문을 `article_no`로 찾아보면
  된다. "Article은 구조적 단위라 예외"라는 근거 자체가, 결국 엔티티가
  아니라 인용 메타데이터라는 뜻이었다.

Apache AGE(openCypher)는 Neo4j처럼 노드에 라벨을 여러 개 붙이는 게
`CREATE (n:Organization:RegulatoryBody)` 식으로 가능하긴 하다. 그래도
1차는 **라벨 1개 + category 속성** 쪽으로 간다 — 쿼리가 더 단순하고
(`MATCH (n:Organization)`이면 전부 잡힘, category로 더 좁히고 싶을 때만
`WHERE n.category = 'regulatory_body'`), 나중에 필요해지면 특정
category만 골라 보조 라벨을 추가하는 게 그 반대(라벨 쪼개놓고 나중에
합치는 것)보다 쉽다.

## 최종 4개 NodeLabel

| NodeLabel | 대표 속성 | v2에서 흡수한 것 | 실데이터 근거 |
|---|---|---|---|
| `Organization` | `category` | FinancialInstitution, FinancialHoldingGroup, RegulatoryBody, StatutoryInstitution, GovernmentAgency, InternalOrgUnit, CorporateEntity, ListedCompany, CollectiveInvestmentVehicle, MarketParticipant | 금융위원회(3945), 금융지주회사(343), 금융회사(211+), 한국은행(393), 집합투자기구(490) 등 |
| `Person` | `role_hint` | Officer, RegulatorOfficial, Employee, Consumer, DebtorCreditor, Whistleblower | 감사위원(25), 금융감독원장(94), 공익신고자(134), 금융소비자(150) 등 — 이제 전부 `role_hint` 값으로 |
| `LegalDocument` | `doc_type` | Statute, PresidentialDecree, MinistrialRule, InternalRegulation | 법률(746), 대통령령(658+), 총리령(221), 고시(222) — 법 전체가 위임/시행관계의 실제 당사자가 될 때(예: PRESCRIBES의 agent)만 노드로 등장 |
| `Concept` | `concept_type` | FinancialProduct, FinancialInstrument, FinancialBusinessLicense, Standard, Procedure, InternalControlConcept | 금융상품(199+), 집합투자증권(411), 금융투자업(1495), 내부통제(22) |
| ~~Article~~ | — | **v4에서 노드 제거** — `source_law`/`article_no`/`paragraph_no`로 모든 엣지의 속성이 됨 | — |
| ~~속성값(Amount/Period 등)~~ | — | (v2와 동일하게 노드화 안 함) | edge/node property로 흡수 |

`role_hint`/`category`/`doc_type`/`concept_type` 값 목록은 아직 확정
안 함 — 이건 실제 SVO 추출 결과를 보면서 나오는 대로 채워나가는 게
verb_groups 때처럼 처음부터 완벽히 다 못 맞힐 걸 걱정하는 것보다 나을
듯(어차피 열린 목록이라 language처럼 계속 늘어날 수 있음).

## 조문 간 참조(준용/적용)는 어떻게 되나

"제10조는 제5조를 준용한다"는 Article↔Article 엣지를 만드는 게 아니라
**적재 시점에 인용 전파(citation propagation)로 처리**한다 — 제5조에서
뽑힌 관계들에 `article_no: 10`을 (다중값으로) 추가해주는 방식. 그래프
구조는 안 늘어나고 인용 속성만 여러 값을 갖게 된다. "제N조에서 정의를
차용한다" 같은 단순 인용은 그냥 스킵(참조하는 법 자체가 별도로
그래프에 들어가므로 정보 손실 없음) — 다만 "정의차용"과 "준용/적용"을
구분하는 규칙은 아직 미작성.

## 확인 필요한 노이즈(v2와 동일, 유효)

1. **목차 오분류**: "가목/나목/다목/마목/바목/라목"이 NNP로 잘못 잡힘.
2. **개정이력 메타 표현**: "개정규정"(1053), "경과조치"(420),
   "항단서"(363), "조생략부칙"(297), "법률시행령일부"(217) 등 — 부칙/
   개정이력 서술에서 나오는 구조적 표현. 엔티티 아님.

## 다음 단계 제안 (4-라벨 구조로 확정됨)

1. SVO 추출기(svo.py)가 뽑은 agent/patient 텍스트를 이 스키마로 타이핑.
   고유명사로 잡히는 특수목적기관(한국자산관리공사 등)·정부기관은 사전
   매칭(결정론적)으로 `category` 채우고, "해당 기관"/"소속 금융회사"처럼
   문맥 의존적인 표현은 LLM 판정으로 채운다.
2. svo.py에 "정하다/규정하다류 동사 + JKS 없음 + 동사 직전 JKB(으로)"
   패턴 규칙 추가(PRESCRIBES 위임조항의 agent="대통령령"/"감사원규칙"
   등을 잡기 위함, 현재 놓치고 있음).
3. 준용/적용 감지 + 인용 전파 규칙 작성("정의차용" vs "준용/적용" 구분
   포함).
4. law_structure.py로 얻은 article_no/paragraph_no를 svo.py 결과에
   엣지 속성으로 붙이는 오케스트레이션 스크립트 작성(현재 두 모듈이
   따로 존재, 연결 안 됨).
