-- RDB (PostgreSQL 17.10): document/entity/relation의 SSOT.
-- 스키마는 CLAUDE.md "5단계 > RDB 스키마" 절과 동기화해서 유지할 것.
-- entity.label 값은 src/graphdb/schema.py의 NodeLabel(4개), relation.edge_type
-- 값은 같은 파일의 EdgeLabel(64개)이 canonical — 여기서는 CHECK 제약으로
-- 강제하지 않는다(두 소스 손동기화 부담을 셋으로 늘리지 않기 위함).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS document (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_law          TEXT NOT NULL,          -- manifest.json의 법령명
    doc_type            TEXT NOT NULL,           -- 법률/시행령/시행규칙/감사원규칙 등
    law_mst             TEXT,                    -- 법령MST (manifest.json)
    promulgation_date   DATE,                    -- 공포일자
    enforcement_date    DATE,                    -- 시행일자
    competent_ministry  TEXT,                    -- 소관부처
    file_path           TEXT NOT NULL UNIQUE,    -- data/laws/raw/... 상대경로
    raw_text            TEXT NOT NULL,           -- 원문 전체
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entity (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label         TEXT NOT NULL,   -- NodeLabel: Organization/Person/LegalDocument/Concept
    name          TEXT NOT NULL,   -- 정규화된 엔티티명
    category      TEXT,            -- Organization 전용
    role_hint     TEXT,            -- Person 전용
    doc_type      TEXT,            -- LegalDocument 전용
    concept_type  TEXT,            -- Concept 전용
    aliases       TEXT[] NOT NULL DEFAULT '{}',  -- 동일 지시어 통합 결과
    description   TEXT,            -- AGE/OpenSearch로 그대로 나가는 요약
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_entity_label_name ON entity (label, name);

CREATE TABLE IF NOT EXISTS relation (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    edge_type          TEXT NOT NULL,   -- EdgeLabel 64개 중 하나
    source_entity_id   UUID NOT NULL REFERENCES entity (id),
    target_entity_id   UUID NOT NULL REFERENCES entity (id),
    document_id        UUID REFERENCES document (id),
    source_law         TEXT,
    article_no         INT[],   -- 인용 전파(준용/적용)로 다중값 가능
    paragraph_no       INT,
    condition          TEXT,
    modality           TEXT,    -- 의무 | 금지 | 재량 | 없음
    voice              TEXT,    -- 능동 | 피동
    evidence_text      TEXT,    -- svo.py가 뽑은 원문 절
    -- 'rule' | 'llm_disambiguation' | 'llm_fallback' — CLAUDE.md "5단계"의
    -- 규칙/LLM 역할 분담표와 매핑되는 감사 추적용 필드, 반드시 채울 것.
    extraction_method  TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_relation_source_entity ON relation (source_entity_id);
CREATE INDEX IF NOT EXISTS idx_relation_target_entity ON relation (target_entity_id);
CREATE INDEX IF NOT EXISTS idx_relation_edge_type ON relation (edge_type);
CREATE INDEX IF NOT EXISTS idx_relation_document ON relation (document_id);
