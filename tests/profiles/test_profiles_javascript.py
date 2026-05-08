import os
import pytest
import tempfile

from unittest.mock import patch

from swesmith.constants import ENV_NAME
from swesmith.profiles.javascript import (
    JavaScriptProfile,
    default_npm_install_dockerfile,
    parse_log_karma,
    parse_log_jasmine,
    parse_log_jest,
    parse_log_mocha,
    parse_log_vitest,
    parse_log_qunit,
    parse_log_tap,
    Githubreadmestats5df91f9b,
    Commanderjs8247364d,
    Color4fda9a3e,
)
from swebench.harness.constants import TestStatus


def make_dummy_js_profile():
    class DummyJSProfile(JavaScriptProfile):
        owner = "dummy"
        repo = "dummyrepo"
        commit = "deadbeefcafebabe"
        test_cmd = "npm test"

        @property
        def dockerfile(self):
            return "FROM node:18\nRUN echo hello"

        def log_parser(self, log):
            return {}

    return DummyJSProfile()


def _write_file(base, relpath, content):
    full = os.path.join(base, relpath)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)


def _make_profile_with_clone(tmp_path):
    profile = make_dummy_js_profile()

    def fake_clone(dest=None):
        return str(tmp_path), False

    profile.clone = fake_clone
    return profile


def _make_profile_with_cache(cache):
    profile = make_dummy_js_profile()
    profile._test_name_to_files_cache = cache
    return profile


def test_parse_log_karma_basic():
    log = """
Chrome Headless 137.0.0.0 (Linux x86_64): Executed 108 of 108 SUCCESS (0.234 secs / 0.215 secs)
"""
    result = parse_log_karma(log)
    assert len(result) == 108
    assert result["karma_unit_test_1"] == TestStatus.PASSED.value
    assert result["karma_unit_test_108"] == TestStatus.PASSED.value


def test_parse_log_karma_with_failures():
    log = "Chrome Headless 137.0.0.0 (Linux x86_64): Executed 95 of 100 SUCCESS (0.5 secs / 0.45 secs)\nChrome Headless 137.0.0.0 (Linux x86_64): Executed 100 of 100 (5 FAILED) (0.5 secs / 0.45 secs)"
    result = parse_log_karma(log)
    passed_count = sum(1 for v in result.values() if v == TestStatus.PASSED.value)
    failed_count = sum(1 for v in result.values() if v == TestStatus.FAILED.value)
    assert passed_count == 95
    assert failed_count == 5


def test_parse_log_karma_no_matches():
    log = """
Some random text
No test results here
"""
    result = parse_log_karma(log)
    assert result == {}


def test_parse_log_jasmine_basic():
    log = "426 specs, 0 failures"
    result = parse_log_jasmine(log)
    assert len(result) == 426
    assert result["jasmine_spec_1"] == TestStatus.PASSED.value
    assert result["jasmine_spec_426"] == TestStatus.PASSED.value


def test_parse_log_jasmine_with_failures():
    log = "100 specs, 5 failures"
    result = parse_log_jasmine(log)
    passed_count = sum(1 for v in result.values() if v == TestStatus.PASSED.value)
    failed_count = sum(1 for v in result.values() if v == TestStatus.FAILED.value)
    assert passed_count == 95
    assert failed_count == 5


def test_parse_log_jasmine_with_pending():
    log = """
100 specs, 2 failures, 3 pending specs
"""
    result = parse_log_jasmine(log)
    passed_count = sum(1 for v in result.values() if v == TestStatus.PASSED.value)
    failed_count = sum(1 for v in result.values() if v == TestStatus.FAILED.value)
    skipped_count = sum(1 for v in result.values() if v == TestStatus.SKIPPED.value)
    assert passed_count == 95
    assert failed_count == 2
    assert skipped_count == 3


def test_parse_log_jasmine_no_matches():
    log = """
Some random text
No test results here
"""
    result = parse_log_jasmine(log)
    assert result == {}


# --- Tests for default_npm_install_dockerfile and mirror_url usage ---


