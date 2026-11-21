# Q-SYS Plugin Linter

`qsys-lint` checks Q-SYS plugin files (`.qplug` or `.lua`) for mistakes that Designer or a Core
would otherwise show you one at a time: undeclared controls, layouts that place controls which don't
exist, broken property defaults, a local function called before it is declared, and more.

It runs in two passes:

1. **Static:** reads the source without running it. Always on, and needs nothing but Python.
2. **Design-time:** runs the plugin's own `GetProperties`, `GetControls`, `GetPages` and
   `GetControlLayout` with default properties (the way Designer does, with `Controls` unset) and
   checks what they return. This needs Lua 5.3, either `lua5.3` on your PATH or the `lupa` Python
   package. Without one, the linter falls back to static checks and tells you so.

```
$ qsys-lint my-plugin.qplug
my-plugin.qplug:18: error QL008 control 'Volume': Min (10) is not below Max (0)
my-plugin.qplug:31: error QL009 page 1 lays out 'Ghost', which GetControls does not declare
my-plugin.qplug:37: error QL006 helper() is called on line 37 but declared `local` only on line 38: that call reaches a nil global
my-plugin.qplug:39: error QL004 Controls.Mute is used but GetControls never declares it
my-plugin.qplug: 4 error(s), 0 warning(s), 0 note(s)
```

## Install

```bash
pip install "git+https://github.com/Yara162/Q-SYS-Plugin-Linter#egg=qsys-lint[lua]"
```

Or clone the repository and run `python3 -m qsys_lint` from its folder. There are no required
dependencies; `[lua]` adds `lupa` for the design-time pass.

## Use

```bash
qsys-lint plugin.qplug
```

| Option | What it does |
|---|---|
| `--format text\|json\|github` | `github` prints workflow annotations, so findings appear on the pull request's diff |
| `--fail-on error\|warning\|info` | Lowest severity that makes the exit code 1 (default `error`) |
| `--disable QL011,QL012` | Skip rules |
| `--lua PATH` | Lua interpreter to use; `--lua none` skips the design-time pass |
| `--list-rules` | Print the rules |

To silence one line, end it with `-- qsys-lint: ignore`, or `-- qsys-lint: ignore QL004` for one rule.

### In GitHub Actions

```yaml
- uses: actions/checkout@v4
- uses: Yara162/Q-SYS-Plugin-Linter@v0.1.0
  with:
    files: "*.qplug"
    fail-on: error
```

## Rules

| Rule | Checks | Pass |
|---|---|---|
| QL001 | `function`/`if`/`do`/`repeat` blocks, brackets and strings all close | static |
| QL002 | `PluginInfo` exists with Name, Version and Id (Description and Author warned); Version is dotted; the Id doesn't contain the version, which stops new versions updating placed copies | static |
| QL003 | `GetControls` and `GetControlLayout` exist; runtime code sits inside `if Controls then` | static |
| QL004 | Every `Controls.X` / `Controls["X"]` the runtime uses is declared | both |
| QL005 | Every `Properties["X"]` the runtime reads is declared | both |
| QL006 | No `local function` is called above the line that declares it | static |
| QL007 | The design-time functions run without raising errors | design |
| QL008 | Every control has a valid ControlType, ButtonType, IndicatorType, ControlUnit, PinStyle and Min < Max, and no name is used twice | design |
| QL009 | Each page's layout places only declared controls, with `{x, y}` Position and Size; graphics use known Types; every control is on a page or has a pin | design |
| QL010 | Every property has a valid Type, a default inside Min/Max, and an enum default that is one of its Choices | design |
| QL011 | The runtime avoids `io.*`, `os.execute`, LuaSocket and `while true do` | static |
| QL012 | A `.lua` and `.qplug` of the same name are byte-identical | static |

QL004 works statically only when `GetControls` uses literal names. When it builds them (for example
`"Gain " .. i`), the design-time pass is what makes the check complete.

## What it does not know

The lists of valid ControlTypes, ButtonTypes, layout graphic Types and so on come from Q-SYS's
published plugin documentation and from plugins that run on real Cores. They have not been checked
against every Designer version, so if the linter rejects something your Designer accepts, please
open an issue with the Designer version.

The design-time pass runs only with each property's default value. A layout that breaks only at,
say, 16 channels will not show up unless you change the default and lint again.

Checked against [Q-SYS Philips Hue](https://github.com/Yara162/Q-SYS-Philips-Hue) v1.5.0
(250 controls, 6 pages): no findings.

## Develop

```bash
python3 -m unittest discover -v tests
```

`tests/fixtures/bad.qplug` holds one of nearly every mistake, and the tests pin each finding to its line.

MIT License.
