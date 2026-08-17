# 프로젝트 컨텍스트 (Claude Code 핸드오프)

금융지주회사 내부통제시스템 RAG 프로젝트의 **그래프DB 구축** 부분. 최종
목표는 대한민국 법령(현재 33개 금융권 관련 법령)을 조문 단위 지식그래프로
만들어, 사내 내부통제기준/통제항목이 어떤 법조문에 근거하는지 추적 가능한
GraphRAG를 만드는 것.

**핵심 방향 전환(1차)**: 초반에는 LLM 기반 엔티티/관계 추출을 검토했으나,
컴플라이언스 시스템 특성상 "왜 이 관계가 추출됐는지 설명 가능해야 한다"는
이유로 **NLP 형태소분석 기반 결정론적 추출**로 전환했다. 이 결정론적
파이프라인의 산출물이 바로 **그래프 스키마**(엔티티 4-라벨, edge_type
64개 — 전수 근거자료로 확정)다.

**핵심 방향 전환(2차, 2026-08-15)**: 스키마 확정 이후 "새 문서가 들어올
때마다 저 결정론적 규칙만으로 실제 적재까지 처리한다"는 가정을
재검토했다. 결론: **스키마(라벨/edge_type 집합)는 계속 고정**하되, 신규
문서에 대한 실제 추출은 **관계의 존재/방향(agent↔patient)/양상
(modality)/능동피동(voice)은 여전히 svo.py가 결정하고, LLM은 그 결과를
뒤엎지 않는 좁은 역할만 보탠다** — 상세 경계는 "## 5단계"와 "작업
스타일" 절 참고. 새 파이프라인은 우선 `data/laws/raw/` 기존 60개 파일
대상으로 붙인다(실 문서 API 연동은 나중).

**설계 히스토리를 옮긴 이유**: 위 스키마/그래프 구조가 지금 형태로
확정되기까지 verb_groups v1→v3, edge_type v1→v3, 엔티티 라벨 v1→v4,
그래프 구조 3회 재설계 등 상당한 반려/재작업 히스토리가 있었다. 그
전체 서술이 "## 5단계"(지금 당장 할 일) 앞에 있으면 오히려 헷갈릴 수
있어서 `data/laws/pipeline_design_log.md`로 옮겼다 — **5단계를
구현하는 데는 필요 없고**, 왜 이런 선택을 했는지 나중에 되짚을 때만
보면 된다. 아래 두 절이 그 결론만 요약한다.

## 확정된 산출물 (재사용, 손대지 않음)

| 산출물 | 위치 | 상태 |
|---|---|---|
| 원문 60개 법령 md | `data/laws/raw/` | 완료 |
| 파일별 메타데이터(법령MST/공포일자/시행일자/소관부처) | `data/laws/manifest.json` | 완료 |
| 조/항/호 파서 | `src/graphdb/nlp/law_structure.py` | 완료(60개 파일/3,775개 조문/10,466개 항 검증) |
| 격조사 기반 SVO 추출기 | `src/graphdb/nlp/svo.py` | 1차 구현 완료 — 아래 "svo.py가 이미 해결한 것" 참고 |
| 어근→edge_type 매핑(913개 어근, 100%) | `data/laws/edge_type_mapping.jsonl` | 완료 |
| 그래프 스키마 코드(`NodeLabel` 4개, `EdgeLabel` 64개) | `src/graphdb/schema.py` | 완료 — 5단계의 canonical 소스 |
| 엔티티 스키마 설계 근거 | `data/laws/entity_schema_draft.md` | 완료 |
| edge_type 설계 근거 | `data/laws/edge_type_taxonomy_draft.md` | 완료 |
| AGE 연결/Cypher 실행 레이어 | `src/graphdb/config.py`/`connection.py`/`cypher.py` | 재사용 가능, 라벨 무관(값을 하드코딩 안 함) |
| GraphRAG 조회 헬퍼 | `src/graphdb/query/retrieval.py` | 재사용 가능(라벨을 파라미터로 받음) |
| 설계 히스토리(왜 지금 형태인지) | `data/laws/pipeline_design_log.md` | 참고용, 필수 아님 |

## 확정된 그래프 구조 — 엔티티 직접 연결, Article 노드 없음