def test_default_npm_install_dockerfile_default_node():
    result = default_npm_install_dockerfile("https://github.com/org/repo")
    assert "FROM node:18-bullseye" in result
    assert f"git clone https://github.com/org/repo /{ENV_NAME}" in result
    assert "npm install" in result


def test_default_npm_install_dockerfile_custom_node():
    result = default_npm_install_dockerfile(
        "https://github.com/org/repo", node_version="22"
    )
    assert "FROM node:22-bullseye" in result


def test_default_npm_install_dockerfile_ssh_url():
    result = default_npm_install_dockerfile("git@github.com:org/repo.git")
    assert f"git clone git@github.com:org/repo.git /{ENV_NAME}" in result


def test_github_readme_stats_dockerfile_uses_mirror_url():
    profile = Githubreadmestats5df91f9b()
    with patch.object(type(profile), "_is_repo_private", return_value=False):
        dockerfile = profile.dockerfile
        assert f"https://github.com/{profile.mirror_name}" in dockerfile


def test_github_readme_stats_dockerfile_ssh_when_private():
    profile = Githubreadmestats5df91f9b()
    with patch.object(type(profile), "_is_repo_private", return_value=True):
        dockerfile = profile.dockerfile
        assert f"git@github.com:{profile.mirror_name}.git" in dockerfile


def test_commanderjs_uses_node_20():
    profile = Commanderjs8247364d()
    with patch.object(type(profile), "_is_repo_private", return_value=False):
        dockerfile = profile.dockerfile
        assert "FROM node:20-bullseye" in dockerfile
        assert f"https://github.com/{profile.mirror_name}" in dockerfile


def test_color_uses_node_22():
    profile = Color4fda9a3e()
    with patch.object(type(profile), "_is_repo_private", return_value=False):
        dockerfile = profile.dockerfile
        assert "FROM node:22-bullseye" in dockerfile
        assert f"https://github.com/{profile.mirror_name}" in dockerfile


def test_build_test_name_to_files_map_it_single_quotes(tmp_path):
    _write_file(
        tmp_path,
        "test/foo.test.js",
        "describe('foo', () => {\n  it('should work', () => {});\n});\n",
    )
    profile = _make_profile_with_clone(tmp_path)
    result = profile._build_test_name_to_files_map()
    assert "should work" in result
    assert "test/foo.test.js" in result["should work"]


def test_build_test_name_to_files_map_test_double_quotes(tmp_path):
    _write_file(
        tmp_path,
        "test/bar.test.js",
        'describe("bar", () => {\n  test("handles edge case", () => {});\n});\n',
    )
    profile = _make_profile_with_clone(tmp_path)
    result = profile._build_test_name_to_files_map()
    assert "handles edge case" in result
    assert "test/bar.test.js" in result["handles edge case"]


def test_build_test_name_to_files_map_backtick_template(tmp_path):
    _write_file(
        tmp_path,
        "test/baz.test.js",
        "it(`renders correctly`, () => {});\n",
    )
    profile = _make_profile_with_clone(tmp_path)
    result = profile._build_test_name_to_files_map()
    assert "renders correctly" in result


def test_build_test_name_to_files_map_it_only_and_skip(tmp_path):
    _write_file(
        tmp_path,
        "test/variants.test.js",
        "it.only('focused test', () => {});\nit.skip('skipped test', () => {});\n",
    )
    profile = _make_profile_with_clone(tmp_path)
    result = profile._build_test_name_to_files_map()
    assert "focused test" in result
    assert "skipped test" in result


def test_build_test_name_to_files_map_tests_dir(tmp_path):
    _write_file(
        tmp_path,
        "tests/unit/helper.js",
        "it('returns correct value', () => {});\n",
    )
    profile = _make_profile_with_clone(tmp_path)
    result = profile._build_test_name_to_files_map()
    assert "returns correct value" in result
    assert "tests/unit/helper.js" in result["returns correct value"]


