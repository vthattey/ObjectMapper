"""
JSON Attribute Mapper v2
========================
Visual mapping utility rebuilt on NodeGraphQt. Three new capabilities:

  1. NodeGraphQt foundation — undo/redo, session save/load, pipe routing,
     serialization — all come free from the framework.
  2. Functoids — draggable transformation blocks (String, Math, Logic, Custom)
     that sit between source and target with their own input/output ports.
  3. Bidirectional sync — export .md for AI, generate Python code from the
     visual mapping, AND reverse-engineer existing code back into the graph.

Run:
    pip install PySide6 NodeGraphQt
    python json_mapper_v2.py
"""

from __future__ import annotations

import json
import sys
import textwrap
import webbrowser
from pathlib import Path
from typing import Optional

from Qt import QtCore, QtWidgets, QtGui
from NodeGraphQt import NodeGraph, BaseNode
from NodeGraphQt.constants import (
    PipeLayoutEnum,
    PortTypeEnum,
)

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def flatten_json(data, prefix: str = "$") -> list[tuple[str, str]]:
    """Return [(json_path, type_name), ...] for every leaf and branch."""
    result: list[tuple[str, str]] = []

    def walk(node, path: str):
        result.append((path, _type_of(node)))
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list) and node:
            walk(node[0], f"{path}[*]")

    walk(data, prefix)
    return result


def _type_of(value) -> str:
    if isinstance(value, dict):   return "object"
    if isinstance(value, list):   return "array"
    if isinstance(value, bool):   return "boolean"
    if isinstance(value, int):    return "integer"
    if isinstance(value, float):  return "number"
    if isinstance(value, str):    return "string"
    if value is None:             return "null"
    return type(value).__name__


# --------------------------------------------------------------------------- #
# Node types                                                                  #
# --------------------------------------------------------------------------- #

class SourceSchemaNode(BaseNode):
    __identifier__ = "mapper.schema"
    NODE_NAME = "Source"

    def __init__(self):
        super().__init__()
        self.set_color(45, 125, 210)   # blue
        self.create_property("json_file", "", widget_type=0)
        self.create_property("field_types", "{}", widget_type=0)
        self._field_types: dict[str, str] = {}

    def load_json(self, data, filename: str = "source.json"):
        # Clear existing output ports
        for p in list(self.output_ports()):
            self.delete_output(p)
        self.set_name(f"Source: {filename}")
        fields = flatten_json(data)
        self._field_types = {}
        for path, typ in fields:
            if typ in ("object", "array"):
                continue  # only leaf fields get ports
            port = self.add_output(path)
            self._field_types[path] = typ
        self.set_property("json_file", filename)
        self.set_property("field_types", json.dumps(self._field_types))

    def type_of(self, path: str) -> str:
        return self._field_types.get(path, "")

    def restore_types(self):
        raw = self.get_property("field_types")
        if raw:
            self._field_types = json.loads(raw)


class TargetSchemaNode(BaseNode):
    __identifier__ = "mapper.schema"
    NODE_NAME = "Target"

    def __init__(self):
        super().__init__()
        self.set_color(92, 184, 92)    # green
        self.create_property("json_file", "", widget_type=0)
        self.create_property("field_types", "{}", widget_type=0)
        self._field_types: dict[str, str] = {}

    def load_json(self, data, filename: str = "target.json"):
        for p in list(self.input_ports()):
            self.delete_input(p)
        self.set_name(f"Target: {filename}")
        fields = flatten_json(data)
        self._field_types = {}
        for path, typ in fields:
            if typ in ("object", "array"):
                continue
            port = self.add_input(path)
            self._field_types[path] = typ
        self.set_property("json_file", filename)
        self.set_property("field_types", json.dumps(self._field_types))

    def type_of(self, path: str) -> str:
        return self._field_types.get(path, "")

    def restore_types(self):
        raw = self.get_property("field_types")
        if raw:
            self._field_types = json.loads(raw)