```
(대통령:Organization)-[:APPOINTS {
    source_law: "감사원법", article_no: 4, paragraph_no: 1,
    condition: null, modality: "없음", voice: "능동"
}]->(원장:Organization)
```

조문(Article)은 노드가 아니라 엣지 속성(`source_law`/`article_no`/
`paragraph_no`)일 뿐이다 — 세 번 재설계 끝에 나온 결론(히스토리는
`pipeline_design_log.md` 참고). "제10조는 제5조를 준용한다" 같은 조문
간 참조도 별도 엣지가 아니라 **적재 시점 인용 전파**(제5조에서 뽑힌
관계들에 `article_no: 10`을 추가로 얹는 방식)로 처리한다. "정의차용"
같은 단순 인용은 스킵.

## svo.py가 이미 해결한 것 (재구현/재판단 금지)

svo.py는 아래를 전부 실제 법령 문장으로 검증하며 규칙화했다 — 5단계의
LLM이나 새 코드가 이걸 다시 판단하면 안 된다(특히 능동/피동 방향, 아래
"작업 스타일" 절 참고):
- **능동/피동 방향 정규화**: XSV 파생접미사가 "되다"/"받다"(피동)면
  agent/patient를 스왑, "~에 의하여" 행위자 명시구가 있으면 그걸 agent로.
- **목적어의 화제화(topicalization) 재배정**: JX(topic)와 JKS(subj)가
  한 문장에 둘 다 있으면 JKS가 진짜 주어, topic은 목적어로.
- **양상(의무/금지/재량) 판정**: 재량=`NNB(수)+VA(있)`(최우선),
  금지=`EC(지)+VX(아니하|못하)`, 의무=`EC(어야)+VX(하)`, 탐지 범위는
  다음 동사구 시작 전까지로 한정.
- **전방조응 주어 공유**: 문장 뒷부분에만 나오는 진짜 주어를 앞 절과
  공유(`_backfill_forward_subject`).

**아직 안 된 것** (5단계 표에서 규칙 우선/LLM 폴백으로 처리 예정):
조건절 텍스트 추출("제1항에도 불구하고" 등 → `condition` 속성), 위임조항
JKB 패턴("~은 대통령령으로 정한다"의 위임 대상 인식 — 현재 topic을
잘못 agent로 배정하는 버그 있음), 준용/적용 감지 + 인용 전파 규칙,
호/목 열거형 목적어 분리.

## 지금 당장 알아야 할 것: 폐기된 코드 (이미 삭제됨)

다음은 **LLM 기반 추출 + 범용 도메인 스키마(v1)** 시절 산출물이었다.
현재 NLP 파이프라인/새 3-store 파이프라인과 무관해 **이미 저장소에서
삭제했다**(git 히스토리에서 복구 가능) — 새 작업에서 재사용/재작성하지
말 것:

- `src/graphdb/schema.py`의 옛 내용(Company/Department/Regulation/
  ControlItem/Risk/Process 같은 범용 NodeLabel/EdgeLabel), `src/graphdb/models/entities.py`
  — schema.py는 이미 위 "확정된 산출물" 표의 새 스키마로 교체 완료.
  두 소스(entity_schema_draft.md/edge_type_mapping.jsonl)가 바뀌면
  schema.py도 손으로 같이 갱신해야 한다(자동 생성 스크립트는 아직 없음).
- `src/graphdb/ingest/document_extractor.py` — LLM(vLLM/Qwen)으로 문서
  전체에서 엔티티/관계를 자유형식으로 뽑던 코드. **삭제됨**, 재사용 안
  함(이번에 다시 LLM을 쓰지만 자유형식 추출이 아니라 "## 5단계"의
  좁게 스코프된 역할로만 씀 — 이 파일의 접근 방식을 참고하지 말 것).
- `src/graphdb/ingest/domain_loader.py`, `data/domain/sample_internal_control.yaml`,
  `scripts/seed_graph.py` — 위 범용 스키마용 샘플 데이터 로더. 삭제됨.
- `tests/test_schema.py`, `tests/test_domain_loader.py`,
  `tests/test_integration_graph.py` — 위 삭제 코드에 대한 테스트. 삭제됨.