def test_build_test_name_to_files_map_dunder_tests_dir(tmp_path):
    _write_file(
        tmp_path,
        "src/__tests__/util.test.js",
        "test('parses input', () => {});\n",
    )
    profile = _make_profile_with_clone(tmp_path)
    result = profile._build_test_name_to_files_map()
    assert "parses input" in result


def test_build_test_name_to_files_map_spec_file(tmp_path):
    _write_file(
        tmp_path,
        "src/utils.spec.ts",
        "it('formats date', () => {});\n",
    )
    profile = _make_profile_with_clone(tmp_path)
    result = profile._build_test_name_to_files_map()
    assert "formats date" in result
    assert "src/utils.spec.ts" in result["formats date"]


def test_build_test_name_to_files_map_non_test_files_ignored(tmp_path):
    _write_file(
        tmp_path,
        "src/lib.js",
        "// it('not a test', () => {});\nfunction helper() {}\n",
    )
    profile = _make_profile_with_clone(tmp_path)
    result = profile._build_test_name_to_files_map()
    assert "not a test" not in result


def test_build_test_name_to_files_map_node_modules_skipped(tmp_path):
    _write_file(
        tmp_path,
        "node_modules/pkg/test/foo.test.js",
        "it('should not match', () => {});\n",
    )
    profile = _make_profile_with_clone(tmp_path)
    result = profile._build_test_name_to_files_map()
    assert "should not match" not in result


def test_build_test_name_to_files_map_same_name_multiple_files(tmp_path):
    _write_file(tmp_path, "test/a.test.js", "it('works', () => {});\n")
    _write_file(tmp_path, "test/b.test.js", "it('works', () => {});\n")
    profile = _make_profile_with_clone(tmp_path)
    result = profile._build_test_name_to_files_map()
    assert "works" in result
    assert result["works"] == {"test/a.test.js", "test/b.test.js"}


def test_build_test_name_to_files_map_unreadable_file_skipped(tmp_path):
    _write_file(tmp_path, "test/good.test.js", "it('ok test', () => {});\n")
    bad_path = os.path.join(tmp_path, "test", "bad.test.js")
    with open(bad_path, "wb") as f:
        f.write(b"\x80\x81\x82\x83" * 100)
    profile = _make_profile_with_clone(tmp_path)
    result = profile._build_test_name_to_files_map()
    assert "ok test" in result


def test_build_test_name_to_files_map_cleanup_on_fresh_clone(tmp_path):
    src_dir = tmp_path / "repo"
    src_dir.mkdir()
    _write_file(str(src_dir), "test/x.test.js", "it('x', () => {});\n")

    profile = make_dummy_js_profile()

    def fake_clone(dest=None):
        return str(src_dir), True

    profile.clone = fake_clone

    with patch("swesmith.profiles.javascript.shutil.rmtree") as mock_rm:
        profile._build_test_name_to_files_map()
        mock_rm.assert_called_once_with(str(src_dir))


def test_build_test_name_to_files_map_typescript(tmp_path):
    _write_file(
        tmp_path,
        "test/feature.test.ts",
        "it('handles typescript', () => {});\n",
    )
    profile = _make_profile_with_clone(tmp_path)
    result = profile._build_test_name_to_files_map()
    assert "handles typescript" in result
    assert "test/feature.test.ts" in result["handles typescript"]


def test_get_test_files_basic_f2p_p2p():
    cache = {
        "should parse input": {"test/parser.test.js"},
        "should format output": {"test/formatter.test.js"},
        "handles errors": {"test/errors.test.js"},
    }
    profile = _make_profile_with_cache(cache)
    instance = {
        "instance_id": "dummy__dummyrepo.deadbeef.1",
        "FAIL_TO_PASS": ["should parse input"],
        "PASS_TO_PASS": ["should format output", "handles errors"],
    }
    f2p, p2p = profile.get_test_files(instance)
    assert set(f2p) == {"test/parser.test.js"}
    assert set(p2p) == {"test/formatter.test.js", "test/errors.test.js"}