# ---- Functoid nodes ------------------------------------------------------- #

class BaseFunctoid(BaseNode):
    """Base class for all transformation blocks."""
    __identifier__ = "mapper.functoid"
    NODE_NAME = "Functoid"
    CATEGORY = "General"

    def __init__(self):
        super().__init__()
        self.set_color(186, 117, 23)    # amber
        self.create_property("expression", "", widget_type=0)

    def get_expression(self) -> str:
        return self.get_property("expression") or ""


class StringFunctoid(BaseFunctoid):
    NODE_NAME = "String"
    CATEGORY = "String"

    OPERATIONS = [
        ("Concatenate",  'input_a + " " + input_b'),
        ("Uppercase",    "input_a.upper()"),
        ("Lowercase",    "input_a.lower()"),
        ("Trim",         "input_a.strip()"),
        ("Substring",    "input_a[:N]"),
        ("Replace",      'input_a.replace("old", "new")'),
        ("Split",        'input_a.split(",")'),
        ("Format",       'f"prefix {input_a} suffix"'),
    ]

    def __init__(self):
        super().__init__()
        self.set_color(210, 90, 48)     # coral
        self.add_input("input_a")
        self.add_input("input_b")
        self.add_output("result")
        self.create_property("operation", "Concatenate", widget_type=0)
        self.set_property("expression", self.OPERATIONS[0][1])


class MathFunctoid(BaseFunctoid):
    NODE_NAME = "Math"
    CATEGORY = "Math"

    OPERATIONS = [
        ("Divide by 100",     "input_a / 100.0"),
        ("Multiply",          "input_a * input_b"),
        ("Add",               "input_a + input_b"),
        ("Subtract",          "input_a - input_b"),
        ("Round",             "round(input_a, 2)"),
        ("Floor divide",      "input_a // input_b"),
        ("Absolute value",    "abs(input_a)"),
    ]

    def __init__(self):
        super().__init__()
        self.set_color(99, 22, 146)     # purple
        self.add_input("input_a")
        self.add_input("input_b")
        self.add_output("result")
        self.create_property("operation", "Divide by 100", widget_type=0)
        self.set_property("expression", self.OPERATIONS[0][1])


class LogicFunctoid(BaseFunctoid):
    NODE_NAME = "Logic"
    CATEGORY = "Logic"

    OPERATIONS = [
        ("If-else",          'input_a if condition else default'),
        ("Lookup map",       '{"A": "Active", "I": "Inactive"}.get(input_a, input_a)'),
        ("Not null",         "input_a is not None"),
        ("Coalesce",         "input_a or input_b"),
        ("Bool cast",        "bool(input_a)"),
    ]

    def __init__(self):
        super().__init__()
        self.set_color(64, 127, 127)    # teal
        self.add_input("input_a")
        self.add_input("input_b")
        self.add_output("result")
        self.create_property("operation", "If-else", widget_type=0)
        self.set_property("expression", self.OPERATIONS[0][1])


class ConversionFunctoid(BaseFunctoid):
    NODE_NAME = "Conversion"
    CATEGORY = "Conversion"

    OPERATIONS = [
        ("Cents to dollars",      "input_a / 100.0"),
        ("ISO date reformat",     "format_date(input_a, 'YYYY-MM-DD')"),
        ("Country code to name",  "country_name(input_a)"),
        ("Phone format",          "pretty_phone(input_a)"),
        ("To string",             "str(input_a)"),
        ("To integer",            "int(input_a)"),
        ("To float",              "float(input_a)"),
    ]

    def __init__(self):
        super().__init__()
        self.set_color(60, 52, 137)     # indigo
        self.add_input("input_a")
        self.add_output("result")
        self.create_property("operation", "Cents to dollars", widget_type=0)
        self.set_property("expression", self.OPERATIONS[0][1])