- `src/graphdb/query/retrieval.py`의 `get_controls_for_risk` 함수 —
  옛 스키마(ControlItem/Risk/Regulation/Person 하드코딩)에 종속된
  도메인 전용 쿼리라 제거. 나머지 함수(`find_entity_id`/`get_subgraph`/
  `format_subgraph_as_context`/`get_context_for_rag`)는 라벨을 파라미터로
  받는 범용 코드라 그대로 재사용.

아직 실제로 그래프에 뭘 적재해본 적은 없음(파이프라인이 아직 그 단계
전) — RDB(PostgreSQL 17.10)/OpenSearch는 `docker-compose.yml`에 서비스
자체가 아직 없다("## 5단계" 참고, 추가 필요).

## 5단계: 엔티티 타이핑 + 3-store(RDB/AGE/OpenSearch) 적재 (다음 작업, 지침)

**스코프**: 지금은 실제 문서 API 연동 없이 `data/laws/raw/**/*.md`(60개
파일, 이미 로컬에 있음) 전체를 대상으로 오케스트레이션 스크립트를
완성하고 3-store에 적재하는 것까지가 목표. "문서를 API로 받는다"는
장기 방향은 맞지만, 지금 API가 없으니 API 클라이언트 추상화를 미리
만들지 말 것 — `data/laws/raw/` + `data/laws/manifest.json`을 그냥 직접
읽는 로더로 충분하고, 나중에 실제 문서 소스가 API로 바뀌면 그때 그
로더 함수만 교체하면 된다.

### 규칙 기반 vs LLM 역할 경계 (가장 중요 — 절대 흐리지 말 것)

이미 완성한 결정론적 파이프라인(형태소분석 → 어근 정규화 →
edge_type 매핑, 조/항 파싱 → SVO 추출)이 위 "svo.py가 이미 해결한 것"
절에 있는 **능동/피동 방향 정규화, 화제화된 목적어 재배정, 양상(의무/
금지/재량) 판정, 전방조응 주어 공유** 같은 어려운 문제를 이미 실제
법령 문장으로 검증하며 맞춰놨다(자세한 버그 히스토리는
`data/laws/pipeline_design_log.md` 참고). 이번에 LLM을 다시 들이는 이유는 "저게
어설프니 LLM으로 다시 뽑자"가 **아니라**, 애초에 규칙화가 안 맞는 두
영역(엔티티 타이핑, 소수의 판정불가 case)을 메우기 위해서다. 그래서
**LLM이 svo.py가 이미 정한 것을 재해석/역전시키는 일은 절대 없어야
한다** — 특히 사용자가 명시적으로 우려한 지점: *"수동/피동을 잘 잡고
있는데 LLM이 추출하면서 엣지가 이상한 방향으로 생기는" 상황을 만들지
말 것*.

구체적 역할 분담:

| 단계 | 무엇을 결정하나 | 담당 |
|---|---|---|
| 관계의 존재, agent/patient 배정, 능동/피동, 의무/금지/재량 | svo.py 출력 그대로 사용 | **규칙(고정, LLM 개입 금지)** |
| 어근 → edge_type(64개 중 하나) | `edge_type_mapping.jsonl` 사전 lookup (100% 매핑 완료) | **규칙(고정)** |
| `needs_context: true`인 두 어근("처분"→SANCTIONS/DISPOSES, "임면"→APPOINTS/DISMISSES 계열)의 edge_type 최종 선택 | svo.py가 뽑은 절 원문(agent/patient/목적어) 안에서 `edge_type_alt` 중 택1 — **자유 생성이 아니라 이미 정해진 2지선다 분류** | **LLM(좁은 분류만)** |
| AMBIGUOUS 버킷(하다/이루어지다/아니하다 등, verb_roots_ambiguous.jsonl) 문맥 해소 | 마찬가지로 문맥 보고 가장 적합한 edge_type을 **기존 64개 중에서만** 선택(신규 edge_type 발명 금지) | **LLM(좁은 분류만)** |
| agent/patient 표면 텍스트 → NodeLabel(4개) + category/role_hint/doc_type/concept_type | 고유명사(한국자산관리공사 등)·정부기관은 사전 매칭 우선, "해당 기관"/"소속 금융회사" 같은 문맥 의존 표현만 LLM | **사전 우선, LLM은 보강** |
| 동일 지시어 통합("금융위"="금융위원회"="금융감독위원회"[구 명칭]) | 별칭 사전 우선, 사전에 없는 후보만 LLM이 "같은 개체로 보이는지" 판정 | **사전 우선, LLM은 보강** |
| 조건절 텍스트 추출("제1항에도 불구하고", "~하는 경우에는") | 패턴이 정형적이라 우선 정규식/규칙, 규칙이 못 잡는 잔여만 LLM 폴백 | **규칙 우선, LLM은 폴백** |
| 새 문장에서 svo.py가 아예 SVO를 못 뽑아낸 경우(파싱 실패) | LLM으로 relation 자체를 새로 뽑을 수 있음 — 단, 반드시 `extraction_method` 필드에 다르게 표시(아래 RDB 스키마)해서 규칙 기반 결과와 절대 섞이지 않게 할 것 | **LLM 폴백(별도 표식 필수)** |

