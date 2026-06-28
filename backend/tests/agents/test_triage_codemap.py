"""The deterministic code_map resolver (SP2) — pure, keyless."""
from cliff.agents.triage_codemap import NONSHIP_CATEGORIES, resolve_by_code_map


def _cm(classified):
    return {"ships_roots": [], "excluded_roots": [], "classified": classified}


def test_clears_test_file_with_reason():
    cm = _cm([{"glob": "tests/**", "category": "test", "reason": "pytest suite"}])
    out = resolve_by_code_map({"location": "tests/test_signup.py"}, cm)
    assert out is not None
    assert out.verdict == "false_positive"
    assert out.recommended_close == "false_positive"
    assert out.checks and "tests/**" in (out.checks[0].detail or "")
    assert "pytest suite" in (out.checks[0].detail or "")


def test_does_not_clear_ships_code():
    cm = _cm([{"glob": "src/**", "category": "ships", "reason": "app"}])
    assert resolve_by_code_map({"location": "src/app.py"}, cm) is None


def test_does_not_clear_dead_code():
    cm = _cm([{"glob": "old/**", "category": "dead", "reason": "unused"}])
    assert resolve_by_code_map({"location": "old/legacy.py"}, cm) is None


def test_no_match_falls_through():
    cm = _cm([{"glob": "tests/**", "category": "test", "reason": "t"}])
    assert resolve_by_code_map({"location": "src/app.py"}, cm) is None


def test_substring_near_miss_does_not_match():
    # 'contest.py' must NOT match a 'test' directory glob.
    cm = _cm([{"glob": "test/**", "category": "test", "reason": "t"}])
    assert resolve_by_code_map({"location": "src/contest.py"}, cm) is None


def test_filename_glob_matches_anywhere():
    cm = _cm([{"glob": "**/*_test.go", "category": "test", "reason": "go tests"}])
    assert resolve_by_code_map({"location": "pkg/sub/foo_test.go"}, cm) is not None


def test_empty_or_missing_inputs_return_none():
    assert resolve_by_code_map({"location": "tests/x.py"}, None) is None
    assert resolve_by_code_map({"location": "tests/x.py"}, _cm([])) is None
    assert resolve_by_code_map({}, _cm([{"glob": "tests/**", "category": "test"}])) is None


def test_nonship_categories_frozen():
    assert frozenset(
        {"test", "fixture", "example", "docs", "build", "vendored"}
    ) == NONSHIP_CATEGORIES
