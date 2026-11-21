"""The lint rules. Each check takes a Plugin and yields Findings."""

import os
import re
from dataclasses import dataclass

from .source import blank, find_function, line_of

ERROR, WARNING, INFO = "error", "warning", "info"


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    line: int = 1


class Plugin:
    def __init__(self, path, design=None):
        self.path = path
        with open(path, encoding="utf-8", errors="replace") as f:
            self.src = f.read()
        self.code = blank(self.src)                       # comments and strings blanked
        self.code_s = blank(self.src, keep_strings=True)  # comments blanked, strings kept
        self.design = design                              # dump.lua output, or None

    def line(self, index):
        return line_of(self.src, index)

    def runtime_start(self):
        m = re.search(r"(?m)^[ \t]*if\s+Controls\s+then\b", self.code)
        return m.start() if m else None

    def line_of_literal(self, text, default=1):
        i = self.code_s.find('"' + text + '"')
        if i < 0:
            i = self.code_s.find("'" + text + "'")
        return self.line(i) if i >= 0 else default


RULES = {}


def rule(rule_id, summary):
    def wrap(fn):
        RULES[rule_id] = (summary, fn)
        return fn
    return wrap


# ------------------------------------------------------------------------------- structure

@rule("QL001", "Lua blocks, brackets and strings balance")
def check_balance(p):
    stack = []
    for t in re.finditer(r"\b(function|if|do|repeat|end|until)\b", p.code):
        w = t.group(1)
        if w in ("function", "if", "do", "repeat"):
            stack.append((w, t.start()))
        else:
            want = "repeat" if w == "until" else None
            if not stack:
                yield Finding("QL001", ERROR, f"'{w}' with nothing open to close", p.line(t.start()))
                return
            opened, at = stack.pop()
            if want and opened != "repeat":
                yield Finding("QL001", ERROR, f"'until' closes '{opened}' opened on line {p.line(at)}", p.line(t.start()))
                return
            if not want and opened == "repeat":
                yield Finding("QL001", ERROR, f"'end' closes 'repeat' opened on line {p.line(at)}; it needs 'until'", p.line(t.start()))
                return
    for opened, at in stack[-1:]:
        yield Finding("QL001", ERROR, f"'{opened}' is never closed", p.line(at))

    pairs = {")": "(", "]": "[", "}": "{"}
    brackets = []
    for m in re.finditer(r"[()\[\]{}]", p.code):
        c = m.group(0)
        if c in "([{":
            brackets.append((c, m.start()))
        elif not brackets or brackets[-1][0] != pairs[c]:
            yield Finding("QL001", ERROR, f"unmatched '{c}'", p.line(m.start()))
            return
        else:
            brackets.pop()
    for c, at in brackets[-1:]:
        yield Finding("QL001", ERROR, f"'{c}' is never closed", p.line(at))

    for m in re.finditer(r"(?m)([\"'])[^\n]*$", p.code):
        line = m.group(0)
        q = m.group(1)
        if line.count(q) % 2:
            # The blanker stops a quoted string at the end of its line, so an odd count is unterminated.
            yield Finding("QL001", ERROR, "string is not closed on its line", p.line(m.start()))
            return