이 표에서 LLM이 손대는 항목은 전부 **"이미 정해진 후보 중에서 고르기"**
아니면 **"규칙이 커버 못하는 좁은 잔여"**다. "문서를 통째로 LLM에
넣고 엔티티/관계를 자유형식으로 뽑는" 방식(document_extractor.py가
하던 방식)은 쓰지 않는다 — structured output(pydantic 등)으로 출력
스키마 자체를 `NodeLabel`/`EdgeLabel`/`edge_type_alt` 후보로 강제해서,
LLM이 스키마 밖의 라벨을 만들어내는 것 자체를 구조적으로 막을 것.

**폐쇄망 이슈**: 이 프로젝트는 폐쇄망 이전 계획이 있다(과거 통계적
한국어 의존구문분석기(KLUE-DP) 도입을 기각한 이유이기도 함 —
`data/laws/pipeline_design_log.md` 참고). 클라우드 LLM API에 의존하는 설계는
나중에 다시 뜯어고쳐야 하므로, vLLM 등으로 자체 호스팅 가능한 오픈
가중치 모델(과거 document_extractor.py가 쓰던 Qwen 계열 등) 기준으로
설계할 것 — 이 프로젝트가 실제로 클라우드 LLM API를 쓸지, 사내에서
자체 호스팅할지는 아직 확정된 바 없으니 나중에 개발자와 상의할 것.

### 실행 체크리스트 (goal 모드 등 자율 작업용 — 순서/완료조건)

**절대 원칙**(위반 시 작업 중단하고 재검토 — 위 역할 분담표를 코드
차원에서 다시 한 줄로 요약한 것):
- `src/graphdb/nlp/`(morphology.py, law_structure.py, svo.py)의 로직은
  손대지 않는다. 버그를 발견해도 여기선 고치지 말고 별도로 보고만 한다.
- svo.py가 출력한 agent/patient/voice/modality는 그대로 쓴다 — LLM이
  이걸 재해석하거나 뒤집는 코드를 만들지 않는다.
- `schema.py`의 `NodeLabel`(4개)/`EdgeLabel`(64개)을 확장하거나 새
  라벨/타입을 만들지 않는다. 판단이 안 되는 case는 새 카테고리를
  만드는 대신 `extraction_method='llm_fallback'`으로 표시하고 넘어간다.

**구현 순서** (상세는 위 "코드 배치 제안"):
1. `src/graphdb/pipeline.py` — law_structure.py + svo.py + edge_type_mapping.jsonl 오케스트레이션.
2. `src/graphdb/typing/` — 엔티티 타이핑 + 동일지시어 통합(사전 우선, LLM 보강).
3. `src/graphdb/ingest/{rdb_loader,age_loader,opensearch_loader}.py` — RDB(SSOT) → AGE/OpenSearch 순서로 같은 id 재사용 적재.
4. `scripts/run_pipeline.py` — `data/laws/raw/**/*.md` 60개 파일 전체를 돌리는 진입점.

