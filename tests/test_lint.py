"""Run with: python -m unittest discover tests"""
import io
import json
import os
import unittest
from contextlib import redirect_stdout

from qsys_lint.checks import Plugin, run
from qsys_lint.cli import main, run_design

HERE = os.path.dirname(os.path.abspath(__file__))


def fixture(name):
    return os.path.join(HERE, "fixtures", name)


def lint(name, dynamic=True):
    path = fixture(name)
    design = run_design(path)[0] if dynamic else None
    return run(Plugin(path, design))


def rules_at(findings):
    return {(f.rule, f.line) for f in findings}


HAVE_LUA = run_design(fixture("good.qplug"))[0] is not None


class StaticChecks(unittest.TestCase):
    def test_good_plugin_is_clean(self):
        self.assertEqual(lint("good.qplug", dynamic=False), [])

    def test_bad_plugin_static(self):
        got = rules_at(lint("bad.qplug", dynamic=False))
        for expected in [("QL002", 2), ("QL006", 37), ("QL004", 39), ("QL005", 40), ("QL011", 41), ("QL011", 42)]:
            self.assertIn(expected, got)

    def test_id_with_version_is_flagged(self):
        msgs = [f.message for f in lint("bad.qplug", dynamic=False) if f.rule == "QL002"]
        self.assertTrue(any("contains the version" in m for m in msgs))

    def test_unbalanced_block(self):
        got = lint("unbalanced.lua", dynamic=False)
        self.assertIn(("QL001", 5), rules_at(got))

    def test_runtime_outside_guard(self):
        self.assertIn("QL003", {f.rule for f in lint("norun.lua", dynamic=False) if f.severity == "warning"})

    def test_pair_mismatch(self):
        self.assertIn("QL012", {f.rule for f in lint("pair.lua", dynamic=False)})

    def test_ignore_comment(self):
        p = Plugin(fixture("bad.qplug"))
        p.src = p.src.replace("helper()\n", "helper() -- qsys-lint: ignore QL006\n", 1)
        self.assertNotIn("QL006", {f.rule for f in run(p)})

    def test_strings_and_comments_do_not_confuse_blocks(self):
        from qsys_lint.source import blank
        code = 'x = "end if do" -- function\n--[[ if\nthen ]] y = [==[ do ]==]\n'
        out = blank(code)
        self.assertNotRegex(out, r"\b(end|if|do|function)\b")
        self.assertEqual(out.count("\n"), code.count("\n"))


@unittest.skipUnless(HAVE_LUA, "needs lua5.3 on PATH or the lupa package")
class DesignChecks(unittest.TestCase):
    def test_good_plugin_is_clean(self):
        self.assertEqual(lint("good.qplug"), [])

    def test_bad_plugin_design(self):
        got = rules_at(lint("bad.qplug"))
        for expected in [("QL010", 10), ("QL010", 11), ("QL008", 18), ("QL008", 19), ("QL008", 22),
                         ("QL009", 18), ("QL009", 21), ("QL009", 31), ("QL009", 32)]:
            self.assertIn(expected, got)

    def test_load_error_reported(self):
        self.assertIn("QL007", {f.rule for f in lint("unbalanced.lua")})

    def test_cli_exit_codes_and_json(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([fixture("good.qplug")]), 0)
            self.assertEqual(main([fixture("bad.qplug")]), 1)
            self.assertEqual(main(["--fail-on", "warning", fixture("pair.lua")]), 1)
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--format", "json", fixture("bad.qplug")])
        data = json.loads(buf.getvalue())
        self.assertTrue(all({"file", "rule", "severity", "message", "line"} <= set(d) for d in data))

    def test_github_format(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--format", "github", fixture("bad.qplug")])
        self.assertIn("::error file=", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
