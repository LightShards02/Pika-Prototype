"""Build per-file AST summary of codebase for prompt injection.

Used by API-based agents (e.g. Kimi) that cannot access the filesystem.
CLI providers (e.g. Codex) never use this; they read files directly.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Optional tree-sitter; import lazily to avoid startup cost when not used
_tree_sitter_available = None


def _check_tree_sitter() -> bool:
    """Return True if tree-sitter and tree-sitter-languages are available."""
    global _tree_sitter_available
    if _tree_sitter_available is not None:
        return _tree_sitter_available
    try:
        from tree_sitter_languages import get_parser  # noqa: F401

        _tree_sitter_available = True
    except ImportError:
        _tree_sitter_available = False
    return _tree_sitter_available


# Extension -> tree-sitter language name
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "c",
    ".hpp": "cpp",
}


@dataclass
class Symbol:
    """A class, function, method, or attribute extracted from source."""

    name: str
    kind: str  # "class", "function", "method", "attribute"
    signature: str
    docstring: str
    line: int
    children: list[Symbol] = field(default_factory=list)


@dataclass
class FileSummary:
    """Per-file AST summary with symbols and call edges."""

    rel_path: str
    language: str
    symbols: list[Symbol]
    call_edges: list[tuple[str, str]]  # (caller, callee)
    raw_content: str | None = None


def _get_codebase_transmission_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return codebase_transmission config with defaults. No enabled flag."""
    ct = config.get("codebase_transmission")
    if not isinstance(ct, dict):
        ct = {}
    from core.pika_config import get_pika_config

    pika = get_pika_config()
    defaults = pika.get("codebase_transmission", {})
    if not isinstance(defaults, dict):
        defaults = {}
    out = {
        "max_summary_chars": 200_000,
        "max_raw_files": 10,
        "max_raw_chars_per_file": 5_000,
        "include_extensions": [".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs", ".c", ".cpp", ".h", ".hpp"],
        "exclude_patterns": [
            "**/__pycache__/**",
            "**/.git/**",
            "**/node_modules/**",
            "**/venv/**",
            "**/dist/**",
            "**/build/**",
            "**/*.min.js",
        ],
        "depth_limit": 15,
    }
    out.update(defaults)
    out.update(ct)
    return out


def _collect_source_files(codebase_dir: Path, config: dict[str, Any]) -> list[Path]:
    """Walk directory, filter by extension/exclude patterns, respect depth limit."""
    cfg = _get_codebase_transmission_config(config)
    extensions = set(e.lower() if e.startswith(".") else f".{e.lower()}" for e in cfg.get("include_extensions", [".py"]))
    exclude = cfg.get("exclude_patterns", [])
    depth_limit = int(cfg.get("depth_limit", 15))
    codebase_str = str(codebase_dir.resolve())

    collected: list[Path] = []
    for path in codebase_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(codebase_dir)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) > depth_limit:
            continue
        if path.suffix.lower() not in extensions:
            continue
        rel_str = str(rel).replace("\\", "/")
        if any(fnmatch.fnmatch(rel_str, p) for p in exclude):
            continue
        collected.append(path)
    return sorted(collected, key=lambda p: (len(p.relative_to(codebase_dir).parts), str(p)))


def _detect_language(path: Path) -> str | None:
    """Map file extension to tree-sitter language name."""
    return _EXT_TO_LANG.get(path.suffix.lower())


def _get_node_text(source_bytes: bytes, node: Any) -> str:
    """Extract text for a tree-sitter node from source bytes."""
    start = node.start_byte
    end = node.end_byte
    return source_bytes[start:end].decode("utf-8", errors="replace")


def _get_docstring(node: Any, source_bytes: bytes) -> str:
    """Extract first docstring from a function/class node. Truncate to 200 chars."""
    for child in node.children:
        if child.type == "block":
            for block_child in child.children:
                if block_child.type == "expression_statement":
                    for expr in block_child.children:
                        if expr.type in ("string", "concatenated_string"):
                            text = _get_node_text(source_bytes, expr).strip()
                            if text.startswith('"""') and text.endswith('"""'):
                                text = text[3:-3]
                            elif text.startswith("'''") and text.endswith("'''"):
                                text = text[3:-3]
                            elif (text.startswith('"') and text.endswith('"')) or (
                                text.startswith("'") and text.endswith("'")
                            ):
                                text = text[1:-1]
                            return text.strip()[:200] if len(text) > 200 else text.strip()
    return ""


