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
    assert frozenset({"test", "fixture", "example", "docs"}) == NONSHIP_CATEGORIES


def test_build_and_vendored_categories_do_not_clear():
    # CI/build is a security surface; vendored code can ship — neither is auto-cleared.
    for cat, glob, path in [
        ("build", ".github/**", ".github/workflows/locale-sync.yml"),
        ("build", "scripts/**", "scripts/release.sh"),
        ("vendored", "vendor/**", "vendor/lib/thing.go"),
    ]:
        cm = _cm([{"glob": glob, "category": cat, "reason": "x"}])
        assert resolve_by_code_map({"location": path}, cm) is None, cat


def test_loose_infix_wildcard_glob_is_rejected():
    cm = _cm([{"glob": "*test*", "category": "test", "reason": "t"}])
    # 'latest'/'attestation' embed 'test' — must NOT clear (false-clear guard).
    assert resolve_by_code_map({"location": "latest_release.py"}, cm) is None
    assert resolve_by_code_map({"location": "src/attestation.py"}, cm) is None


def test_match_all_glob_never_clears():
    for bad in ("**", "*", "**/*"):
        cm = _cm([{"glob": bad, "category": "test", "reason": "t"}])
        assert resolve_by_code_map({"location": "src/app.py"}, cm) is None


def test_safe_forms_still_clear():
    for glob, path in [
        ("**/*_test.py", "pkg/foo_test.py"),
        ("test_*.py", "test_login.py"),
        ("*.spec.ts", "button.spec.ts"),
        ("tests/**", "tests/x.py"),
        ("examples", "examples/demo.py"),
    ]:
        cm = _cm([{"glob": glob, "category": "test", "reason": "t"}])
        assert resolve_by_code_map({"location": path}, cm) is not None, glob


def test_bare_dir_matches_nested_but_not_substring_segment():
    cm = _cm([{"glob": "tests", "category": "test", "reason": "t"}])
    assert resolve_by_code_map({"location": "app/pkg/tests/test_x.py"}, cm) is not None
    # 'latest' is a different segment that merely contains the name → must NOT match
    assert resolve_by_code_map({"location": "app/latest/x.py"}, cm) is None


def test_repeated_doublestar_matches_same_as_single():
    """**/**/*_test.py must match exactly the same paths as **/*_test.py.

    Verifies the consecutive-**/ collapse in _glob_to_regex — the dedup must
    not change matching results for valid inputs.
    """
    from cliff.agents.triage_codemap import _glob_to_regex

    doubled = _glob_to_regex("**/**/*_test.py")
    single = _glob_to_regex("**/*_test.py")
    paths = [
        "foo_test.py",
        "pkg/foo_test.py",
        "pkg/sub/foo_test.py",
        "a/b/c/foo_test.py",
        # should NOT match (wrong suffix)
        "pkg/foo_test_extra.py",
        "pkg/nottest.py",
    ]
    for p in paths:
        assert bool(doubled.match(p)) == bool(single.match(p)), f"mismatch on {p!r}"

    # Also confirm via the public API that a doubled glob clears the same path
    cm_doubled = _cm([{"glob": "**/**/*_test.py", "category": "test", "reason": "t"}])
    cm_single = _cm([{"glob": "**/*_test.py", "category": "test", "reason": "t"}])
    for loc in ("pkg/foo_test.py", "a/b/c/bar_test.py"):
        assert (
            resolve_by_code_map({"location": loc}, cm_doubled) is not None
        ), f"doubled glob missed {loc!r}"
        assert (
            resolve_by_code_map({"location": loc}, cm_single) is not None
        ), f"single glob missed {loc!r}"