class CustomFunctoid(BaseFunctoid):
    NODE_NAME = "Custom"
    CATEGORY = "Custom"

    def __init__(self):
        super().__init__()
        self.set_color(136, 135, 128)   # gray
        self.add_input("input_a")
        self.add_input("input_b")
        self.add_input("input_c")
        self.add_output("result")
        self.set_property("expression", "# write custom logic here\nresult = input_a")


ALL_FUNCTOIDS = [
    StringFunctoid, MathFunctoid, LogicFunctoid,
    ConversionFunctoid, CustomFunctoid,
]

ALL_NODES = [SourceSchemaNode, TargetSchemaNode] + ALL_FUNCTOIDS


# --------------------------------------------------------------------------- #
# Functoid property editor dialog                                             #
# --------------------------------------------------------------------------- #

class FunctoidEditor(QtWidgets.QDialog):
    def __init__(self, node: BaseFunctoid, parent=None):
        super().__init__(parent)
        self.node = node
        self.setWindowTitle(f"Edit {node.NODE_NAME} functoid")
        self.resize(520, 380)

        layout = QtWidgets.QVBoxLayout(self)

        # Operation picker (if node has OPERATIONS)
        if hasattr(node, "OPERATIONS"):
            op_group = QtWidgets.QGroupBox("Operation template")
            op_lay = QtWidgets.QVBoxLayout(op_group)
            self.op_combo = QtWidgets.QComboBox()
            for name, _ in node.OPERATIONS:
                self.op_combo.addItem(name)
            cur = node.get_property("operation") or ""
            idx = self.op_combo.findText(cur)
            if idx >= 0:
                self.op_combo.setCurrentIndex(idx)
            self.op_combo.currentIndexChanged.connect(self._on_op_changed)
            op_lay.addWidget(self.op_combo)
            layout.addWidget(op_group)

        # Expression editor
        expr_group = QtWidgets.QGroupBox("Expression / pseudocode")
        expr_lay = QtWidgets.QVBoxLayout(expr_group)
        self.expr_edit = QtWidgets.QPlainTextEdit()
        self.expr_edit.setFont(QtGui.QFont("Menlo, Consolas, monospace", 11))
        self.expr_edit.setPlainText(node.get_expression())
        self.expr_edit.setPlaceholderText(
            "# Use input_a, input_b, input_c as port references\n"
            "result = input_a.upper()"
        )
        expr_lay.addWidget(self.expr_edit)
        layout.addWidget(expr_group)

        # Port info
        info = QtWidgets.QLabel(
            f"<b>Inputs:</b> "
            + ", ".join(p.name() for p in node.input_ports())
            + f"<br><b>Outputs:</b> "
            + ", ".join(p.name() for p in node.output_ports())
        )
        info.setTextFormat(QtCore.Qt.RichText)
        layout.addWidget(info)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_op_changed(self, idx: int):
        if hasattr(self.node, "OPERATIONS") and 0 <= idx < len(self.node.OPERATIONS):
            _, template = self.node.OPERATIONS[idx]
            self.expr_edit.setPlainText(template)

    def apply(self):
        self.node.set_property("expression", self.expr_edit.toPlainText().strip())
        if hasattr(self.node, "OPERATIONS") and hasattr(self, "op_combo"):
            self.node.set_property("operation", self.op_combo.currentText())


# --------------------------------------------------------------------------- #
# Mapping extraction                                                          #
# --------------------------------------------------------------------------- #

def extract_mappings(graph: NodeGraph) -> list[dict]:
    """Walk all pipes and build mapping records.

    Returns a list of dicts:
        target_path, source_paths, source_types, target_type,
        functoid_chain (list of {name, expression}), direct (bool)
    """
    # Find schema nodes
    sources = graph.get_nodes_by_type("mapper.schema.SourceSchemaNode")
    targets = graph.get_nodes_by_type("mapper.schema.TargetSchemaNode")
    if not sources or not targets:
        return []
    src_node = sources[0]
    tgt_node = targets[0]

    mappings = []

    for tgt_port in tgt_node.input_ports():
        tgt_path = tgt_port.name()
        tgt_type = tgt_node.type_of(tgt_path)

        # Trace back from this target port through any functoid chain
        connected = tgt_port.connected_ports()
        if not connected:
            continue

        for upstream_port in connected:
            chain = []
            source_paths = []
            source_types = []
            _trace_upstream(upstream_port.node(), upstream_port, src_node,
                            chain, source_paths, source_types)
            mappings.append({
                "target_path": tgt_path,
                "target_type": tgt_type,
                "source_paths": source_paths,
                "source_types": source_types,
                "functoid_chain": chain,
                "direct": len(chain) == 0,
            })

    return mappings


