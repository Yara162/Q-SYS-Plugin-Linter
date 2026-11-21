"""Reading Lua source: blanking comments and strings while keeping line structure."""

import re

LONG_OPEN = re.compile(r"\[(=*)\[")


def blank(code, keep_strings=False):
    """Return `code` with comments (and, unless keep_strings, string contents) replaced by spaces.

    Newlines are kept, so line numbers and columns still match the original. String delimiters
    stay in place so `x = ""` still reads as an assignment.
    """
    out = []
    i, n = 0, len(code)

    def spaces(s):
        return re.sub(r"[^\n]", " ", s)

    while i < n:
        c = code[i]
        if code.startswith("--", i):
            m = LONG_OPEN.match(code, i + 2)
            if m:
                close = "]" + m.group(1) + "]"
                j = code.find(close, m.end())
                j = n if j < 0 else j + len(close)
            else:
                j = code.find("\n", i)
                j = n if j < 0 else j
            out.append(spaces(code[i:j]))
            i = j
            continue
        m = LONG_OPEN.match(code, i) if c == "[" else None
        if m:
            close = "]" + m.group(1) + "]"
            j = code.find(close, m.end())
            j = n if j < 0 else j + len(close)
            out.append(code[i:j] if keep_strings else m.group(0) + spaces(code[m.end():j - len(close)]) + close)
            i = j
            continue
        if c in "\"'":
            j = i + 1
            while j < n and code[j] != c and code[j] != "\n":
                j += 2 if code[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(code[i:j] if keep_strings else c + spaces(code[i + 1:j - 1]) + code[j - 1:j])
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def line_of(code, index):
    return code.count("\n", 0, index) + 1


def find_function(code, name):
    """(start, end) of `function NAME(...) ... end` in blanked code, or None."""
    m = re.search(r"(?m)^[ \t]*function\s+" + re.escape(name) + r"\s*\(", code)
    if not m:
        return None
    depth = 0
    for t in re.finditer(r"\b(function|if|do|repeat|end|until)\b", code[m.start():]):
        w = t.group(1)
        if w in ("function", "if", "do", "repeat"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.start(), m.start() + t.end()
    return m.start(), len(code)