@rule("QL002", "PluginInfo is present and complete")
def check_plugininfo(p):
    m = re.search(r"(?m)^[ \t]*PluginInfo\s*=\s*\{", p.code)
    if not m:
        yield Finding("QL002", ERROR, "no PluginInfo table: Designer cannot load the plugin without one")
        return
    line = p.line(m.start())
    info = (p.design or {}).get("PluginInfo")
    if isinstance(info, dict):
        fields = info
    else:
        end = p.code.find("}", m.end())
        body = p.code_s[m.end():end]
        fields = dict(re.findall(r"\b(\w+)\s*=\s*\"([^\"]*)\"", body))
        fields.update({k: True for k in re.findall(r"\b(\w+)\s*=", body) if k not in fields})
    for key in ("Name", "Version", "Id"):
        if not fields.get(key):
            yield Finding("QL002", ERROR, f"PluginInfo has no {key}", line)
    for key in ("Description", "Author"):
        if not fields.get(key):
            yield Finding("QL002", WARNING, f"PluginInfo has no {key}", line)
    version = fields.get("Version")
    if isinstance(version, str) and not re.fullmatch(r"\d+(\.\d+){1,3}", version):
        yield Finding("QL002", WARNING, f"PluginInfo.Version '{version}' is not a dotted number such as 1.2.0", line)
    pid = fields.get("Id")
    if isinstance(pid, str) and isinstance(version, str) and version and version in pid:
        yield Finding("QL002", WARNING,
                      f"PluginInfo.Id contains the version ({version}): Designer matches placed plugins by Id, "
                      "so each new version will need re-dragging instead of updating in place", line)
    name = fields.get("Name")
    if isinstance(name, str) and name.count("~") > 1:
        yield Finding("QL002", INFO, "PluginInfo.Name has more than one '~': only the first sets the User-tree folder", line)


@rule("QL003", "Designer's required functions are defined")
def check_functions(p):
    for name, sev in (("GetControls", ERROR), ("GetControlLayout", ERROR), ("GetProperties", INFO), ("GetPrettyName", INFO)):
        if not re.search(r"(?m)^[ \t]*function\s+" + name + r"\s*\(", p.code):
            msg = f"no {name}()"
            if sev == ERROR:
                msg += ": Designer needs it to place the plugin"
            yield Finding("QL003", sev, msg)
    if p.runtime_start() is None and re.search(r"\bControls\s*[.\[]", p.code):
        yield Finding("QL003", WARNING,
                      "runtime code is not inside `if Controls then ... end`: Designer runs the file without "
                      "Controls, so it will error at design time")


# ------------------------------------------------------------------------------- names

def declared_controls(p):
    """(names, complete): control names from the design dump, or literal names from GetControls."""
    if p.design and isinstance(p.design.get("controls"), list) and p.design["controls"]:
        return {c.get("Name") for c in p.design["controls"] if isinstance(c, dict)}, True
    span = find_function(p.code, "GetControls")
    if not span:
        return set(), False
    body = p.code_s[span[0]:span[1]]
    names = set(re.findall(r"\bName\s*=\s*\"([^\"]+)\"", body))
    dynamic = re.search(r"\bName\s*=\s*[^\"\s]", body) is not None
    return names, not dynamic


def referenced_controls(p):
    start = p.runtime_start() or 0
    code = p.code_s
    for m in re.finditer(r"\bControls\s*\.\s*([A-Za-z_]\w*)", code):
        if m.start() >= start:
            yield m.group(1), m.start()
    for m in re.finditer(r"\bControls\s*\[\s*([\"'])([^\"'\n]+)\1\s*\]", code):
        if m.start() >= start:
            yield m.group(2), m.start()


@rule("QL004", "Controls the runtime uses are declared in GetControls")
def check_control_refs(p):
    names, complete = declared_controls(p)
    seen = set()
    unresolved = 0
    for name, at in referenced_controls(p):
        if name in names or name in seen:
            continue
        seen.add(name)
        if complete:
            yield Finding("QL004", ERROR, f"Controls.{name} is used but GetControls never declares it", p.line(at))
        else:
            unresolved += 1
    if unresolved:
        yield Finding("QL004", INFO,
                      f"{unresolved} control reference(s) could not be checked: GetControls builds names at run time "
                      "(install lupa or put lua5.3 on PATH so the linter can run it)")


@rule("QL005", "Properties the runtime reads are declared in GetProperties")
def check_property_refs(p):
    if p.design and isinstance(p.design.get("properties"), list) and p.design["properties"]:
        names = {x.get("Name") for x in p.design["properties"] if isinstance(x, dict)}
    else:
        span = find_function(p.code, "GetProperties")
        if not span:
            names = set()
        else:
            names = set(re.findall(r"\bName\s*=\s*\"([^\"]+)\"", p.code_s[span[0]:span[1]]))
    start = p.runtime_start() or 0
    seen = set()
    for m in re.finditer(r"\bProperties\s*\[\s*([\"'])([^\"'\n]+)\1\s*\]", p.code_s):
        name = m.group(2)
        if m.start() < start or name in names or name in seen:
            continue
        seen.add(name)
        yield Finding("QL005", ERROR, f"Properties[\"{name}\"] is read but GetProperties never declares it", p.line(m.start()))