**LLM 엔드포인트**: 이 리포 밖 `.env.dev`의 `VLLM_BASE_URL`/`VLLM_API_KEY`
사용(위 "인프라 준비물" 참고). **주의(2026-08-15 확인)**: `.env.dev`에
적힌 `VLLM_MODEL_NAME=Qwen/Qwen3.6-35B-A3B-FP8`을 그대로 쓰면
`openai.NotFoundError: The model ... does not exist`(404)가 남 — 서버에
실제로 서빙 중인 모델 id가 그 값과 다르다. 하드코딩하지 말고 매 실행
시작 시 `client.models.list()`로 실제 모델 id를 조회해서 쓸 것.

**AMBIGUOUS 버킷 규모 주의**: `verb_roots_ambiguous.jsonl`의 "하다"
어근 하나가 9,287회로 그 버킷의 대부분을 차지한다(나머지 어근 합쳐도
200회 미만). 인스턴스 1건당 LLM 호출 1번씩 하면 호출 수가 과도해지므로
**반드시 배치(한 호출에 여러 절을 묶어 분류)로 처리**할 것 — 개별
호출로 짜면 사실상 못 끝낸다.

**DB 접속 정보**: `.env`(`.env.example` 복사본) 참고 — RDB
`localhost:5434`(rdb_admin/changeme/internal_control), AGE
`localhost:5433`, OpenSearch `localhost:9200`(보안 플러그인 꺼짐,
인증 불필요). 2026-08-15에 셋 다 기동/헬스체크 확인 완료.

**완료 조건**:
- `data/laws/raw/` 60개 파일 전체 처리.
- RDB `entity`/`relation` 테이블에 행 적재됨.
- AGE에 RDB와 동일한 `id`로 노드/엣지 생성됨.
- OpenSearch `entity`/`relation` 인덱스에 문서 색인됨.
- `extraction_method`별 건수를 로그로 출력(감사 추적용).
- `PYTHONPATH=src pytest tests/ -q` 계속 그린.

막히는 설계 판단은 임의로 새 규칙을 만들지 말고, CLAUDE.md에 없는
부분이면 `llm_fallback`으로 표시하고 계속 진행 — 중대한 애매함만 최종
보고에 별도로 남긴다.

### ID 스킴: RDB가 SSOT

- `document_id` / `entity_id` / `relation_id` 모두 UUID. **RDB가 이
  ID들의 발급 주체(SSOT)** — AGE/OpenSearch는 RDB가 만든 ID를 그대로
  재사용만 한다(AGE 노드/엣지의 `id` 속성, OpenSearch 문서의 `_id`).
- `entity_id`는 문서마다 새로 발급하지 않는다 — 엔티티 해석(위 표의
  "동일 지시어 통합")을 거쳐 기존 RDB `entity` 테이블에서 동일 개체를
  찾으면 그 id를 재사용하고, 못 찾을 때만 새 UUID를 발급한다. 그래야
  "금융위원회"가 여러 법령/조문에서 언급돼도 그래프에서 노드 하나로
  합쳐진다.
- `relation_id`는 매 추출 인스턴스(조/항 단위 SVO 1건)마다 새로
  발급한다(재사용/중복제거 없음) — 같은 두 엔티티 사이에 같은
  edge_type이 여러 조문에서 반복돼도 각각 별도 relation row/엣지로
  남긴다(그래야 `article_no`별 근거 추적이 유지된다).

### RDB 스키마 (PostgreSQL 17.10) — document/entity/relation 3개 테이블만

AGE처럼 라벨/edge_type별로 테이블을 쪼개지 않고 **entity 테이블 하나,
relation 테이블 하나로 통합**한다(타입은 컬럼으로만 구분). RDB는 모든
메타데이터와 문서 원문의 SSOT.

