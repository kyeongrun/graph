# 내부통제시스템 그래프DB (Apache AGE)

금융지주회사 내부통제시스템 RAG 프로젝트의 그래프DB 구성요소입니다.
별도 그래프 엔진 대신, 프로젝트가 이미 사용 중인 PostgreSQL 스택(`psycopg`/`asyncpg`)에
[Apache AGE](https://age.apache.org/) 확장을 얹어 하나의 DB에서 벡터/전문 검색(OpenSearch)과
그래프 탐색을 함께 운용하도록 설계했습니다.

## 아키텍처

- **그래프 엔진**: Apache AGE (PostgreSQL 16 확장, openCypher 지원)
- **그래프 모델**: 하이브리드
  - **도메인 그래프** (`source="domain"`): 조직(Company/Department/Person), 규정/법규
    (Regulation/Law), 통제항목(ControlItem), 리스크(Risk), 프로세스(Process)를 구조화된
    YAML(`data/domain/`)에서 적재. 컴플라이언스 추적/감사 대응에 강함.
  - **문서 지식그래프** (`source="document"`): 규정집·매뉴얼 원문을 LLM(vLLM 서버의
    Qwen3.6-27B)으로 엔티티/관계 추출 후 병합. 도메인 그래프와 이름 기반으로 엔티티를
    매칭하여 중복 노드 생성을 피함.
- **연결 계층**: `psycopg` 3 (async) + `psycopg-pool`. Cypher 쿼리는 AGE의 `cypher()` SQL
  함수를 통해 실행하며, 값은 항상 AGE 네이티브 파라미터(`$name`)로 바인딩합니다(문자열 조합 없음).

```
src/graphdb/
├── config.py              # AGE_DB_* 환경변수 설정 (pydantic-settings)
├── connection.py          # psycopg async pool, 연결마다 AGE LOAD/search_path 설정
├── cypher.py               # cypher() 실행 + agtype 파싱 + upsert 헬퍼
├── schema.py               # NodeLabel/EdgeLabel, 도메인 스키마 정의
├── models/entities.py       # 노드/엣지 pydantic 모델 (Company, Regulation, Risk, ...)
├── ingest/
│   ├── domain_loader.py     # 구조화 YAML -> 그래프 적재
│   └── document_extractor.py # LLM 기반 문서 -> 엔티티/관계 추출 및 병합
└── query/retrieval.py        # GraphRAG 조회 (서브그래프 조회, RAG 컨텍스트 포맷팅)
```

## 시작하기

```bash
cp .env.example .env
docker compose up -d age-db

python -m venv .venv && source .venv/bin/activate
pip install -r requirements-graphdb.txt

# PYTHONPATH에 src 추가 (또는 pip install -e . 로 패키지화)
export PYTHONPATH=src

# 샘플 도메인 데이터 적재
python scripts/seed_graph.py data/domain/sample_internal_control.yaml
```

## 사용 예시

### 도메인 데이터 적재

```python
from graphdb.connection import GraphConnection
from graphdb.ingest.domain_loader import load_domain_file
from pathlib import Path

conn = GraphConnection()
await conn.open()
stats = await load_domain_file(conn, Path("data/domain/sample_internal_control.yaml"))
print(stats.nodes_upserted, stats.edges_upserted, stats.errors)
```

### 문서에서 지식그래프 추출

```python
from graphdb.ingest.document_extractor import extract_from_chunk, merge_extraction_into_graph
from graphdb.models.entities import Document

result = await extract_from_chunk(chunk_text, )
doc = Document(id="doc-2025-internal-control", title="2025 내부통제기준 개정안", doc_type="규정집")
await merge_extraction_into_graph(conn, doc, chunk_id="chunk-0001", result=result)
```

### GraphRAG 조회 (RAG 프롬프트에 주입할 컨텍스트)

```python
from graphdb.query.retrieval import get_context_for_rag, get_controls_for_risk

async with conn.cursor() as cur:
    context = await get_context_for_rag(cur, "시스템 무단 접근 리스크")
    # (Risk) 시스템 무단 접근 리스크 -[MITIGATES]-> (ControlItem) 분기별 접근권한 검토
    # ...

    controls = await get_controls_for_risk(cur, "시스템 무단 접근 리스크")
    # [{"control": {...}, "regulation": {...}, "responsible_person": {...}}]
```

## 테스트

```bash
pip install -r requirements-graphdb.txt
PYTHONPATH=src pytest tests/ -q
```

DB가 필요 없는 순수 로직 테스트(`parse_agtype`, 스키마 검증, YAML 로더)는 기본으로 실행됩니다.
실제 AGE 인스턴스에 대한 통합 테스트는 기본적으로 스킵되며, 다음으로 활성화합니다:

```bash
docker compose up -d age-db
RUN_GRAPHDB_INTEGRATION_TESTS=1 PYTHONPATH=src pytest tests/test_integration_graph.py -q
```

## 스키마 확장하기

새 엔티티/관계 유형을 추가하려면:

1. `schema.py`의 `NodeLabel`/`EdgeLabel`에 값 추가
2. `models/entities.py`에 해당 pydantic 모델(또는 필드) 추가
3. LLM이 추출해도 되는 유형이면 `EXTRACTABLE_NODE_LABELS`에 등록
4. `data/domain/*.yaml`에 샘플 데이터 추가 후 `scripts/seed_graph.py`로 검증