@rule("QL006", "No local function is used above the line that declares it")
def check_local_order(p):
    code = p.code
    forward = set(re.findall(r"(?m)^[ \t]*local\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*$", code))
    forward = {n.strip() for group in forward for n in group.split(",")}
    globals_ = set(re.findall(r"(?m)^[ \t]*function\s+([A-Za-z_]\w*)\s*\(", code))
    for m in re.finditer(r"\blocal\s+function\s+([A-Za-z_]\w*)", code):
        name = m.group(1)
        if name in forward or name in globals_:
            continue
        before = code[:m.start()]
        use = re.search(r"(?<![.:\w])" + re.escape(name) + r"\s*\(", before)
        if use:
            yield Finding("QL006", ERROR,
                          f"{name}() is called on line {p.line(use.start())} but declared `local` only on line "
                          f"{p.line(m.start())}: that call reaches a nil global", p.line(use.start()))


# ------------------------------------------------------------------------------- design dump

CONTROL_TYPES = {"Button", "Knob", "Indicator", "Text"}
BUTTON_TYPES = {"Momentary", "Toggle", "Trigger", "StateTrigger"}
INDICATOR_TYPES = {"Led", "Meter", "Text", "Status"}
PIN_STYLES = {"Input", "Output", "Both", "None"}
CONTROL_UNITS = {"dB", "Hz", "Float", "Integer", "Pan", "Percent", "Position", "Seconds"}
PROPERTY_TYPES = {"string", "integer", "double", "boolean", "enum"}
GRAPHIC_TYPES = {"GroupBox", "Label", "Text", "Header", "Image", "Svg", "MeterLegend"}


@rule("QL007", "Design-time functions run without errors")
def check_design_errors(p):
    if not p.design:
        return
    for e in p.design.get("errors", []):
        msg = e.get("message", "")
        m = re.search(r":(\d+):", msg)
        yield Finding("QL007", ERROR, f"{e.get('stage')} failed: {msg}", int(m.group(1)) if m else 1)


@rule("QL008", "Every control is well formed and named once")
def check_controls(p):
    if not p.design:
        return
    seen = {}
    for c in p.design.get("controls", []):
        if not isinstance(c, dict):
            continue
        name = c.get("Name")
        line = p.line_of_literal(str(name)) if name else 1
        if not name:
            yield Finding("QL008", ERROR, "a control has no Name", line)
            continue
        if name in seen:
            yield Finding("QL008", ERROR, f"control '{name}' is declared more than once", line)
        seen[name] = c
        ct = c.get("ControlType")
        if ct not in CONTROL_TYPES:
            yield Finding("QL008", ERROR, f"control '{name}': ControlType '{ct}' is not one of {sorted(CONTROL_TYPES)}", line)
        if ct == "Button" and c.get("ButtonType", "Momentary") not in BUTTON_TYPES:
            yield Finding("QL008", ERROR, f"control '{name}': ButtonType '{c.get('ButtonType')}' is not one of {sorted(BUTTON_TYPES)}", line)
        if ct == "Indicator" and c.get("IndicatorType") not in INDICATOR_TYPES:
            yield Finding("QL008", ERROR, f"control '{name}': IndicatorType '{c.get('IndicatorType')}' is not one of {sorted(INDICATOR_TYPES)}", line)
        if ct == "Knob":
            unit = c.get("ControlUnit")
            if unit not in CONTROL_UNITS:
                yield Finding("QL008", ERROR, f"control '{name}': Knob ControlUnit '{unit}' is not one of {sorted(CONTROL_UNITS)}", line)
            lo, hi = c.get("Min"), c.get("Max")
            if unit in ("Integer", "Float", "dB", "Hz", "Seconds") and (lo is None or hi is None):
                yield Finding("QL008", WARNING, f"control '{name}': Knob with ControlUnit {unit} has no Min/Max", line)
            elif isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo >= hi:
                yield Finding("QL008", ERROR, f"control '{name}': Min ({lo}) is not below Max ({hi})", line)
        ps = c.get("PinStyle")
        if ps is not None and ps not in PIN_STYLES:
            yield Finding("QL008", ERROR, f"control '{name}': PinStyle '{ps}' is not one of {sorted(PIN_STYLES)}", line)
        if c.get("UserPin") and ps in (None, "None"):
            yield Finding("QL008", WARNING, f"control '{name}': UserPin is set but PinStyle is {ps or 'missing'}, so no pin appears", line)
        count = c.get("Count")
        if count is not None and (not isinstance(count, int) or count < 1):
            yield Finding("QL008", ERROR, f"control '{name}': Count must be a whole number of 1 or more", line)


