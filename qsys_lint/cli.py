"""Command line: qsys-lint [options] PLUGIN..."""

import argparse
import json
import os
import shutil
import subprocess
import sys

from . import __version__
from .checks import ERROR, INFO, RULES, WARNING, Plugin, run

DUMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dump.lua")
ORDER = {INFO: 0, WARNING: 1, ERROR: 2}


def run_design(path, lua=None):
    """Run the plugin's design-time functions and return what they produce, or (None, why)."""
    if lua != "none":
        exe = lua or next((shutil.which(n) for n in ("lua5.3", "lua53", "lua5.4", "lua") if shutil.which(n)), None)
        if exe:
            try:
                out = subprocess.run([exe, DUMP, path], capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired) as e:
                return None, f"{exe}: {e}"
            if out.returncode == 0 and out.stdout.strip():
                try:
                    return json.loads(out.stdout.strip().splitlines()[-1]), None
                except json.JSONDecodeError as e:
                    return None, f"could not read {exe}'s output: {e}"
            return None, (out.stderr.strip() or f"{exe} exited with {out.returncode}")
        try:
            from lupa import lua53  # optional
        except ImportError:
            return None, "no Lua found (put lua5.3 on PATH or pip install lupa)"
        rt = lua53.LuaRuntime()
        captured = []
        rt.globals().print = lambda *a: captured.append(" ".join(str(x) for x in a))
        rt.execute("arg = {}")
        rt.globals().arg[1] = path
        with open(DUMP, encoding="utf-8") as f:
            try:
                rt.execute(f.read())
            except Exception as e:  # lupa raises LuaError
                return None, str(e)
        return (json.loads(captured[-1]), None) if captured else (None, "dump produced nothing")
    return None, "design-time checks turned off (--lua none)"


def format_finding(path, f, fmt):
    if fmt == "github":
        level = {ERROR: "error", WARNING: "warning", INFO: "notice"}[f.severity]
        return f"::{level} file={path},line={f.line},title={f.rule}::{f.message}"
    return f"{path}:{f.line}: {f.severity} {f.rule} {f.message}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="qsys-lint", description="Check Q-SYS plugins (.qplug / .lua) for mistakes Designer would trip on.")
    ap.add_argument("plugins", nargs="*", help="plugin files to check")
    ap.add_argument("--format", choices=("text", "json", "github"), default="text")
    ap.add_argument("--disable", default="", help="comma-separated rule IDs to skip, e.g. QL011,QL012")
    ap.add_argument("--fail-on", choices=(ERROR, WARNING, INFO), default=ERROR,
                    help="lowest severity that makes the exit code 1 (default: error)")
    ap.add_argument("--lua", help="Lua interpreter for design-time checks; 'none' to skip them")
    ap.add_argument("--list-rules", action="store_true")
    ap.add_argument("--version", action="version", version=f"qsys-lint {__version__}")
    args = ap.parse_args(argv)

    if args.list_rules:
        for rid, (summary, _) in sorted(RULES.items()):
            print(f"{rid}  {summary}")
        return 0
    if not args.plugins:
        ap.error("give at least one plugin file")

    disabled = {r.strip().upper() for r in args.disable.split(",") if r.strip()}
    worst = -1
    report = []
    for path in args.plugins:
        design, why = run_design(path, args.lua)
        plugin = Plugin(path, design)
        findings = run(plugin, disabled)
        if design is None and args.format == "text":
            print(f"{path}: note: static checks only ({why})", file=sys.stderr)
        for f in findings:
            worst = max(worst, ORDER[f.severity])
            if args.format == "json":
                report.append({"file": path, **f.__dict__})
            else:
                print(format_finding(path, f, args.format))
        if args.format == "text":
            counts = {s: sum(1 for f in findings if f.severity == s) for s in (ERROR, WARNING, INFO)}
            print(f"{path}: {counts[ERROR]} error(s), {counts[WARNING]} warning(s), {counts[INFO]} note(s)")
    if args.format == "json":
        print(json.dumps(report, indent=2))
    return 1 if worst >= ORDER[args.fail_on] else 0


if __name__ == "__main__":
    sys.exit(main())
