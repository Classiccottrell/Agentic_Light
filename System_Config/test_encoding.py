#!/usr/bin/env python3
"""test_encoding.py -- AST-based lint enforcing CLAUDE.md's Cross-Platform
Constraints ("UTF-8 everywhere") across this workspace's own automation
layer. Windows' locale-default cp1252 both garbles UTF-8 text and crashes
outright on bytes like 0x81/0x8D/0x8F/0x90/0x9D (e.g. a real "curly quote"
character) -- this is a correctness bug, not a style nit.

Checks, per in-scope file:
  1. Every text-mode open()/os.fdopen()/Path.open() call passes
     encoding=. Binary modes ("b" in the mode string) are exempt.
  2. Every write-mode open()/os.fdopen() call ALSO passes newline=
     (any value -- pipeline/test_pipeline.py's .cmd shim deliberately
     wants newline="" for a literal CRLF terminator; this check only
     requires the kwarg's presence, not a specific value).
     write_text() is deliberately NOT checked for newline=:
     pathlib.Path.write_text()'s own `newline` parameter is Python
     3.10+ only and this repo's floor is 3.9 (CLAUDE.md Cross-Platform
     Constraints) -- passing it there would raise TypeError.
  3. Every .read_text()/.write_text() call passes encoding=.
  4. Every subprocess.run()/Popen()/check_output()/check_call()/call()
     call that requests text mode (text=True, universal_newlines=True,
     or an errors= kwarg -- all three put the subprocess module into
     text mode per its own docs) also passes encoding=.
  5. Every file containing `if __name__ == "__main__":` reconfigures
     both sys.stdout and sys.stderr to UTF-8 INSIDE that block -- never
     inside main() itself. healthcheck.py's _call_gen_main() imports
     gen_*.py in-process and redirects sys.stdout to a StringIO to
     capture --check/--dry-run output; a reconfigure() call reachable
     from main() would raise AttributeError there (StringIO has no
     such method).

Scope: every .py directly under System_Config/ or pipeline/ (recursive),
plus bootstrap.py and skills/skills.py -- this workspace's own automation
layer. Vendored skill payloads under skills/<dir>/ (everything except
skills/skills.py) are explicitly OUT of scope -- see CLAUDE.md.

Usage: python3 System_Config/test_encoding.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCOPE_DIRS = ("System_Config", "pipeline")
EXTRA_FILES = ("bootstrap.py", "skills/skills.py")

SUBPROCESS_CALL_NAMES = {"run", "Popen", "check_output", "check_call", "call"}


def iter_scope_files():
    files = []
    for d in SCOPE_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            files.append(p)
    for rel in EXTRA_FILES:
        files.append(ROOT / rel)
    return files


def _kwarg(call, name):
    for kw in call.keywords:
        if kw.arg == name:
            return kw
    return None


def _has_kwarg(call, name):
    return _kwarg(call, name) is not None


def _str_const(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _mode_value(call, pos_index):
    """Mode string for an open()-family call: the positional arg at
    pos_index, or the "mode" kwarg. Defaults the caller applies to "r"
    when this returns None (non-literal/absent mode -- text-read is
    Python's own default and the common case here)."""
    if len(call.args) > pos_index:
        return _str_const(call.args[pos_index])
    kw = _kwarg(call, "mode")
    if kw is not None:
        return _str_const(kw.value)
    return None


def _callee_name(call):
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        base = f.value
        if isinstance(base, ast.Name):
            return f"{base.id}.{f.attr}"
        return f.attr
    return "<call>"


class Checker(ast.NodeVisitor):
    def __init__(self, relpath):
        self.relpath = relpath
        self.violations = []

    def _flag(self, node, message):
        self.violations.append(f"{self.relpath}:{node.lineno}: {message}")

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Name):
            if f.id in ("open", "fdopen"):
                self._check_open_family(node, mode_index=1)
        elif isinstance(f, ast.Attribute):
            base = f.value
            base_name = base.id if isinstance(base, ast.Name) else None
            if f.attr in SUBPROCESS_CALL_NAMES and base_name == "subprocess":
                self._check_subprocess(node)
            elif f.attr == "fdopen":
                self._check_open_family(node, mode_index=1)
            elif f.attr == "open" and base_name != "os":
                # obj.open(...) -- e.g. Path.open(). Mode is the FIRST
                # positional arg (index 0): no leading file/fd argument
                # shifts it, unlike builtin open()/os.fdopen(). os.open()
                # (the raw fd-returning syscall wrapper, flags not a mode
                # string) is excluded.
                self._check_open_family(node, mode_index=0)
            elif f.attr in ("read_text", "write_text"):
                self._check_text_helper(node, f.attr)
        self.generic_visit(node)

    def _check_open_family(self, node, mode_index):
        mode = _mode_value(node, mode_index) or "r"
        if "b" in mode:
            return  # binary mode: exempt from both checks
        if not _has_kwarg(node, "encoding"):
            self._flag(node, f"{_callee_name(node)}() text mode missing encoding=")
        if any(c in mode for c in "wax+") and not _has_kwarg(node, "newline"):
            self._flag(node, f"{_callee_name(node)}() write mode missing newline=")

    def _check_text_helper(self, node, name):
        if not _has_kwarg(node, "encoding"):
            self._flag(node, f"{name}() missing encoding=")

    def _check_subprocess(self, node):
        text_mode = any(
            (kw.arg in ("text", "universal_newlines") and isinstance(kw.value, ast.Constant) and kw.value.value is True)
            or kw.arg == "errors"
            for kw in node.keywords
        )
        if text_mode and not _has_kwarg(node, "encoding"):
            self._flag(node, f"{_callee_name(node)}() text mode missing encoding=")


def _reconfigures(stmts, stream_name):
    for stmt in stmts:
        for node in ast.walk(stmt):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "reconfigure"):
                continue
            target = node.func.value
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                    and target.value.id == "sys" and target.attr == stream_name:
                return True
    return False


def _is_main_guard(test):
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)):
        return False
    operands = [test.left] + test.comparators
    names = {o.id for o in operands if isinstance(o, ast.Name)}
    consts = {o.value for o in operands if isinstance(o, ast.Constant)}
    return "__name__" in names and "__main__" in consts


def check_reconfigure(relpath, tree):
    violations = []
    for node in tree.body:  # __main__ guards are always top-level
        if isinstance(node, ast.If) and _is_main_guard(node.test):
            if not (_reconfigures(node.body, "stdout") and _reconfigures(node.body, "stderr")):
                violations.append(
                    f"{relpath}:{node.lineno}: if __name__ == '__main__' block missing "
                    "sys.stdout/sys.stderr.reconfigure(encoding=...)"
                )
    return violations


def check_file(path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    relpath = str(path.relative_to(ROOT))
    checker = Checker(relpath)
    checker.visit(tree)
    return checker.violations + check_reconfigure(relpath, tree)


def main():
    files = iter_scope_files()
    violations = []
    for path in files:
        violations.extend(check_file(path))

    if violations:
        print("test_encoding: FAILED -- UTF-8/newline/reconfigure violations found:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1
    print(f"test_encoding: PASS -- {len(files)} files clean")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