def _trace_upstream(node, from_port, src_node, chain, source_paths, source_types):
    """Recursively trace upstream connections from a node."""
    if node is src_node:
        path = from_port.name()
        if path not in source_paths:
            source_paths.append(path)
            source_types.append(src_node.type_of(path))
        return

    if isinstance(node, BaseFunctoid):
        chain.append({
            "name": node.NODE_NAME,
            "operation": node.get_property("operation") or "",
            "expression": node.get_expression(),
        })
        # Trace all inputs of this functoid
        for inp in node.input_ports():
            for upstream in inp.connected_ports():
                _trace_upstream(upstream.node(), upstream, src_node,
                                chain, source_paths, source_types)


# --------------------------------------------------------------------------- #
# Markdown export                                                             #
# --------------------------------------------------------------------------- #

def render_markdown(mappings: list[dict], source_file: str, target_file: str) -> str:
    lines = [
        "# JSON Attribute Mapping Specification", "",
        "This document describes how to transform a **source** JSON object "
        "into a **target** JSON object.", "",
        f"- **Source:** `{source_file}`",
        f"- **Target:** `{target_file}`",
        f"- **Mappings:** {len(mappings)}", "",
        "## Path notation", "",
        "- `$` — root.  `.field` — property.  `[*]` — every array element.", "",
        "## Mapping table", "",
        "| # | Source | Type | Target | Type | Functoids | Kind |",
        "|---|--------|------|--------|------|-----------|------|",
    ]
    for i, m in enumerate(mappings, 1):
        srcs = ", ".join(f"`{s}`" for s in m["source_paths"]) or "—"
        stypes = ", ".join(m["source_types"]) or "—"
        funcs = " → ".join(f["name"] for f in m["functoid_chain"]) or "—"
        kind = "direct" if m["direct"] else "transform"
        lines.append(
            f"| {i} | {srcs} | {stypes} | `{m['target_path']}` "
            f"| {m['target_type']} | {funcs} | {kind} |"
        )

    lines += ["", "## Mapping details", ""]
    for i, m in enumerate(mappings, 1):
        srcs = " + ".join(f"`{s}`" for s in m["source_paths"])
        lines.append(f"### {i}. {srcs} → `{m['target_path']}`")
        lines.append("")
        if m["direct"]:
            lines.append("- **Transformation:** direct copy.")
        else:
            for f in m["functoid_chain"]:
                lines.append(f"- **Functoid:** {f['name']}"
                             + (f" ({f['operation']})" if f['operation'] else ""))
                if f["expression"]:
                    lines.append("")
                    lines.append("```text")
                    lines.append(f["expression"])
                    lines.append("```")
        lines.append("")

    lines += [
        "## Agent instructions", "",
        "1. Read source JSON, produce target JSON satisfying every mapping.",
        "2. Direct-copy rows: assign unchanged.",
        "3. Functoid rows: implement the expression faithfully.",
        "4. `[*]` paths: iterate and produce corresponding arrays.",
        "5. Preserve types unless the expression says to coerce.", "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Python code generation (visual → code)                                      #
# --------------------------------------------------------------------------- #

def generate_python(mappings: list[dict], source_file: str, target_file: str) -> str:
    """Generate a Python mapping function from the visual mapping."""
    body_lines = []
    helpers_needed = set()

    # Separate array mappings from scalar mappings
    array_mappings = [m for m in mappings if "[*]" in m["target_path"]]
    scalar_mappings = [m for m in mappings if "[*]" not in m["target_path"]]

    body_lines.append(f'def map_source_to_target(source: dict) -> dict:')
    body_lines.append(f'    """')
    body_lines.append(f'    Auto-generated mapping: {source_file} -> {target_file}')
    body_lines.append(f'    Mappings: {len(mappings)}')
    body_lines.append(f'    """')

    # Scan for helper functions needed
    for m in mappings:
        for f in m.get("functoid_chain", []):
            expr = f.get("expression", "")
            if "format_date" in expr:
                helpers_needed.add("format_date")
            if "country_name" in expr:
                helpers_needed.add("country_name")
            if "pretty_phone" in expr:
                helpers_needed.add("pretty_phone")

    body_lines.append("")
    body_lines.append("    result = {}")
    body_lines.append("")

    # Scalar assignments
    generated_parents: set[str] = set()
    for m in scalar_mappings:
        parts = m["target_path"].lstrip("$.").split(".")
        expr = _build_expression(m, "source")
        _emit_assignment(body_lines, parts, expr, generated_parents)

    # Group array mappings by array root
    array_groups: dict[str, list] = {}
    for m in array_mappings:
        path = m["target_path"]
        arr_idx = path.index("[*]")
        arr_root = path[:arr_idx]
        field_after = path[arr_idx + 3:].lstrip(".")
        if arr_root not in array_groups:
            array_groups[arr_root] = []
        array_groups[arr_root].append((field_after, m))

    # Generate array comprehensions
    for arr_root, fields in array_groups.items():
        arr_parts = arr_root.lstrip("$.").split(".")
        # Determine source array path from the first mapping
        src_arr = ""
        for _, m in fields:
            for sp in m["source_paths"]:
                if "[*]" in sp:
                    src_arr = sp[:sp.index("[*]")]
                    break
            if src_arr:
                break
        src_accessor = _src_accessor(src_arr, "source")
        item_var = "item"

        # Build inner dict
        inner_parts = []
        for field_name, m in fields:
            expr = _build_expression(m, "source", loop_var=item_var)
            inner_parts.append(f'            "{field_name}": {expr},')

        # Ensure parent exists
        _ensure_parent(body_lines, arr_parts, generated_parents)
        target_accessor = _dict_path("result", arr_parts)
        body_lines.append(f"    {target_accessor} = [")
        body_lines.append("        {")
        body_lines.extend(inner_parts)
        body_lines.append("        }")
        body_lines.append(f"        for {item_var} in {src_accessor}")
        body_lines.append("    ]")
        body_lines.append("")

    body_lines.append("    return result")

    # Build full file
    file_lines = ['"""', f"Auto-generated mapping code.", f"Source: {source_file}",
                  f"Target: {target_file}", '"""', ""]

    if helpers_needed:
        file_lines.append("")
        file_lines.append("# Helper functions — implement these for your environment")
        for h in sorted(helpers_needed):
            if h == "format_date":
                file_lines.append("def format_date(iso_str: str, fmt: str) -> str:")
                file_lines.append("    from datetime import datetime")
                file_lines.append('    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))')
                file_lines.append("    return dt.strftime(fmt.replace('YYYY','%Y').replace('MM','%m').replace('DD','%d'))")
                file_lines.append("")
            elif h == "country_name":
                file_lines.append("def country_name(code: str) -> str:")
                file_lines.append('    _MAP = {"US": "United States", "GB": "United Kingdom", "DE": "Germany"}')
                file_lines.append("    return _MAP.get(code.upper(), code)")
                file_lines.append("")
            elif h == "pretty_phone":
                file_lines.append("def pretty_phone(e164: str) -> str:")
                file_lines.append('    return e164  # implement formatting as needed')
                file_lines.append("")

    file_lines.extend(["", ""])
    file_lines.extend(body_lines)

    # Add main block
    file_lines.extend([
        "", "", "if __name__ == '__main__':",
        "    import json, sys",
        "    if len(sys.argv) < 2:",
        f'        print("Usage: python {{sys.argv[0]}} <source.json>")',
        "        sys.exit(1)",
        '    with open(sys.argv[1]) as f:',
        "        source = json.load(f)",
        "    result = map_source_to_target(source)",
        "    print(json.dumps(result, indent=2))",
    ])

    return "\n".join(file_lines)


def _build_expression(m: dict, root: str, loop_var: str = "") -> str:
    """Build a Python expression for one mapping."""
    if m["direct"]:
        sp = m["source_paths"][0] if m["source_paths"] else "$"
        if loop_var and "[*]" in sp:
            # Inside a list comprehension — use loop variable
            after = sp[sp.index("[*]") + 3:].lstrip(".")
            return f'{loop_var}["{after}"]' if after else loop_var
        return _src_accessor(sp, root)

    # Has functoid chain — use the expression
    chain = m.get("functoid_chain", [])
    if not chain:
        sp = m["source_paths"][0] if m["source_paths"] else "$"
        return _src_accessor(sp, root)

    expr = chain[0].get("expression", "input_a")
    # Replace input_a, input_b with actual source accessors
    for i, sp in enumerate(m["source_paths"]):
        var = ["input_a", "input_b", "input_c"][i] if i < 3 else f"input_{i}"
        if loop_var and "[*]" in sp:
            after = sp[sp.index("[*]") + 3:].lstrip(".")
            replacement = f'{loop_var}["{after}"]' if after else loop_var
        else:
            replacement = _src_accessor(sp, root)
        expr = expr.replace(var, replacement)

    return expr


def _src_accessor(path: str, root: str) -> str:
    """Convert $.customer.email_lc -> source['customer']['email_lc']"""
    parts = path.lstrip("$.").split(".")
    parts = [p for p in parts if p]  # remove empties
    result = root
    for p in parts:
        result += f'["{p}"]'
    return result


def _dict_path(root: str, parts: list[str]) -> str:
    result = root
    for p in parts:
        result += f'["{p}"]'
    return result


def _ensure_parent(lines: list[str], parts: list[str], generated: set[str]):
    """Emit result["parent"] = {} if not yet generated."""
    for depth in range(1, len(parts)):
        key = ".".join(parts[:depth])
        if key not in generated:
            accessor = _dict_path("result", parts[:depth])
            lines.append(f"    {accessor} = {{}}")
            generated.add(key)


def _emit_assignment(lines: list[str], parts: list[str], expr: str,
                     generated: set[str]):
    _ensure_parent(lines, parts, generated)
    accessor = _dict_path("result", parts)
    lines.append(f"    {accessor} = {expr}")


# --------------------------------------------------------------------------- #
# Main window                                                                 #
# --------------------------------------------------------------------------- #

class MapperWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JSON Attribute Mapper v2")
        self.resize(1500, 850)

        self.source_file = "source.json"
        self.target_file = "target.json"

        # NodeGraphQt setup
        self.graph = NodeGraph()
        self.graph.set_pipe_style(PipeLayoutEnum.CURVED.value)
        self.graph.register_nodes(ALL_NODES)

        # Wire up double-click for functoid editing
        self.graph.node_double_clicked.connect(self._on_node_double_clicked)
        self.graph.port_connected.connect(lambda *_: self._update_status())
        self.graph.port_disconnected.connect(lambda *_: self._update_status())

        # Build UI
        self._build_toolbar()
        self._build_functoid_palette()

        # Central area: graph viewer + palette
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(self.palette_widget)
        graph_widget = self.graph.widget
        graph_widget.setMinimumWidth(900)
        splitter.addWidget(graph_widget)
        splitter.setSizes([220, 1280])
        self.setCentralWidget(splitter)

        self._build_status()

        # Create initial schema nodes
        self.src_node = self.graph.create_node(
            "mapper.schema.SourceSchemaNode", pos=[-400, 0])
        self.tgt_node = self.graph.create_node(
            "mapper.schema.TargetSchemaNode", pos=[400, 0])

    # ---- toolbar ---------------------------------------------------------- #

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)

        tb.addAction("Load Source JSON", self._load_source)
        tb.addAction("Load Target JSON", self._load_target)
        tb.addSeparator()
        tb.addAction("Auto-layout", self._auto_layout)
        tb.addSeparator()
        tb.addAction("Export .md", self._export_md)
        tb.addAction("Generate Python", self._generate_python)
        tb.addAction("Analyze Code → HTML", self._analyze_code)
        tb.addSeparator()
        tb.addAction("Save Session", self._save_session)
        tb.addAction("Load Session", self._load_session)

    # ---- functoid palette ------------------------------------------------- #

    def _build_functoid_palette(self):
        self.palette_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.palette_widget)
        layout.setContentsMargins(6, 6, 6, 6)

        title = QtWidgets.QLabel("<b>Functoids</b>")
        title.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title)

        info = QtWidgets.QLabel(
            "<small>Drag a functoid onto the canvas, then "
            "connect source ports → functoid → target ports. "
            "Double-click to edit.</small>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addSpacing(8)

        categories = {}
        for cls in ALL_FUNCTOIDS:
            cat = cls.CATEGORY
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(cls)

        for cat, nodes in categories.items():
            group = QtWidgets.QGroupBox(cat)
            g_layout = QtWidgets.QVBoxLayout(group)
            for cls in nodes:
                btn = QtWidgets.QPushButton(cls.NODE_NAME)
                btn.setToolTip(
                    f"Add a {cls.NODE_NAME} functoid to the canvas.\n"
                    + (f"Operations: {', '.join(op[0] for op in cls.OPERATIONS)}"
                       if hasattr(cls, "OPERATIONS") else "Custom expression block")
                )
                btn.clicked.connect(lambda _, c=cls: self._add_functoid(c))
                g_layout.addWidget(btn)
            layout.addWidget(group)

        layout.addStretch()

    def _add_functoid(self, cls):
        type_id = f"{cls.__identifier__}.{cls.__name__}"
        node = self.graph.create_node(type_id)
        # Position near center of current view
        pos = self.graph.cursor_pos()
        node.set_pos(pos[0], pos[1])

    # ---- status ----------------------------------------------------------- #

    def _build_status(self):
        self.status_label = QtWidgets.QLabel()
        self.statusBar().addPermanentWidget(self.status_label)
        self._update_status()

    def _update_status(self):
        mappings = extract_mappings(self.graph)
        functoids = [n for n in self.graph.all_nodes()
                     if isinstance(n, BaseFunctoid)]
        self.status_label.setText(
            f"Source: {self.source_file}  |  "
            f"Target: {self.target_file}  |  "
            f"Mappings: {len(mappings)}  |  "
            f"Functoids: {len(functoids)}"
        )

    # ---- node interaction ------------------------------------------------- #

    def _on_node_double_clicked(self, node):
        if isinstance(node, BaseFunctoid):
            dlg = FunctoidEditor(node, self)
            if dlg.exec() == QtWidgets.QDialog.Accepted:
                dlg.apply()
                self._update_status()

    # ---- load JSON -------------------------------------------------------- #

    def _load_source(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Source JSON", "", "JSON (*.json);;All (*)")
        if not path:
            return
        data = self._read_json(path)
        if data is None:
            return
        self.source_file = Path(path).name
        self.src_node.load_json(data, self.source_file)
        self._auto_layout()
        self._update_status()

    def _load_target(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Target JSON", "", "JSON (*.json);;All (*)")
        if not path:
            return
        data = self._read_json(path)
        if data is None:
            return
        self.target_file = Path(path).name
        self.tgt_node.load_json(data, self.target_file)
        self._auto_layout()
        self._update_status()

    def _read_json(self, path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load error", str(e))
            return None

    # ---- layout ----------------------------------------------------------- #

    def _auto_layout(self):
        src_ports = len(self.src_node.output_ports())
        tgt_ports = len(self.tgt_node.input_ports())
        max_ports = max(src_ports, tgt_ports, 1)
        half_h = max_ports * 15

        self.src_node.set_pos(-450, -half_h)
        self.tgt_node.set_pos(450, -half_h)

        # Spread functoids in the middle
        functoids = [n for n in self.graph.all_nodes()
                     if isinstance(n, BaseFunctoid)]
        for i, fn in enumerate(functoids):
            y = -half_h + i * 120
            fn.set_pos(0, y)

        self.graph.fit_to_selection()

    # ---- export / generate ------------------------------------------------ #

    def _export_md(self):
        mappings = extract_mappings(self.graph)
        if not mappings:
            QtWidgets.QMessageBox.information(self, "Nothing", "No mappings defined.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export mapping", "mapping.md", "Markdown (*.md)")
        if not path:
            return
        md = render_markdown(mappings, self.source_file, self.target_file)
        Path(path).write_text(md, encoding="utf-8")
        QtWidgets.QMessageBox.information(
            self, "Exported", f"Wrote {len(mappings)} mappings to {path}")

    def _generate_python(self):
        mappings = extract_mappings(self.graph)
        if not mappings:
            QtWidgets.QMessageBox.information(self, "Nothing", "No mappings defined.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Generate Python", "generated_mapper.py", "Python (*.py)")
        if not path:
            return
        code = generate_python(mappings, self.source_file, self.target_file)
        Path(path).write_text(code, encoding="utf-8")
        QtWidgets.QMessageBox.information(
            self, "Generated",
            f"Wrote {len(mappings)} mappings as Python to:\n{path}")

    def _analyze_code(self):
        py_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose Python mapping file", "", "Python (*.py);;All (*)")
        if not py_path:
            return

        source_var, ok = QtWidgets.QInputDialog.getText(
            self, "Source variable", "Source variable name:", text="source")
        if not ok:
            return
        target_var, ok = QtWidgets.QInputDialog.getText(
            self, "Target variable", "Target variable name:", text="target")
        if not ok:
            return

        try:
            from code_to_mapping import analyze_file, render_html
        except ImportError as e:
            QtWidgets.QMessageBox.critical(
                self, "Missing", f"code_to_mapping.py not found.\n{e}")
            return

        try:
            extracted = analyze_file(py_path, source_var.strip(), target_var.strip())
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return

        if not extracted:
            QtWidgets.QMessageBox.warning(self, "None found", "No mappings extracted.")
            return

        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save HTML", str(Path(py_path).with_suffix(".mapping.html")),
            "HTML (*.html)")
        if not out_path:
            return

        html = render_html(extracted, Path(py_path).name, source_var, target_var)
        Path(out_path).write_text(html, encoding="utf-8")

        reply = QtWidgets.QMessageBox.question(
            self, "Done",
            f"Extracted {len(extracted)} mappings.\nOpen in browser?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.Yes:
            webbrowser.open(f"file://{Path(out_path).resolve()}")

    # ---- session ---------------------------------------------------------- #

    def _save_session(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save session", "mapping_session.json", "JSON (*.json)")
        if path:
            self.graph.save_session(path)

    def _load_session(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load session", "", "JSON (*.json)")
        if path:
            self.graph.load_session(path)
            # Restore type maps on schema nodes
            for n in self.graph.all_nodes():
                if isinstance(n, (SourceSchemaNode, TargetSchemaNode)):
                    n.restore_types()
                    if isinstance(n, SourceSchemaNode):
                        self.src_node = n
                        self.source_file = n.get_property("json_file") or "source.json"
                    else:
                        self.tgt_node = n
                        self.target_file = n.get_property("json_file") or "target.json"
            self._update_status()


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MapperWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