def test_get_test_files_file_path_format():
    profile = _make_profile_with_cache({})
    instance = {
        "instance_id": "dummy__dummyrepo.deadbeef.1",
        "FAIL_TO_PASS": ["packages/svelte/tests/runtime-runes/test.ts"],
        "PASS_TO_PASS": ["packages/svelte/src/internal/client/proxy.test.ts"],
    }
    f2p, p2p = profile.get_test_files(instance)
    assert f2p == ["packages/svelte/tests/runtime-runes/test.ts"]
    assert p2p == ["packages/svelte/src/internal/client/proxy.test.ts"]


def test_get_test_files_missing_test_names():
    cache = {"exists": {"test/a.test.js"}}
    profile = _make_profile_with_cache(cache)
    instance = {
        "instance_id": "dummy__dummyrepo.deadbeef.1",
        "FAIL_TO_PASS": ["does not exist in cache"],
        "PASS_TO_PASS": ["also missing"],
    }
    f2p, p2p = profile.get_test_files(instance)
    assert f2p == []
    assert p2p == []


def test_get_test_files_cache_reuse():
    profile = make_dummy_js_profile()
    clone_count = 0

    def counting_clone(dest=None):
        nonlocal clone_count
        clone_count += 1
        d = tempfile.mkdtemp()
        return d, True

    profile.clone = counting_clone

    instance = {
        "instance_id": "dummy__dummyrepo.deadbeef.1",
        "FAIL_TO_PASS": ["test_a"],
        "PASS_TO_PASS": ["test_b"],
    }
    profile.get_test_files(instance)
    profile.get_test_files(instance)
    assert clone_count == 1


def test_get_test_files_assertion_error_on_missing_keys():
    profile = _make_profile_with_cache({})
    with pytest.raises(AssertionError):
        profile.get_test_files({"instance_id": "dummy__dummyrepo.deadbeef.1"})


def test_get_test_files_mixed_formats():
    cache = {"should work": {"test/unit.test.js"}}
    profile = _make_profile_with_cache(cache)
    instance = {
        "instance_id": "dummy__dummyrepo.deadbeef.1",
        "FAIL_TO_PASS": ["should work", "src/proxy.test.ts"],
        "PASS_TO_PASS": [],
    }
    f2p, _ = profile.get_test_files(instance)
    assert set(f2p) == {"test/unit.test.js", "src/proxy.test.ts"}


def test_parse_log_jest_basic():
    log = """
 PASS src/utils.test.js
  ✓ should add numbers (3ms)
  ✓ should subtract
  ✕ should multiply (5ms)
  ○ skipped test
"""
    result = parse_log_jest(log)
    assert result["should add numbers"] == "PASSED"
    assert result["should subtract"] == "PASSED"
    assert result["should multiply"] == "FAILED"
    assert result["skipped test"] == "SKIPPED"


def test_parse_log_mocha_basic():
    log = """
  ✓ should pass
  ✖ should fail (10ms)
  - pending test
"""
    result = parse_log_mocha(log)
    assert result["should pass"] == "PASSED"
    assert result["should fail"] == "FAILED"
    assert result["pending test"] == "SKIPPED"


def test_parse_log_mocha_numbered_failures():
    log = """
  ✓ passes fine
  1) first failure
  2) second failure
"""
    result = parse_log_mocha(log)
    assert result["passes fine"] == "PASSED"
    assert result["first failure"] == "FAILED"
    assert result["second failure"] == "FAILED"


def test_parse_log_mocha_ava_heavy_ballot_x():
    log = """
  ✔ ava passing test
  ✘ ava failing test (12ms)
"""
    result = parse_log_mocha(log)
    assert result["ava passing test"] == "PASSED"
    assert result["ava failing test"] == "FAILED"


def test_parse_log_vitest_basic():
    log = """
 ✓ tests/unit.test.ts (5 tests) 12ms
 ❯ tests/broken.test.ts (3 tests | 2 failed) 8ms
 ○ tests/skipped.test.ts
"""
    result = parse_log_vitest(log)
    assert result["tests/unit.test.ts"] == "PASSED"
    assert result["tests/broken.test.ts"] == "FAILED"
    assert result["tests/skipped.test.ts"] == "SKIPPED"