def layout_names(p):
    """Every layout key across pages, with Count>1 controls' 'Name 1' style keys mapped back."""
    out = {}
    for page in p.design.get("layouts", []):
        layout = page.get("layout")
        if isinstance(layout, dict):
            for key in layout:
                out.setdefault(key, page.get("page"))
    return out


@rule("QL009", "Layouts place only declared controls, and every control is placed")
def check_layout(p):
    if not p.design or not p.design.get("layouts"):
        return
    controls = {c.get("Name"): c for c in p.design.get("controls", []) if isinstance(c, dict)}
    placed = layout_names(p)
    pages = p.design.get("pages") or []

    def page_label(i):
        if isinstance(pages, list) and i and 0 < i <= len(pages) and isinstance(pages[i - 1], dict):
            return f"page '{pages[i - 1].get('name', i)}'"
        return f"page {i}"

    for key, page in placed.items():
        base = re.sub(r" \d+$", "", key)
        c = controls.get(key) or controls.get(base)
        if c is None:
            yield Finding("QL009", ERROR, f"{page_label(page)} lays out '{key}', which GetControls does not declare",
                          p.line_of_literal(key))
        elif key not in controls and (c.get("Count") or 1) < 2:
            yield Finding("QL009", ERROR, f"{page_label(page)} lays out '{key}', but '{base}' has no Count above 1",
                          p.line_of_literal(base))
    for name, c in controls.items():
        count = c.get("Count") or 1
        keys = [name] if count < 2 else [f"{name} {i}" for i in range(1, count + 1)]
        if not any(k in placed for k in keys) and not (count >= 2 and name in placed):
            pinned = c.get("UserPin") and c.get("PinStyle") not in (None, "None")
            if not pinned:
                yield Finding("QL009", INFO, f"control '{name}' is on no page and has no pin, so nothing can reach it",
                              p.line_of_literal(name))

    for page in p.design.get("layouts", []):
        layout = page.get("layout") if isinstance(page.get("layout"), dict) else {}
        for key, entry in layout.items():
            if not isinstance(entry, dict):
                continue
            for field in ("Position", "Size"):
                v = entry.get(field)
                if v is not None and not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)):
                    yield Finding("QL009", ERROR, f"{page_label(page.get('page'))}: '{key}' {field} must be {{x, y}}",
                                  p.line_of_literal(key))
        graphics = page.get("graphics") if isinstance(page.get("graphics"), list) else []
        for g in graphics:
            if isinstance(g, dict) and g.get("Type") not in GRAPHIC_TYPES:
                yield Finding("QL009", ERROR, f"{page_label(page.get('page'))}: graphic Type '{g.get('Type')}' is not one of {sorted(GRAPHIC_TYPES)}",
                              p.line_of_literal(str(g.get("Type"))))