def _extract_python_symbols(path: Path, source_bytes: bytes, parser: Any) -> tuple[list[Symbol], list[tuple[str, str]]]:
    """Extract symbols and call edges from Python source."""
    tree = parser.parse(source_bytes)
    root = tree.root_node
    symbols: list[Symbol] = []
    call_edges: list[tuple[str, str]] = []
    current_class: str | None = None
    current_caller: str | None = None

    def visit(node: Any, class_prefix: str = "", caller: str | None = None) -> None:
        nonlocal current_class, current_caller
        if node.type == "class_definition":
            name_node = next((c for c in node.children if c.type == "identifier"), None)
            name = _get_node_text(source_bytes, name_node).strip() if name_node else "?"
            doc = _get_docstring(node, source_bytes)
            sig = f"class {name}:"
            sym = Symbol(name=name, kind="class", signature=sig, docstring=doc, line=node.start_point[0] + 1, children=[])
            prev_class = current_class
            current_class = name
            for c in node.children:
                if c.type == "block":
                    for bc in c.children:
                        if bc.type == "expression_statement":
                            for expr in bc.children:
                                if expr.type == "assignment":
                                    attr_name = ""
                                    for ac in expr.children:
                                        if ac.type == "identifier" and not attr_name:
                                            attr_name = _get_node_text(source_bytes, ac).strip()
                                            break
                                        elif ac.type == "attribute":
                                            attr_name = _get_node_text(source_bytes, ac).strip()
                                            break
                                    if attr_name:
                                        type_hint = ""
                                        for ac in expr.children:
                                            if ac.type == "type":
                                                type_hint = f": {_get_node_text(source_bytes, ac).strip()}"
                                                break
                                        sym.children.append(
                                            Symbol(attr_name, "attribute", f"{attr_name}{type_hint}", "", expr.start_point[0] + 1)
                                        )
                        elif bc.type == "function_definition":
                            visit(bc, f"{name}.", caller)
            symbols.append(sym)
            current_class = prev_class
        elif node.type == "function_definition":
            name_node = next((c for c in node.children if c.type == "identifier"), None)
            params_node = next((c for c in node.children if c.type == "parameters"), None)
            name = _get_node_text(source_bytes, name_node).strip() if name_node else "?"
            full_name = f"{class_prefix}{name}" if class_prefix else name
            doc = _get_docstring(node, source_bytes)
            params_text = _get_node_text(source_bytes, params_node).strip() if params_node else "(...)"
            sig = f"def {name}{params_text}"
            kind = "method" if class_prefix else "function"
            sym = Symbol(name=full_name, kind=kind, signature=sig, docstring=doc, line=node.start_point[0] + 1, children=[])
            symbols.append(sym)
            prev_caller = current_caller
            current_caller = full_name
            for c in node.children:
                visit(c, class_prefix, full_name)
            current_caller = prev_caller
        elif node.type == "call":
            callee_node = next((c for c in node.children if c.type in ("identifier", "attribute")), None)
            callee = _get_node_text(source_bytes, callee_node).strip() if callee_node else ""
            if callee and caller:
                call_edges.append((caller, callee))
            for c in node.children:
                visit(c, class_prefix, caller)
        else:
            for c in node.children:
                visit(c, class_prefix, caller)

    for child in root.children:
        visit(child)
    return symbols, call_edges


