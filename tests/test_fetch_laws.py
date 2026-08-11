import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fetch_laws import ALIASES, normalize, parse_law_list  # noqa: E402

LAW_LIST = Path(__file__).resolve().parent.parent / "data" / "laws" / "law_list.txt"
MANIFEST = Path(__file__).resolve().parent.parent / "data" / "laws" / "manifest.json"


def test_normalize_strips_spaces_and_unifies_middot():
    assert normalize("감사원 심사규칙") == "감사원심사규칙"
    assert normalize("자체감사활동의 지원 및 대행, 위탁감사에 관한 규칙") == normalize(
        "자체감사활동의지원및대행ㆍ위탁감사에관한규칙"
    )


def test_aliases_resolve_to_real_directory_names():
    # every alias target should itself already be a normalized (space-free) name
    for target in ALIASES.values():
        assert normalize(target) == target


def test_law_list_has_33_entries():
    entries = parse_law_list(LAW_LIST)
    assert len(entries) == 33
    numbers = [no for no, _ in entries]
    assert numbers == list(range(1, 34))


@pytest.mark.skipif(not MANIFEST.exists(), reason="run scripts/fetch_laws.py first")
def test_manifest_has_no_missing_laws():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["missing"] == []
    assert len(manifest["laws"]) == 33