def test_parse_log_vitest_multiplication_sign():
    log = """
 ✓ passing test (2ms)
 × failing test (5ms)
 ○ skipped test
"""
    result = parse_log_vitest(log)
    assert result["passing test"] == "PASSED"
    assert result["failing test"] == "FAILED"
    assert result["skipped test"] == "SKIPPED"


def test_parse_log_vitest_indented():
    log = """
    ✓ deeply nested passing
    × deeply nested failing (3ms)
    ○ deeply nested skip
"""
    result = parse_log_vitest(log)
    assert result["deeply nested passing"] == "PASSED"
    assert result["deeply nested failing"] == "FAILED"
    assert result["deeply nested skip"] == "SKIPPED"


def test_parse_log_vitest_bun_format():
    log = """
 ✓ should handle bun pass
 ✗ should handle bun fail (4ms)
"""
    result = parse_log_vitest(log)
    assert result["should handle bun pass"] == "PASSED"
    assert result["should handle bun fail"] == "FAILED"


def test_parse_log_qunit_basic():
    log = """
TAP version 13
ok 1 - math addition works
ok 2 - math subtraction works
not ok 3 - math division by zero
ok 4 - string concat
"""
    result = parse_log_qunit(log)
    assert result["math addition works"] == "PASSED"
    assert result["math subtraction works"] == "PASSED"
    assert result["math division by zero"] == "FAILED"
    assert result["string concat"] == "PASSED"


def test_parse_log_qunit_skip_and_todo():
    log = """
ok 1 - works fine
ok 2 - skipped test # SKIP not implemented
not ok 3 - todo test # TODO fix later
"""
    result = parse_log_qunit(log)
    assert result["works fine"] == "PASSED"
    assert result["skipped test"] == "SKIPPED"
    assert result["todo test"] == "SKIPPED"


def test_parse_log_qunit_no_description():
    log = """
ok 1
not ok 2
ok 3
"""
    result = parse_log_qunit(log)
    assert result["test_1"] == "PASSED"
    assert result["test_2"] == "FAILED"
    assert result["test_3"] == "PASSED"


def test_parse_log_tap_basic():
    log = """
TAP version 13
ok 1 - should connect
not ok 2 - should handle errors
ok 3 - should disconnect
"""
    result = parse_log_tap(log)
    assert result["should connect"] == "PASSED"
    assert result["should handle errors"] == "FAILED"
    assert result["should disconnect"] == "PASSED"


def test_parse_log_tap_with_dash_separator():
    log = """
ok 1 - first test
not ok 2 - second test
ok 3 - third test # SKIP reason
"""
    result = parse_log_tap(log)
    assert result["first test"] == "PASSED"
    assert result["second test"] == "FAILED"
    assert result["third test"] == "SKIPPED"


def test_parse_log_tap_empty_log():
    result = parse_log_tap("")
    assert result == {}


def test_parse_log_qunit_jtr_format():
    """jtr (jquery-test-runner) outputs summary: 'X failed. Y passed. Z skipped.'"""
    log = """................
.....

Tests finished in 3.2s at http://localhost:9876/ in ChromeHeadless (120.0)...
2 failed. 43 passed. 1 skipped.
"""
    result = parse_log_qunit(log)
    assert len([k for k, v in result.items() if v == "PASSED"]) == 43
    assert len([k for k, v in result.items() if v == "FAILED"]) == 2
    assert len([k for k, v in result.items() if v == "SKIPPED"]) == 1


def test_parse_log_qunit_jtr_all_pass():
    log = """..............
Tests finished in 1.0s at http://localhost:9876/ in ChromeHeadless (120.0)...
0 failed. 10 passed. 0 skipped.
"""
    result = parse_log_qunit(log)
    assert len(result) == 10
    assert all(v == "PASSED" for v in result.values())
