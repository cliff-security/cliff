"""The deterministic code_map resolver (SP2) — pure, keyless."""
from cliff.agents.triage_codemap import (
    _BUILTIN_BASENAME_GLOBS,
    _BUILTIN_TEST_SEGMENTS,
    _BUILTIN_VETOABLE_SEGMENTS,
    NONSHIP_CATEGORIES,
    _code_map_says_ships,
    _match_builtin,
    _strip_line_suffix,
    resolve_by_code_map,
)


def _cm(classified):
    return {"ships_roots": [], "excluded_roots": [], "classified": classified}


def test_clears_test_file_with_reason():
    # Use a non-builtin dir + non-builtin basename so Layer 2 (code_map) is exercised.
    cm = _cm([{"glob": "my_suite/**", "category": "test", "reason": "pytest suite"}])
    out = resolve_by_code_map({"location": "my_suite/signup_handler.py"}, cm)
    assert out is not None
    assert out.verdict == "false_positive"
    assert out.recommended_close == "false_positive"
    assert out.checks and "my_suite/**" in (out.checks[0].detail or "")
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
    # Non-builtin path + no code_map → None (no built-in match, no profile).
    assert resolve_by_code_map({"location": "src/app.py"}, None) is None
    # Non-builtin path + empty classified → None.
    assert resolve_by_code_map({"location": "src/app.py"}, _cm([])) is None
    # Empty location always → None.
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


def test_non_string_location_does_not_crash():
    """A truthy non-string `location` (e.g. a list or int from a malformed scanner
    payload) must not raise AttributeError on .strip() — the resolver falls through
    to None cleanly, never crashing triage."""
    for bad_loc in (123, [], {"path": "tests/x.py"}, True):
        result = resolve_by_code_map({"location": bad_loc}, None)
        assert result is None, f"expected None for location={bad_loc!r}, got {result!r}"
    # Also with a code_map entry that would otherwise match — still must not crash.
    cm = _cm([{"glob": "tests/**", "category": "test", "reason": "t"}])
    for bad_loc in (123, [], True):
        result = resolve_by_code_map({"location": bad_loc}, cm)
        assert result is None, f"expected None for location={bad_loc!r} with code_map"


def test_corrupt_classified_non_list_returns_none():
    # A corrupt code_map whose `classified` is a non-list scalar must not crash — fall through.
    # Use a non-builtin path so Layer 1 doesn't clear it; only Layer 2 is in play.
    for bad in (5, True, "x", {"glob": "src/**"}):
        cm = {"ships_roots": [], "excluded_roots": [], "classified": bad}
        assert resolve_by_code_map({"location": "src/handler.py"}, cm) is None


def test_non_hashable_category_does_not_crash():
    """A corrupt entry whose `category` is a non-hashable (list/dict) must not raise
    TypeError when tested against NONSHIP_CATEGORIES — the guard skips it cleanly.
    Uses a non-builtin path so Layer 1 doesn't fire; only Layer 2 is exercised."""
    for bad_category in (["test"], {"key": "val"}):
        cm = _cm([{"glob": "src/**", "category": bad_category, "reason": "x"}])
        result = resolve_by_code_map({"location": "src/handler.py"}, cm)
        assert result is None, f"expected None for category={bad_category!r}, got {result!r}"


def test_strip_line_suffix():
    assert _strip_line_suffix("pkg/users.test.ts:671") == "pkg/users.test.ts"
    assert _strip_line_suffix("hc/test.py:31:5") == "hc/test.py"
    assert _strip_line_suffix("hc/test.py") == "hc/test.py"
    assert _strip_line_suffix("lodash@4.17.21") == "lodash@4.17.21"  # no trailing :digits


def test_match_builtin_dir_segments():
    assert _match_builtin("app/tests/test_x.py") is not None      # tests/ segment
    assert _match_builtin("pkg/examples/demo.py") is not None      # examples/
    assert _match_builtin("src/app/handler.py") is None           # ships
    assert _match_builtin("app/latest/x.py") is None              # 'latest' != 'tests'


def test_match_builtin_basenames():
    assert _match_builtin("pkg/routers/users.test.ts") is not None  # *.test.ts
    assert _match_builtin("hc/test.py") is not None                 # test.py
    assert _match_builtin("a/b/foo_test.go") is not None            # *_test.go
    assert _match_builtin("src/testimony.py") is None               # no over-match
    assert _match_builtin("src/contest.py") is None


def test_code_map_says_ships_veto():
    cm = {
        "ships_roots": [],
        "classified": [{"glob": "examples/**", "category": "ships", "reason": "packaged"}],
    }
    assert _code_map_says_ships("examples/demo.py", cm) is True   # repo packages examples/
    assert _code_map_says_ships("tests/test_x.py", cm) is False
    assert _code_map_says_ships("examples/demo.py", None) is False
    assert _code_map_says_ships("x", {"ships_roots": ["src"], "classified": []}) is False
    assert _code_map_says_ships("src/app.py", {"ships_roots": ["src"], "classified": []}) is True