def _extract_python_symbols_stdlib(path: Path, content: str) -> tuple[list[Symbol], list[tuple[str, str]]]:
    """Extract symbols and call edges using Python stdlib ast. Fallback when tree-sitter unavailable."""
    import ast

    symbols: list[Symbol] = []
    call_edges: list[tuple[str, str]] = []

    def get_docstring(node: ast.AST) -> str:
        doc = ast.get_docstring(node)
        return (doc[:200] + "..." if len(doc) > 200 else doc) if doc else ""

    def get_callee(node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return ""

    def collect_calls(node: ast.AST, caller: str) -> None:
        for n in ast.walk(node):
            if isinstance(n, ast.Call):
                callee = get_callee(n)
                if callee:
                    call_edges.append((caller, callee))

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._class_prefix = ""

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            doc = get_docstring(node)
            bases_str = ""
            if node.bases and hasattr(ast, "unparse"):
                bases_str = f"({', '.join(ast.unparse(b) for b in node.bases)})"
            sig = f"class {node.name}{bases_str}:"
            sym = Symbol(node.name, "class", sig, doc, node.lineno, [])
            for n in node.body:
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                    type_str = ast.unparse(n.annotation) if hasattr(ast, "unparse") else ""
                    sym.children.append(Symbol(n.target.id, "attribute", f"{n.target.id}: {type_str}", "", n.lineno))
            symbols.append(sym)
            prev = self._class_prefix
            self._class_prefix = f"{node.name}."
            self.generic_visit(node)
            self._class_prefix = prev

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            full_name = f"{self._class_prefix}{node.name}" if self._class_prefix else node.name
            doc = get_docstring(node)
            args_str = ast.unparse(node.args) if hasattr(ast, "unparse") else "..."
            sig = f"def {node.name}{args_str}"
            kind = "method" if self._class_prefix else "function"
            symbols.append(Symbol(full_name, kind, sig, doc, node.lineno, []))
            collect_calls(node, full_name)
            self.generic_visit(node)

    try:
        tree = ast.parse(content)
        Visitor().visit(tree)
    except SyntaxError:
        pass
    return symbols, call_edges


def _extract_file_summary(
    path: Path, codebase_dir: Path, config: dict[str, Any], raw_file_set: set[Path]
) -> FileSummary | None:
    """Parse file with tree-sitter (or stdlib ast for Python), extract symbols and call edges."""
    lang = _detect_language(path)
    if not lang:
        return FileSummary(rel_path=str(path.relative_to(codebase_dir)).replace("\\", "/"), language="", symbols=[], call_edges=[])
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Could not read %s: %s", path, e)
        return None
    if "\x00" in content:
        return None
    symbols: list[Symbol]
    call_edges: list[tuple[str, str]]
    if lang == "python" and not _check_tree_sitter():
        symbols, call_edges = _extract_python_symbols_stdlib(path, content)
    elif _check_tree_sitter():
        source_bytes = content.encode("utf-8")
        try:
            from tree_sitter_languages import get_parser

            parser = get_parser(lang)
        except (ImportError, Exception) as e:
            logger.warning("Could not get parser for %s: %s", lang, e)
            symbols, call_edges = [], []
        else:
            if lang == "python":
                symbols, call_edges = _extract_python_symbols(path, source_bytes, parser)
            else:
                symbols, call_edges = [], []
    else:
        symbols, call_edges = [], []
    rel = str(path.relative_to(codebase_dir)).replace("\\", "/")
    raw_content = None
    if path in raw_file_set:
        cfg = _get_codebase_transmission_config(config)
        max_chars = int(cfg.get("max_raw_chars_per_file", 5000))
        raw_content = content if len(content) <= max_chars else content[:max_chars] + "\n... (truncated)"
    return FileSummary(rel_path=rel, language=lang, symbols=symbols, call_edges=call_edges, raw_content=raw_content)


def _build_file_tree(files: list[Path], codebase_dir: Path) -> str:
    """Render indented directory tree of source files."""
    if not files:
        return "(empty)"
    rel_paths = sorted(set(str(f.relative_to(codebase_dir)).replace("\\", "/") for f in files))
    lines: list[str] = []
    seen_dirs: set[str] = set()
    for rp in rel_paths:
        parts = rp.split("/")
        for i in range(1, len(parts)):
            d = "/".join(parts[:i])
            if d not in seen_dirs:
                seen_dirs.add(d)
                indent = "  " * (i - 1)
                lines.append(f"{indent}{parts[i-1]}/")
        indent = "  " * (len(parts) - 1)
        lines.append(f"{indent}{parts[-1]}")
    return "\n".join(lines) if lines else "(empty)"


def _build_call_graph(file_summaries: list[FileSummary]) -> str:
    """Merge per-file call edges into global call graph string."""
    edges: list[tuple[str, str]] = []
    for fs in file_summaries:
        edges.extend(fs.call_edges)
    if not edges:
        return "(none)"
    caller_to_callees: dict[str, set[str]] = {}
    for caller, callee in edges:
        if caller not in caller_to_callees:
            caller_to_callees[caller] = set()
        caller_to_callees[caller].add(callee)
    lines = [f"{c} -> {', '.join(sorted(callees))}" for c, callees in sorted(caller_to_callees.items())]
    return "\n".join(lines)


def _format_symbol(sym: Symbol, indent: int = 0) -> str:
    """Format a symbol for output."""
    prefix = "  " * indent
    lines = []
    if sym.docstring:
        lines.append(f'{prefix}{sym.signature}')
        lines.append(f'{prefix}    """{sym.docstring}"""')
    else:
        lines.append(f"{prefix}{sym.signature}")
    for child in sym.children:
        lines.append(_format_symbol(child, indent + 1))
    return "\n".join(lines)


def _format_snapshot(
    file_tree: str,
    file_summaries: list[FileSummary],
    call_graph: str,
    max_chars: int,
) -> str:
    """Assemble final per-file-organized string. Truncate if over max_chars."""
    parts = ["# Codebase Snapshot", "", "## File Tree", "", file_tree, "", "## Files", ""]
    for fs in file_summaries:
        parts.append(f"### {fs.rel_path}")
        parts.append("")
        parts.append("#### Symbols")
        parts.append("")
        if fs.symbols:
            for sym in fs.symbols:
                parts.append(_format_symbol(sym))
                parts.append("")
        else:
            parts.append("(none)")
            parts.append("")
        if fs.raw_content:
            lang = "python" if fs.language == "python" else fs.language or "text"
            parts.append("#### Source (included)")
            parts.append("")
            parts.append(f"```{lang}")
            parts.append(fs.raw_content)
            parts.append("```")
            parts.append("")
        parts.append("")
    parts.append("## Call Graph")
    parts.append("")
    parts.append(call_graph)
    result = "\n".join(parts)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n\n... (snapshot truncated)"
    return result


def build_codebase_snapshot(
    codebase_dir: Path,
    config: dict[str, Any],
    *,
    command: str | None = None,
    raw_file_paths: list[Path] | None = None,
) -> str:
    """Build per-file AST summary of codebase for prompt injection.

    Returns formatted string with:
    1. File tree (all source files, indented)
    2. Per-file sections: symbols (classes with attributes, functions, methods,
       signatures, docstrings) and optionally raw source content
    3. Global call graph (who calls whom, cross-file)

    Files selected for raw inclusion (via raw_file_paths or command heuristic)
    get a '#### Source (included)' subsection within their file section.
    """
    codebase_dir = Path(codebase_dir).resolve()
    if not codebase_dir.exists() or not codebase_dir.is_dir():
        return "(No source files found: codebase_dir does not exist or is not a directory)"
    files = _collect_source_files(codebase_dir, config)
    if not files:
        return "(No source files found in codebase_dir)"
    cfg = _get_codebase_transmission_config(config)
    max_chars = int(cfg.get("max_summary_chars", 200_000))
    max_raw = int(cfg.get("max_raw_files", 10))
    raw_set: set[Path] = set()
    if raw_file_paths:
        raw_set = set(Path(p).resolve() for p in raw_file_paths)
    elif command == "implement":
        for f in files[:max_raw]:
            raw_set.add(f)
    summaries: list[FileSummary] = []
    for f in files:
        s = _extract_file_summary(f, codebase_dir, config, raw_set)
        if s:
            summaries.append(s)
    file_tree = _build_file_tree(files, codebase_dir)
    call_graph = _build_call_graph(summaries)
    return _format_snapshot(file_tree, summaries, call_graph, max_chars)
