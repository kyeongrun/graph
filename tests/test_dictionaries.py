from graphdb.typing.dictionaries import resolve_alias, strip_junk_prefix


def test_strip_junk_prefix_removes_known_filler():
    assert strip_junk_prefix("경우금융위원회") == "금융위원회"
    assert strip_junk_prefix("기간동안금융위원회") == "금융위원회"
    assert strip_junk_prefix("해당기간동안금융위원회") == "금융위원회"
    assert strip_junk_prefix("때금융위원회") == "금융위원회"
    assert strip_junk_prefix("등금융위원회") == "금융위원회"


def test_strip_junk_prefix_leaves_bare_canonical_name_alone():
    assert strip_junk_prefix("금융위원회") == "금융위원회"


def test_strip_junk_prefix_does_not_touch_suffix_variants():
    # These are genuinely different entities (an officeholder / a
    # different concept), not extraction junk — they have extra text
    # AFTER the canonical name, not glued in front of it.
    assert strip_junk_prefix("금융위원회위원장") == "금융위원회위원장"
    assert strip_junk_prefix("감사원장") == "감사원장"
    assert strip_junk_prefix("한국은행총재") == "한국은행총재"
    assert strip_junk_prefix("금융감독원장") == "금융감독원장"


def test_strip_junk_prefix_does_not_touch_unrelated_names():
    assert strip_junk_prefix("은행") == "은행"
    assert strip_junk_prefix("아무개회사") == "아무개회사"


def test_strip_junk_prefix_rejects_unknown_prefix():
    # a prefix that isn't in the curated junk list should NOT be stripped,
    # even though the string still ends with a canonical name — avoids
    # silently merging something that might be a real distinct name.
    assert strip_junk_prefix("제이금융위원회") == "제이금융위원회"


def test_resolve_alias_chains_junk_stripping_then_alias_map():
    # a junk-prefixed variant of an old/short name should resolve all the
    # way to the current canonical name in one call.
    assert resolve_alias("경우금융위원회") == "금융위원회"
    assert resolve_alias("금융위") == "금융위원회"