def test_builtin_constants_shape():
    assert "tests" in _BUILTIN_TEST_SEGMENTS and "fixtures" in _BUILTIN_TEST_SEGMENTS
    assert "examples" in _BUILTIN_VETOABLE_SEGMENTS and "docs" in _BUILTIN_VETOABLE_SEGMENTS
    # examples/docs are vetoable; tests/fixtures are never-veto — no cross-membership
    assert "examples" not in _BUILTIN_TEST_SEGMENTS
    assert "tests" not in _BUILTIN_VETOABLE_SEGMENTS
    assert "*.test.ts" in _BUILTIN_BASENAME_GLOBS and "test.py" in _BUILTIN_BASENAME_GLOBS


# ---------------------------------------------------------------------------
# Task 2 — integration tests for the two-layer resolve_by_code_map
# ---------------------------------------------------------------------------

def test_builtin_layer_clears_without_code_map():
    out = resolve_by_code_map({"location": "app/tests/test_login.py:42"}, None)
    assert out is not None and out.verdict == "false_positive"
    assert "non-ship" in (out.checks[0].detail or "").lower()


def test_builtin_layer_clears_test_basename_after_line_strip():
    out = resolve_by_code_map({"location": "packages/trpc/routers/users.test.ts:671"}, None)
    assert out is not None and out.verdict == "false_positive"


def test_ships_veto_overrides_builtin_clear():
    # The repo packages examples/ → profile marks it ships → built-in clear vetoed.
    cm = {"classified": [{"glob": "examples/**", "category": "ships", "reason": "in wheel"}]}
    assert resolve_by_code_map({"location": "examples/demo.py"}, cm) is None


def test_shipping_path_with_no_builtin_match_still_none():
    assert resolve_by_code_map({"location": "src/app/handler.py"}, None) is None


def test_existing_code_map_layer_still_works():
    cm = _cm([{"glob": "vendored_thing/**", "category": "test", "reason": "vendored test rig"}])
    assert resolve_by_code_map({"location": "vendored_thing/x.py"}, cm) is not None


def test_builtin_does_not_overmatch_shipping_lookalike():
    assert resolve_by_code_map({"location": "src/latest_release.py:10"}, None) is None
    assert resolve_by_code_map({"location": "src/contest.py"}, None) is None


def test_ships_roots_non_list_does_not_crash():
    # A corrupt code_map with ships_roots=int must not TypeError — treats it as no veto.
    assert _code_map_says_ships("x", {"ships_roots": 5}) is False
    assert _code_map_says_ships("x", {"ships_roots": "src"}) is False


# ---------------------------------------------------------------------------
# Category-aware ships-veto (fix: test-class paths NEVER vetoed)
# ---------------------------------------------------------------------------

def test_test_segment_under_coarse_ships_prefix_still_clears():
    """A coarse ships code_map (e.g. healthchecks ships_roots:['hc/'] + hc/**/*.py) must
    NOT veto a tests/ directory — test code never ships even under a ships prefix."""
    cm = {
        "ships_roots": ["hc/"],
        "classified": [{"glob": "hc/**/*.py", "category": "ships", "reason": "app"}],
    }
    out = resolve_by_code_map({"location": "hc/tests/test_x.py"}, cm)
    assert out is not None, "test-class dir under coarse ships prefix must still clear"
    assert out.verdict == "false_positive"


def test_examples_with_ships_classification_is_vetoed():
    """An examples/ path with an explicit ships classification is vetoed (can be packaged)."""
    cm = {"classified": [{"glob": "examples/**", "category": "ships", "reason": "in wheel"}]}
    assert resolve_by_code_map({"location": "examples/demo.py"}, cm) is None


def test_match_builtin_test_segment_not_vetoable():
    """_match_builtin returns vetoable=False for test-class dirs."""
    result = _match_builtin("app/tests/x.py")
    assert result is not None
    label, vetoable = result
    assert vetoable is False, "test-class dirs must never be vetoable"


def test_match_builtin_vetoable_segment_is_vetoable():
    """_match_builtin returns vetoable=True for examples/ (ambiguous/can ship)."""
    result = _match_builtin("pkg/examples/x.py")
    assert result is not None
    label, vetoable = result
    assert vetoable is True, "examples/ must be vetoable"


def test_test_segment_deeper_under_examples_is_never_vetoed():
    """examples/tests/x.py: tests/ segment (checked first) wins → never-veto."""
    cm = {"classified": [{"glob": "examples/**", "category": "ships", "reason": "in wheel"}]}
    out = resolve_by_code_map({"location": "examples/tests/test_x.py"}, cm)
    assert out is not None, "test-class segment takes priority over vetoable segment"


def test_examples_without_ships_classification_still_clears():
    """examples/ without a ships veto still clears (no code_map, or non-ships classify)."""
    out = resolve_by_code_map({"location": "examples/demo.py"}, None)
    assert out is not None and out.verdict == "false_positive"


def test_match_builtin_basename_not_vetoable():
    """Test-file basenames (*_test.py etc.) return vetoable=False."""
    result = _match_builtin("src/foo_test.py")
    assert result is not None
    label, vetoable = result
    assert vetoable is False, "test basenames are never vetoable"