```
document(
  id UUID PK,
  source_law TEXT,            -- manifest.json의 법령명
  doc_type TEXT,               -- 법률/시행령/시행규칙/감사원규칙 등
  law_mst TEXT,                 -- 법령MST (manifest.json)
  promulgation_date DATE,       -- 공포일자
  enforcement_date DATE,        -- 시행일자
  competent_ministry TEXT,      -- 소관부처
  file_path TEXT,               -- data/laws/raw/... 상대경로
  raw_text TEXT,                -- 원문 전체
  created_at TIMESTAMPTZ
)

entity(
  id UUID PK,
  label TEXT,                   -- NodeLabel 중 하나 (Organization/Person/LegalDocument/Concept)
  name TEXT,                    -- 정규화된 엔티티명
  category TEXT, role_hint TEXT, doc_type TEXT, concept_type TEXT,  -- 라벨별 해당 필드만 채움
  aliases TEXT[],                -- 동일 지시어 통합 결과
  description TEXT,              -- AGE/OpenSearch로 그대로 나가는 요약
  created_at TIMESTAMPTZ
)

relation(
  id UUID PK,
  edge_type TEXT,                -- EdgeLabel 64개 중 하나
  source_entity_id UUID FK -> entity.id,
  target_entity_id UUID FK -> entity.id,
  document_id UUID FK -> document.id,
  source_law TEXT, article_no INT[], paragraph_no INT,  -- article_no는 인용 전파로 다중값 가능
  condition TEXT, modality TEXT, voice TEXT,
  evidence_text TEXT,            -- svo.py가 뽑은 원문 절
  extraction_method TEXT,        -- 'rule' | 'llm_disambiguation' | 'llm_fallback' (위 표의 담당 열과 매핑)
  created_at TIMESTAMPTZ
)
```

`extraction_method`는 컴플라이언스 감사 추적을 위해 필수 — "이 관계가
규칙으로 나왔는지 LLM 개입이 있었는지"를 나중에 항상 구분할 수 있어야
한다는 원칙(작업 스타일 섹션)을 지키는 최소 장치다.

### AGE 스키마 — 이미 확정된 구조 그대로 재사용

"그래프 구조" 절의 최종 확정 구조(엔티티 직접 연결, Article 노드 없음)를
그대로 쓴다. RDB와 달리 **AGE는 라벨/edge_type을 그대로 유지**한다(
`MATCH (n:Organization)` 식 쿼리가 라벨로 걸러지는 게 AGE의 장점이라
RDB/OpenSearch처럼 통합할 이유가 없음). 노드/엣지 속성은 RDB 전체가
아니라 **탐색·근거 확인에 필요한 최소한**만:
- 노드: `id`(RDB entity.id), `name`, 라벨별 category/role_hint/doc_type/concept_type,
  `description`.
- 엣지: `id`(RDB relation.id), `source_law`, `article_no`, `paragraph_no`,
  `condition`, `modality`, `voice`. (`evidence_text`/`extraction_method`
  같은 감사용 상세 필드는 RDB에만 두고 AGE엔 안 실음 — 그래프 순회
  성능/가독성 우선.)

### OpenSearch 스키마 — entity/relation 2개 인덱스, description 임베딩

RDB/AGE와 마찬가지로 라벨/edge_type별 인덱스 분리 없이 **entity 인덱스
하나, relation 인덱스 하나**로 통합.
- `entity` 인덱스: `id`(RDB entity.id), `name`, `label`(NodeLabel),
  `description`, `description_embedding`(dense_vector).
- `relation` 인덱스: `id`(RDB relation.id), `edge_type`, `description`
  (예: "감사원장이 감사원법 제4조에 따라 대통령에 의해 임명된다" 같은
  사람이 읽을 요약문 — svo.py 결과 template화해서 생성), `description_embedding`.

임베딩 모델 선정은 미착수 — 폐쇄망 이슈 때문에 자체 호스팅 가능한
모델(예: 다국어/한국어 sentence embedding 오픈 모델)을 우선 검토할 것,
OpenAI 등 외부 API 임베딩은 위 vLLM 이슈와 동일한 이유로 지양.

### 인프라 준비물 (완료, 2026-08-15)

- `docker-compose.yml`에 `rdb`(postgres:17.10, 호스트 포트 5434)와
  `opensearch`(2.18.0, 보안 플러그인 끈 단일 노드, 호스트 포트 9200)
  서비스 추가 완료. `age-db`와 별개 컨테이너(AGE 이미지는
  `apache/age:release_PG16_1.5.0`으로 PG16 고정이라 버전을 못 올림).
  `docker compose up -d age-db rdb opensearch`로 셋 다 기동, 2026-08-15에
  실제로 띄워서 헬스체크/`curl localhost:9200/_cluster/health`/RDB
  `\dt`/AGE `ag_graph` 조회까지 확인 완료.
  **함정**: OpenSearch 보안 플러그인은 `plugins.security.disabled` yml
  설정이 아니라 `DISABLE_SECURITY_PLUGIN` env var로 꺼야 한다(2.12+
  이미지의 entrypoint 스크립트가 이 var로 데모 보안 설치 자체를
  건너뜀 — yml 설정만 주면 `OPENSEARCH_INITIAL_ADMIN_PASSWORD` 없다고
  부팅이 계속 재시작 크래시남, 실제로 겪은 버그).
