#!/usr/bin/env python3
"""Fetch source law texts for data/laws/law_list.txt from a local checkout
of legalize-kr/legalize-kr (https://github.com/legalize-kr/legalize-kr),
which mirrors 국가법령정보센터 Open API data as one Markdown file per
법률/시행령/시행규칙, with YAML frontmatter metadata.

This is step 1 of the law knowledge-graph pipeline: acquire raw source
text before any NLP processing (형태소분석 -> 의존구문분석 -> ...) runs.

Usage:
    python scripts/fetch_laws.py /path/to/legalize-kr/legalize-kr
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

# Entries in law_list.txt whose text doesn't directly match a legalize-kr
# directory name after whitespace/punctuation normalization. Each mapping
# is a deliberate, recorded decision (not a silent fuzzy match) so every
# ingested law's source stays auditable.
ALIASES: dict[str, str] = {
    "감사원": "감사원법",  # 리스트의 기관명은 그 기관의 근거 법률로 해석
    "금융거래지표의관리에관한법류": "금융거래지표의관리에관한법률",  # 원본 리스트 오타(법류->법률)
}


def normalize(name: str) -> str:
    name = name.strip().replace(" ", "")
    name = name.replace("·", "ㆍ").replace(",", "ㆍ")
    return name


def parse_law_list(path: Path) -> list[tuple[int, str]]:
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        no, name = line.split("\t", 1)
        entries.append((int(no), name.strip()))
    return entries


def read_frontmatter(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    return yaml.safe_load(text[3:end]) or {}


def main(source_root: Path, list_path: Path, out_dir: Path) -> int:
    kr_dir = source_root / "kr"
    if not kr_dir.is_dir():
        print(f"'{kr_dir}' 를 찾을 수 없습니다 — legalize-kr 리포 루트 경로를 넘겨주세요", file=sys.stderr)
        return 1

    available = {normalize(d.name): d for d in kr_dir.iterdir() if d.is_dir()}
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    missing: list[list] = []

    for no, requested_name in parse_law_list(list_path):
        key = normalize(requested_name)
        key = ALIASES.get(key, key)
        source_dir = available.get(key)
        if source_dir is None:
            missing.append([no, requested_name])
            continue

        dest_dir = out_dir / source_dir.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        files_meta = []
        for md_file in sorted(source_dir.glob("*.md")):
            dest_file = dest_dir / md_file.name
            dest_file.write_text(md_file.read_text(encoding="utf-8"), encoding="utf-8")
            fm = read_frontmatter(md_file)
            files_meta.append(
                {
                    "file": md_file.name,
                    "법령구분": fm.get("법령구분"),
                    "법령MST": fm.get("법령MST"),
                    "법령ID": fm.get("법령ID"),
                    "공포일자": str(fm.get("공포일자")) if fm.get("공포일자") else None,
                    "시행일자": str(fm.get("시행일자")) if fm.get("시행일자") else None,
                    "소관부처": fm.get("소관부처"),
                    "상태": fm.get("상태"),
                }
            )

        manifest.append(
            {
                "no": no,
                "requested_name": requested_name,
                "matched_dir": source_dir.name,
                "alias_applied": requested_name.strip() != source_dir.name and key in ALIASES.values(),
                "files": files_meta,
            }
        )

    manifest_path = out_dir.parent / "manifest.json"
    manifest_path.write_text(
        json.dumps({"laws": manifest, "missing": missing}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total = len(manifest) + len(missing)
    file_count = sum(len(m["files"]) for m in manifest)
    print(f"매칭: {len(manifest)}/{total}건, 파일 {file_count}개")
    if missing:
        print("미매칭 항목:")
        for no, name in missing:
            print(f"  {no}. {name}")
    print(f"manifest: {manifest_path}")
    return 1 if missing else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    source = Path(sys.argv[1])
    list_file = Path(__file__).resolve().parent.parent / "data" / "laws" / "law_list.txt"
    output_dir = Path(__file__).resolve().parent.parent / "data" / "laws" / "raw"
    raise SystemExit(main(source, list_file, output_dir))