@rule("QL010", "Properties are well formed")
def check_properties(p):
    if not p.design:
        return
    seen = set()
    for prop in p.design.get("properties", []):
        if not isinstance(prop, dict):
            continue
        name = prop.get("Name")
        line = p.line_of_literal(str(name)) if name else 1
        if not name:
            yield Finding("QL010", ERROR, "a property has no Name", line)
            continue
        if name in seen:
            yield Finding("QL010", ERROR, f"property '{name}' is declared more than once", line)
        seen.add(name)
        t = prop.get("Type")
        if t not in PROPERTY_TYPES:
            yield Finding("QL010", ERROR, f"property '{name}': Type '{t}' is not one of {sorted(PROPERTY_TYPES)}", line)
            continue
        v = prop.get("Value")
        if t == "enum":
            choices = prop.get("Choices")
            if not isinstance(choices, list) or not choices:
                yield Finding("QL010", ERROR, f"property '{name}': an enum needs Choices", line)
            elif v not in choices:
                yield Finding("QL010", ERROR, f"property '{name}': default '{v}' is not one of its Choices", line)
        if t in ("integer", "double"):
            lo, hi = prop.get("Min"), prop.get("Max")
            if isinstance(v, (int, float)) and isinstance(lo, (int, float)) and v < lo:
                yield Finding("QL010", ERROR, f"property '{name}': default {v} is below Min {lo}", line)
            if isinstance(v, (int, float)) and isinstance(hi, (int, float)) and v > hi:
                yield Finding("QL010", ERROR, f"property '{name}': default {v} is above Max {hi}", line)
            if t == "integer" and isinstance(v, float) and not v.is_integer():
                yield Finding("QL010", ERROR, f"property '{name}': integer default {v} has a fraction", line)


# ------------------------------------------------------------------------------- runtime habits

@rule("QL011", "The runtime avoids what a Core does not provide")
def check_runtime_apis(p):
    start = p.runtime_start() or 0
    bad = {
        r"\bio\s*\.\s*(open|popen|lines|read|write)\b": "io.{0} is not available to plugins on a Core",
        r"\bos\s*\.\s*(execute|exit|remove|rename|getenv|tmpname)\b": "os.{0} is not available to plugins on a Core",
        r"\b(socket)\s*\.\s*(tcp|udp|connect)\b": "LuaSocket is not on a Core: use TcpSocket / UdpSocket",
    }
    for pattern, msg in bad.items():
        for m in re.finditer(pattern, p.code):
            if m.start() >= start:
                yield Finding("QL011", WARNING, msg.format(m.group(1)), p.line(m.start()))
    for m in re.finditer(r"\bwhile\s+true\s+do\b", p.code):
        if m.start() >= start:
            yield Finding("QL011", WARNING,
                          "`while true do` blocks the plugin's only thread: use a Timer instead", p.line(m.start()))


@rule("QL012", "A .lua and .qplug pair are identical")
def check_pair(p):
    root, ext = os.path.splitext(p.path)
    other = root + (".qplug" if ext == ".lua" else ".lua")
    if ext in (".lua", ".qplug") and os.path.exists(other):
        with open(other, "rb") as a, open(p.path, "rb") as b:
            if a.read() != b.read():
                yield Finding("QL012", WARNING,
                              f"{os.path.basename(p.path)} and {os.path.basename(other)} differ: "
                              "the import and double-click installs would give different plugins")


def run(plugin, disabled=()):
    findings = []
    for rule_id, (_, fn) in sorted(RULES.items()):
        if rule_id in disabled:
            continue
        findings.extend(fn(plugin))
    # Silence lines marked `-- qsys-lint: ignore` or `-- qsys-lint: ignore QL004`.
    lines = plugin.src.split("\n")
    kept = []
    for f in findings:
        text = lines[f.line - 1] if 0 < f.line <= len(lines) else ""
        m = re.search(r"--\s*qsys-lint:\s*ignore\b([\w ,]*)", text)
        if m and (not m.group(1).strip() or f.rule in re.split(r"[\s,]+", m.group(1).strip())):
            continue
        kept.append(f)
    return sorted(kept, key=lambda f: (f.line, f.rule))