- `sql/init_rdb.sql`: 위 RDB 스키마(document/entity/relation) DDL,
  `sql/init_graph.sql`과 같은 방식으로 최초 기동 시 자동 실행됨.
- `src/graphdb/config.py`에 `RDBSettings`(`get_rdb_settings()`)/
  `OpenSearchSettings`(`get_opensearch_settings()`) 추가, `.env.example`에
  `RDB_DB_*`/`OPENSEARCH_*` 변수 추가. 기존 `GraphDBSettings`(AGE)는
  안 건드림.
- `requirements-graphdb.txt`에 `opensearch-py` 추가.
- **RDB/OpenSearch용 커넥션 래퍼(`RDBConnection`/OpenSearch 클라이언트
  헬퍼)는 아직 없음** — `connection.py`의 `GraphConnection`은 AGE 전용
  (`LOAD 'age'` 셋업 SQL을 매 커넥션에 실행). RDB는 plain psycopg pool,
  OpenSearch는 `opensearch-py` 클라이언트로 각각 얇은 래퍼가 필요하며
  이건 인프라가 아니라 `ingest/rdb_loader.py`/`ingest/opensearch_loader.py`
  구현의 일부로 취급할 것(아래 "코드 배치 제안" 참고).
- LLM 엔드포인트: 이 리포 밖 `.env.dev`(상위 프로젝트 공용 dev 시크릿
  파일, **git에 커밋 금지** — `.gitignore`에 추가해뒀음)에 이미
  `VLLM_BASE_URL`/`VLLM_API_KEY`/`VLLM_MODEL_NAME`(Qwen3.6-35B-A3B-FP8)
  이 있음. 자체 호스팅 vLLM이라 위 "폐쇄망 이슈" 방향과도 맞음 — 5단계
  LLM 호출(needs_context/AMBIGUOUS edge_type 분류, 엔티티 타이핑/별칭
  통합, svo.py 파싱 실패 폴백)은 새 키를 발급받지 말고 이 값을 그대로
  쓸 것.

### 코드 배치 제안 (디렉토리 정리 방향)

새 코드는 아래처럼 정리해서 넣을 것 — 기존 `nlp/`(2~4단계 결정론적
분석)와 새 추출/적재 로직을 분리해서, 나중에 "이게 규칙 기반인지 LLM
개입이 있는지"를 디렉토리만 보고도 알 수 있게 한다:

```
src/graphdb/
  nlp/              # 기존 그대로 (morphology/law_structure/svo) — 규칙 기반, 손 안 댐
  typing/           # 신규: 엔티티 타이핑 + 동일지시어 통합 (사전 우선 + LLM 보강)
  ingest/           # 신규: document/entity/relation → RDB/AGE/OpenSearch 로더
    rdb_loader.py
    age_loader.py
    opensearch_loader.py
  pipeline.py       # 신규: law_structure + svo + typing + edge_type_mapping 엮는 오케스트레이션
scripts/
  run_pipeline.py   # 신규: data/laws/raw/ 전체를 pipeline.py로 돌려 3-store에 적재하는 진입점
```

`ingest/`는 v1 폐기 코드(`document_extractor.py`/`domain_loader.py`)가
쓰던 이름이지만 삭제됐으니 이제 새 로더들이 그 자리를 쓰면 된다 —
"문서에서 뭔가를 만들어 그래프/DB에 넣는다"는 디렉토리 성격 자체는
유효해서 재사용.

## 환경/실행 방법

- Python 3.12 권장(Docker 기준), `pip install -r requirements-graphdb.txt`
  (이 세션에서 kiwipiepy 등 실제 설치·검증 완료 후 requirements 파일에
  반영함 — 이전에 빠져있었음, 확인 요망).
