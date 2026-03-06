import streamlit as st
import ast
import subprocess
import sys
import tempfile
import os
import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Python Code Reviewer",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styles ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Remove default top padding */
.block-container { padding-top: 2rem; }

/* Hero banner */
.hero {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    border-radius: 16px;
    padding: 2rem 2.5rem;
    margin-bottom: 2rem;
    color: white;
}
.hero h1 { font-size: 2rem; font-weight: 700; margin: 0 0 .3rem 0; }
.hero p  { font-size: 1rem; opacity: .75; margin: 0; }

/* Metric cards */
.metric-row { display: flex; gap: 1rem; margin-bottom: 1.5rem; }
.metric-card {
    flex: 1;
    border-radius: 12px;
    padding: 1.1rem 1.4rem;
    color: white;
    font-weight: 600;
}
.mc-red   { background: linear-gradient(135deg,#c0392b,#e74c3c); }
.mc-amber { background: linear-gradient(135deg,#d35400,#e67e22); }
.mc-blue  { background: linear-gradient(135deg,#1a6496,#2980b9); }
.mc-green { background: linear-gradient(135deg,#1e8449,#27ae60); }
.metric-card .label { font-size: .78rem; opacity: .85; font-weight:500; }
.metric-card .value { font-size: 2rem; font-weight: 700; line-height: 1.1; }

/* Issue row */
.issue-row {
    display: flex;
    align-items: flex-start;
    gap: .9rem;
    border-radius: 10px;
    padding: .75rem 1rem;
    margin-bottom: .55rem;
    border-left: 4px solid;
}
.sev-error   { background:#fff0f0; border-color:#e74c3c; }
.sev-warning { background:#fff8f0; border-color:#e67e22; }
.sev-info    { background:#f0f4ff; border-color:#3498db; }

.badge {
    display: inline-block;
    border-radius: 6px;
    padding: 2px 9px;
    font-size: .72rem;
    font-weight: 700;
    white-space: nowrap;
    color: white;
    margin-right: 6px;
}
.badge-error   { background:#e74c3c; }
.badge-warning { background:#e67e22; }
.badge-info    { background:#3498db; }

.issue-source { font-size: .7rem; color: #888; }
.issue-msg    { font-size: .88rem; margin: .15rem 0 0; line-height: 1.4; }
.issue-line   { font-family: 'JetBrains Mono', monospace; font-size:.78rem; background:#eee; border-radius:4px; padding:1px 6px; margin-left:auto; white-space:nowrap; }

/* Section header */
.section-header {
    font-size: 1.1rem;
    font-weight: 700;
    color: #1a1a2e;
    margin: 1.4rem 0 .7rem;
    padding-bottom: .3rem;
    border-bottom: 2px solid #eee;
}

/* Code snippet */
.code-snippet {
    background: #1a1a2e;
    color: #e0e0e0;
    border-radius: 8px;
    padding: .9rem 1.2rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: .82rem;
    overflow-x: auto;
    margin-top: .5rem;
    white-space: pre;
}
.code-snippet .hl { background: rgba(231,76,60,.25); display:block; }

/* Tool pill */
.tool-pill {
    display: inline-block;
    background: #eef2ff;
    color: #3730a3;
    border-radius: 20px;
    padding: 3px 12px;
    font-size: .75rem;
    font-weight: 600;
    margin: 2px;
}
</style>
""", unsafe_allow_html=True)

# ── Data model ──────────────────────────────────────────────────────────────────
@dataclass
class Issue:
    severity: str          # "error" | "warning" | "info"
    source: str            # tool name
    line: Optional[int]
    col: Optional[int]
    code: str
    message: str

# ── AST custom checks ───────────────────────────────────────────────────────────

class ASTChecker(ast.NodeVisitor):
    """Hand-written checks that complement automated tools."""

    def __init__(self, source_lines: List[str]):
        self.issues: List[Issue] = []
        self.source_lines = source_lines
        self._assigned_names: set = set()
        self._used_names: set = set()

    # -- helpers
    def _add(self, severity, code, msg, node=None, line=None, col=None):
        ln = (node.lineno if node else None) if line is None else line
        cl = (node.col_offset if node else None) if col is None else col
        self.issues.append(Issue(severity=severity, source="AST-Custom",
                                 line=ln, col=cl, code=code, message=msg))

    # -- visit nodes
    def visit_Assign(self, node):
        for t in node.targets:
            if isinstance(t, ast.Name):
                self._assigned_names.add(t.id)
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self._used_names.add(node.id)
        self.generic_visit(node)

    def visit_Call(self, node):
        # Flag bare except with broad Exception swallowing
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        if node.type is None:
            self._add("warning", "W-BARE-EXCEPT",
                      "Bare `except:` catches everything including KeyboardInterrupt. "
                      "Prefer `except Exception as e:`.", node=node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        # Functions with no docstring
        if (not ast.get_docstring(node) and
                not node.name.startswith("_") and
                not node.name.startswith("test_")):
            self._add("info", "I-NO-DOCSTRING",
                      f"Function `{node.name}` has no docstring.", node=node)
        # Functions with too many arguments (> 6)
        args_count = len(node.args.args)
        if args_count > 6:
            self._add("warning", "W-TOO-MANY-ARGS",
                      f"Function `{node.name}` has {args_count} parameters. "
                      "Consider grouping into a config object.", node=node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        if not ast.get_docstring(node):
            self._add("info", "I-NO-DOCSTRING",
                      f"Class `{node.name}` has no docstring.", node=node)
        self.generic_visit(node)

    def check_long_lines(self):
        for i, line in enumerate(self.source_lines, start=1):
            stripped = line.rstrip("\n\r")
            if len(stripped) > 120:
                self._add("info", "I-LONG-LINE",
                          f"Line {i} is {len(stripped)} characters "
                          "(exceeds 120). Consider breaking it up.",
                          line=i, col=120)

    def check_bare_string_literals(self, tree):
        """Detect stray string literals that aren't docstrings or assignments."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    self._add("info", "I-STRAY-STRING",
                              "Stray string literal (not a docstring or assignment). "
                              "Did you mean to use a comment?", node=node)

    def check_mutable_defaults(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults + node.args.kw_defaults:
                    if default and isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        self._add("warning", "W-MUTABLE-DEFAULT",
                                  f"Mutable default argument in `{node.name}`. "
                                  "Use `None` and initialise inside the function.",
                                  node=node)

    def check_print_statements(self, tree):
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Name) and
                    node.func.id == "print"):
                self._add("info", "I-PRINT",
                          "Found `print()` statement. "
                          "Replace with `logging` in production code.",
                          node=node)

    def check_hardcoded_secrets(self):
        secret_patterns = re.compile(
            r'(?i)(password|secret|api[_\-]?key|token|passwd)\s*=\s*["\'][^"\']{4,}["\']'
        )
        for i, line in enumerate(self.source_lines, start=1):
            if secret_patterns.search(line) and not line.strip().startswith("#"):
                self._add("error", "E-HARDCODED-SECRET",
                          "Possible hardcoded secret/credential in source. "
                          "Use environment variables or a secrets manager.",
                          line=i, col=0)


def run_ast_checks(source: str, source_lines: List[str]) -> List[Issue]:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [Issue(severity="error", source="AST-Syntax",
                      line=e.lineno, col=e.offset, code="E-SYNTAX",
                      message=f"SyntaxError: {e.msg}")]

    checker = ASTChecker(source_lines)
    checker.visit(tree)
    checker.check_long_lines()
    checker.check_bare_string_literals(tree)
    checker.check_mutable_defaults(tree)
    checker.check_print_statements(tree)
    checker.check_hardcoded_secrets()
    return checker.issues


# ── Pyflakes ────────────────────────────────────────────────────────────────────

def run_pyflakes(source: str) -> List[Issue]:
    try:
        from pyflakes import api as pf_api
        from pyflakes import checker as pf_checker
        import io, tokenize as tk

        result = []

        class _WarningCollector:
            def __init__(self):
                self.warnings = []
            def flake(self, warning):
                self.warnings.append(warning)

        try:
            tree = compile(source, "<string>", "exec", ast.PyCF_ONLY_AST)
        except SyntaxError:
            return []

        w = pf_checker.Checker(tree, "<string>")
        for msg in w.messages:
            sev = "warning"
            if "undefined name" in msg.message % msg.message_args:
                sev = "error"
            result.append(Issue(
                severity=sev,
                source="pyflakes",
                line=msg.lineno,
                col=msg.col,
                code="PF",
                message=msg.message % msg.message_args,
            ))
        return result
    except ImportError:
        return [Issue(severity="info", source="pyflakes", line=None, col=None,
                      code="MISSING", message="`pyflakes` is not installed. "
                      "Run: pip install pyflakes")]


# ── Pylint ──────────────────────────────────────────────────────────────────────

def run_pylint(source: str) -> List[Issue]:
    try:
        import pylint  # noqa: F401
    except ImportError:
        return [Issue(severity="info", source="pylint", line=None, col=None,
                      code="MISSING", message="`pylint` is not installed. "
                      "Run: pip install pylint")]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                     delete=False, encoding="utf-8") as f:
        f.write(source)
        tmp = f.name

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pylint", tmp,
             "--output-format=json",
             "--disable=C0114,C0115,C0116,R0903,W0212",  # suppress some noisy ones handled by AST
             "--max-line-length=120"],
            capture_output=True, text=True, timeout=30
        )
        raw = result.stdout.strip()
        if not raw:
            return []
        data = json.loads(raw)
        issues = []
        for item in data:
            sev_map = {"error": "error", "warning": "warning",
                       "refactor": "info", "convention": "info", "fatal": "error"}
            issues.append(Issue(
                severity=sev_map.get(item.get("type", "info"), "info"),
                source="pylint",
                line=item.get("line"),
                col=item.get("column"),
                code=item.get("message-id", ""),
                message=f"[{item.get('symbol', '')}] {item.get('message', '')}",
            ))
        return issues
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        return [Issue(severity="info", source="pylint", line=None, col=None,
                      code="ERR", message=f"pylint run failed: {e}")]
    finally:
        os.unlink(tmp)


# ── Rendering helpers ───────────────────────────────────────────────────────────

SEV_ORDER = {"error": 0, "warning": 1, "info": 2}

def render_metric_cards(issues: List[Issue]):
    errors   = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")
    infos    = sum(1 for i in issues if i.severity == "info")
    score    = max(0, 10 - errors * 2 - warnings * 0.5 - infos * 0.1)

    st.markdown(f"""
    <div class="metric-row">
      <div class="metric-card mc-red">
        <div class="label">🔴 Errors</div>
        <div class="value">{errors}</div>
      </div>
      <div class="metric-card mc-amber">
        <div class="label">🟠 Warnings</div>
        <div class="value">{warnings}</div>
      </div>
      <div class="metric-card mc-blue">
        <div class="label">🔵 Info</div>
        <div class="value">{infos}</div>
      </div>
      <div class="metric-card mc-green">
        <div class="label">⭐ Score / 10</div>
        <div class="value">{score:.1f}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


def render_issue(issue: Issue, source_lines: List[str]):
    sev_class = f"sev-{issue.severity}"
    badge_class = f"badge-{issue.severity}"
    badge_label = issue.severity.upper()
    line_tag = f'<span class="issue-line">L{issue.line}</span>' if issue.line else ""

    # Snippet
    snippet_html = ""
    if issue.line and source_lines:
        idx = issue.line - 1
        start = max(0, idx - 1)
        end = min(len(source_lines), idx + 2)
        lines_html = ""
        for li, ln in enumerate(source_lines[start:end], start=start + 1):
            esc = ln.rstrip("\n\r").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            cls = ' class="hl"' if li == issue.line else ""
            lines_html += f'<span{cls}>{li:3d}  {esc}</span>\n'
        snippet_html = f'<div class="code-snippet">{lines_html}</div>'

    st.markdown(f"""
    <div class="issue-row {sev_class}">
      <div style="flex:1;">
        <div>
          <span class="badge {badge_class}">{badge_label}</span>
          <span class="badge" style="background:#555;">{issue.code}</span>
          <span class="issue-source">{issue.source}</span>
          {line_tag}
        </div>
        <div class="issue-msg">{issue.message}</div>
        {snippet_html}
      </div>
    </div>
    """, unsafe_allow_html=True)


# ── Main app ────────────────────────────────────────────────────────────────────

def main():
    # Hero
    st.markdown("""
    <div class="hero">
      <h1>🔍 Python Code Reviewer</h1>
      <p>Static analysis powered by AST Custom Checks · pyflakes · pylint</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Sidebar ──
    with st.sidebar:
        st.header("⚙️ Options")
        show_errors   = st.checkbox("Show Errors",   value=True)
        show_warnings = st.checkbox("Show Warnings", value=True)
        show_infos    = st.checkbox("Show Info",     value=True)
        st.divider()
        run_pylint_check   = st.checkbox("Run pylint",   value=True)
        run_pyflakes_check = st.checkbox("Run pyflakes", value=True)
        run_ast_check      = st.checkbox("Run AST custom checks", value=True)
        st.divider()
        st.caption("Upload a `.py` file or paste code in the main panel.")

    # ── Source input ──
    tab_upload, tab_paste, tab_default = st.tabs(
        ["📂 Upload File", "✏️ Paste Code", "📄 Use dashboard.py"]
    )

    source: Optional[str] = None
    filename = "code.py"

    with tab_upload:
        uploaded = st.file_uploader("Choose a Python file", type=["py"])
        if uploaded:
            source = uploaded.read().decode("utf-8", errors="replace")
            filename = uploaded.name

    with tab_paste:
        pasted = st.text_area("Paste Python code here", height=280,
                              placeholder="# paste your code...")
        if pasted.strip():
            source = pasted
            filename = "pasted_code.py"

    with tab_default:
        default_path = Path(__file__).parent / "dashboard.py"
        if default_path.exists():
            st.info(f"Will analyse: `{default_path}`")
            if st.button("▶️ Analyse dashboard.py"):
                source = default_path.read_text(encoding="utf-8")
                filename = "dashboard.py"
        else:
            st.warning("dashboard.py not found next to this script.")

    if source is None:
        st.markdown("""
        <div style="text-align:center;padding:3rem;color:#999;">
          <div style="font-size:3rem;">📂</div>
          <p>Upload a file, paste code, or click <strong>Analyse dashboard.py</strong> to begin.</p>
        </div>
        """, unsafe_allow_html=True)
        return

    # ── Run analysis ──
    source_lines = source.splitlines(keepends=True)
    all_issues: List[Issue] = []

    with st.spinner("🔎 Analysing…"):
        if run_ast_check:
            all_issues.extend(run_ast_checks(source, source_lines))
        if run_pyflakes_check:
            all_issues.extend(run_pyflakes(source))
        if run_pylint_check:
            all_issues.extend(run_pylint(source))

    # Deduplicate near-identical messages on the same line
    seen = set()
    deduped = []
    for iss in all_issues:
        key = (iss.line, iss.message[:60])
        if key not in seen:
            seen.add(key)
            deduped.append(iss)

    all_issues = sorted(deduped, key=lambda i: (SEV_ORDER.get(i.severity, 9), i.line or 9999))

    # ── Apply sidebar filters ──
    visible = [i for i in all_issues
               if (i.severity == "error"   and show_errors)
               or (i.severity == "warning" and show_warnings)
               or (i.severity == "info"    and show_infos)]

    # ── Summary cards ──
    st.markdown(f'<div class="section-header">📊 Summary — <code>{filename}</code></div>',
                unsafe_allow_html=True)
    render_metric_cards(all_issues)

    # Active tools
    active = []
    if run_ast_check:      active.append("AST Custom")
    if run_pyflakes_check: active.append("pyflakes")
    if run_pylint_check:   active.append("pylint")
    pills = "".join(f'<span class="tool-pill">{t}</span>' for t in active)
    st.markdown(f"<div>Tools used: {pills}</div>", unsafe_allow_html=True)

    # ── Issue list ──
    if not visible:
        st.success("✅ No issues found with the current filters!")
        return

    # Group by severity
    for sev_label, sev_key in [("🔴 Errors", "error"),
                                ("🟠 Warnings", "warning"),
                                ("🔵 Info", "info")]:
        group = [i for i in visible if i.severity == sev_key]
        if not group:
            continue
        st.markdown(f'<div class="section-header">{sev_label} ({len(group)})</div>',
                    unsafe_allow_html=True)
        for issue in group:
            render_issue(issue, source_lines)

    # ── Raw code viewer ──
    with st.expander("📄 View Source Code"):
        st.code(source, language="python", line_numbers=True)


if __name__ == "__main__":
    main()