- `cp .env.example .env` 후 `docker compose up -d age-db` (AGE 그래프DB,
  아직 실사용 안 함).
- 형태소분석 재실행: `PYTHONPATH=src python scripts/analyze_verbs.py`
- 그룹핑 재실행: `python scripts/group_verbs.py`
- REF/DEF/STATIVE/ACTION 재분류: `PYTHONIOENCODING=utf-8 python scripts/classify_edge_roots.py`
  (Windows 콘솔 한글 깨짐 방지용으로 `PYTHONIOENCODING=utf-8` 필요)
- edge_type 매핑 재생성: `PYTHONIOENCODING=utf-8 python scripts/build_edge_type_mapping.py`
- 엔티티 명사 빈도 재스캔: `PYTHONIOENCODING=utf-8 python scripts/analyze_entities.py`
  → `data/laws/entity_noun_frequency.json`
- 이 세션에서 psycopg/psycopg-pool/pydantic-settings/kiwipiepy가 새
  환경에 안 깔려있어서 다시 설치함(`requirements-graphdb.txt` 그대로
  pip install) — `src/graphdb/__init__.py`가 nlp 서브모듈만 import해도
  psycopg까지 eager import하는 구조라, DB 연결 없이 NLP 코드만 테스트
  하려 해도 전체 스택이 설치돼 있어야 함(불편하지만 지금은 그대로 둠).
- 테스트: `PYTHONPATH=src pytest tests/ -q` (v1 폐기 코드 대상 테스트는
  삭제했음 — 이제 남은 테스트는 전부 현재 코드 대상, 2026-08-15 기준
  11개 그린). `pytest`/`pytest-asyncio`는 requirements-graphdb.txt에
  핀 돼있지만 이 세션 환경엔 안 깔려있어서 별도 설치함 — 확인 요망.

## 작업 스타일 관련 참고

이 프로젝트는 **관계(edge) 추출은 LLM을 쓰지 않고 결정론적 규칙으로
근거를 코드에 남기는 방식**을 고수해왔다(감사 추적 가능성이 이유,
verb_groups/edge_type 작업 전체가 이 원칙으로 진행됨). 새 규칙을
추가할 때는 왜 그렇게 판단했는지 주석/커밋 메시지에 남길 것.

**원칙 수정(엔티티 한정)**: 동사(닫힌 집합, ~1,500종)와 달리 명사/
엔티티는 개방집합이라 똑같은 전수 규칙화가 안 맞는다는 사용자 판단에
따라, **엔티티 스키마 설계와 엔티티 타이핑(문맥 의존적인 지시어 판정)
은 LLM 사용을 허용**한다. 단, **관계의 존재/agent·patient 방향/능동·
피동/의무·금지·재량은 여전히 결정론적 규칙(격조사+양상 태깅, svo.py)
으로 고정** — 이 경계(무엇이 LLM 허용이고 무엇이 아닌지)를 흐리지 말 것.

**원칙 재확인(2026-08-15, 3-store 파이프라인 설계 시 사용자가 명시적으로
강조)**: LLM을 다시 쓰는 이유가 "규칙 기반 결과가 부정확해서 대체한다"가
아니라 "규칙화가 원래 안 맞는 영역(엔티티 타이핑 등)을 메운다"는 것임을
절대 혼동하지 말 것. **svo.py가 이미 능동/피동을 정확히 구분해서 방향을
정규화해주고 있는데, LLM이 같은 문장을 다시 판단하다가 방향을 반대로
잘못 잡는 상황("엣지가 이상한 방향으로 생기는" 것)을 만들면 안 된다.**
그래서 LLM은 항상 (a) svo.py가 이미 만든 구조(agent/patient/voice/
modality)를 입력으로 받아 그 위에 얹는 좁은 판단(edge_type 소수 후보
중 택1, 엔티티 타입 부여, 별칭 통합)만 하거나, (b) svo.py가 아예 파싱에
실패한 문장에서만 폴백으로 동작해야 하고, 두 경우 모두 결과에
`extraction_method`로 규칙/LLM 여부를 남겨 감사 추적이 가능하게 한다
("## 5단계"의 역할 분담표와 RDB `relation.extraction_method` 참고).
