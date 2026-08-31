"""
code_to_mapping.py
==================

Reverse the workflow: given a Python file that implements a source→target
mapping (either mutable-target style `target.x = source.y` or return-dict
style `return {"x": source.y}`), extract every attribute mapping and emit
a self-contained HTML visualization with interactive arrows.

Supported patterns:
  * `target.field = source.something` and nested variants
  * `target["field"] = source["something"]`
  * `return {"field": source.something, ...}` with nested dict literals
  * `for item in source.items: ...` — binds `item` to `$.items[*]`
  * `[ {...} for item in source.items ]` list comprehensions
  * `target.some_list.append({...})` inside a loop
  * Arbitrary transformation expressions (any RHS is captured verbatim)

Usage (CLI):
    python code_to_mapping.py mapping_impl.py \\
        --source source --target target --out mapping.html

Usage (API):
    from code_to_mapping import analyze_file, render_html
    mappings = analyze_file("mapping_impl.py")
    Path("mapping.html").write_text(render_html(mappings, "mapping_impl.py"))
"""

from __future__ import annotations

import argparse
import ast
import html as html_esc
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# --------------------------------------------------------------------------- #
# Data model                                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class ExtractedMapping:
    target_path: str
    source_paths: list[str]     # every source-rooted path referenced on RHS
    expression: str             # RHS as source code
    direct: bool                # True if RHS is a bare source path chain
    line: int                   # line number in the analyzed file


# --------------------------------------------------------------------------- #
# AST helpers                                                                 #
# --------------------------------------------------------------------------- #

def _path_from_node(node: ast.AST, root_name: str) -> Optional[str]:
    """If ``node`` is an attribute/subscript chain rooted at ``Name(root_name)``,
    return a ``$``-rooted path string (``$.a.b[0]``). Else return None.
    """
    parts: list[str] = []
    cur: ast.AST = node
    while True:
        if isinstance(cur, ast.Attribute):
            parts.append("." + cur.attr)
            cur = cur.value
        elif isinstance(cur, ast.Subscript):
            seg = _subscript_segment(cur.slice)
            if seg is None:
                return None
            parts.append(seg)
            cur = cur.value
        elif isinstance(cur, ast.Name):
            if cur.id == root_name:
                return "$" + "".join(reversed(parts))
            return None
        else:
            return None


def _subscript_segment(slice_node: ast.AST) -> Optional[str]:
    if isinstance(slice_node, ast.Constant):
        if isinstance(slice_node.value, str):
            return "." + slice_node.value
        if isinstance(slice_node.value, int):
            return f"[{slice_node.value}]"
    return None


# --------------------------------------------------------------------------- #
# Analyzer                                                                    #
# --------------------------------------------------------------------------- #

class MappingAnalyzer(ast.NodeVisitor):
    def __init__(self, source_var: str, target_var: str):
        self.source_var = source_var
        self.target_var = target_var
        self.mappings: list[ExtractedMapping] = []
        # Loop variable name -> source path prefix (e.g. "item" -> "$.items[*]")
        self.loop_bindings: dict[str, str] = {}

    # ---- source path resolution ------------------------------------------ #

    def _resolve_source(self, node: ast.AST) -> Optional[str]:
        for name in (self.source_var, *self.loop_bindings.keys()):
            p = _path_from_node(node, name)
            if p is not None:
                if name in self.loop_bindings:
                    return self.loop_bindings[name] + p[1:]  # replace leading '$'
                return p
        return None

    def _all_source_paths(self, node: ast.AST) -> list[str]:
        found: list[str] = []

        def walk(n: ast.AST) -> None:
            # Method calls: extract path from receiver, ignore the method name
            # (e.g. source.customer.loyalty_tier.title() -> $.customer.loyalty_tier,
            # with .title() being the transformation).
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                p = self._resolve_source(n.func.value)
                if p is not None:
                    found.append(p)
                    for arg in n.args:
                        walk(arg)
                    for kw in n.keywords:
                        walk(kw)
                    return
            if isinstance(n, (ast.Attribute, ast.Subscript, ast.Name)):
                p = self._resolve_source(n)
                if p is not None:
                    found.append(p)
                    return
            for c in ast.iter_child_nodes(n):
                walk(c)

        walk(node)
        # Dedup preserving order
        seen: set[str] = set()
        return [p for p in found if not (p in seen or seen.add(p))]

    # ---- recording ------------------------------------------------------- #

    def _record(self, target_path: str, value_node: ast.AST, lineno: int) -> None:
        source_paths = self._all_source_paths(value_node)
        expression = ast.unparse(value_node)
        # "Direct" means RHS is exactly a bare source-path chain (no wrapping).
        direct = self._resolve_source(value_node) is not None
        self.mappings.append(ExtractedMapping(
            target_path=target_path,
            source_paths=source_paths,
            expression=expression,
            direct=direct,
            line=lineno,
        ))

    # ---- assignment: target.foo = ... ------------------------------------ #

    def visit_Assign(self, node: ast.Assign) -> None:
        for tgt in node.targets:
            tp = _path_from_node(tgt, self.target_var)
            if tp is None:
                continue
            if isinstance(node.value, ast.Dict):
                self._process_dict(node.value, tp, node.lineno)
            elif isinstance(node.value, ast.ListComp):
                self._process_listcomp(node.value, tp + "[*]", node.lineno)
            else:
                self._record(tp, node.value, node.lineno)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        tp = _path_from_node(node.target, self.target_var)
        if tp is not None:
            self._record(tp, node.value, node.lineno)
        self.generic_visit(node)

    # ---- return {...} ---------------------------------------------------- #

    def visit_Return(self, node: ast.Return) -> None:
        if isinstance(node.value, ast.Dict):
            self._process_dict(node.value, "$", node.lineno)
        elif isinstance(node.value, ast.ListComp):
            self._process_listcomp(node.value, "$[*]", node.lineno)
        self.generic_visit(node)

    # ---- for loops ------------------------------------------------------- #

    def visit_For(self, node: ast.For) -> None:
        binding = self._bind_from_iter(node.target, node.iter)
        saved = self.loop_bindings.copy()
        self.loop_bindings.update(binding)
        try:
            self.generic_visit(node)
        finally:
            self.loop_bindings = saved

    def _bind_from_iter(self, target: ast.AST, iter_node: ast.AST) -> dict[str, str]:
        """Return a mapping {loop_var: source_prefix[*]} for a `for X in Y` header."""
        # Special-case enumerate(...)
        actual_iter = iter_node
        item_target: Optional[ast.AST] = target
        if (
            isinstance(iter_node, ast.Call)
            and isinstance(iter_node.func, ast.Name)
            and iter_node.func.id == "enumerate"
            and iter_node.args
        ):
            actual_iter = iter_node.args[0]
            if isinstance(target, ast.Tuple) and len(target.elts) == 2:
                item_target = target.elts[1]

        source_paths = self._all_source_paths(actual_iter)
        if len(source_paths) == 1 and isinstance(item_target, ast.Name):
            return {item_target.id: source_paths[0] + "[*]"}
        return {}

    # ---- dict / list-comp helpers ---------------------------------------- #

    def _process_dict(
        self, dict_node: ast.Dict, target_prefix: str, lineno: int
    ) -> None:
        for k, v in zip(dict_node.keys, dict_node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            key_path = f"{target_prefix}.{k.value}"
            if isinstance(v, ast.Dict):
                self._process_dict(v, key_path, lineno)
            elif isinstance(v, ast.ListComp):
                self._process_listcomp(v, key_path + "[*]", lineno)
            elif isinstance(v, ast.List):
                for i, elem in enumerate(v.elts):
                    if isinstance(elem, ast.Dict):
                        self._process_dict(elem, f"{key_path}[{i}]", lineno)
                    else:
                        self._record(f"{key_path}[{i}]", elem, lineno)
            else:
                self._record(key_path, v, lineno)

    def _process_listcomp(
        self, comp: ast.ListComp, target_prefix: str, lineno: int
    ) -> None:
        # Push bindings for each generator
        new_bindings: dict[str, str] = {}
        for gen in comp.generators:
            new_bindings.update(self._bind_from_iter(gen.target, gen.iter))
        saved = self.loop_bindings.copy()
        self.loop_bindings.update(new_bindings)
        try:
            if isinstance(comp.elt, ast.Dict):
                self._process_dict(comp.elt, target_prefix, lineno)
            else:
                self._record(target_prefix, comp.elt, lineno)
        finally:
            self.loop_bindings = saved

    # ---- target.some_list.append({...}) ---------------------------------- #

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in ("append", "extend")
            and node.args
        ):
            base_tp = _path_from_node(node.func.value, self.target_var)
            if base_tp is not None:
                arg = node.args[0]
                if isinstance(arg, ast.Dict):
                    self._process_dict(arg, base_tp + "[*]", node.lineno)
                elif isinstance(arg, ast.ListComp):
                    self._process_listcomp(arg, base_tp + "[*]", node.lineno)
                else:
                    self._record(base_tp + "[*]", arg, node.lineno)
        self.generic_visit(node)


# --------------------------------------------------------------------------- #
# Public entry points                                                         #
# --------------------------------------------------------------------------- #

def analyze_source(
    code: str, source_var: str = "source", target_var: str = "target"
) -> list[ExtractedMapping]:
    tree = ast.parse(code)
    analyzer = MappingAnalyzer(source_var, target_var)
    analyzer.visit(tree)
    return analyzer.mappings


def analyze_file(
    path: str, source_var: str = "source", target_var: str = "target"
) -> list[ExtractedMapping]:
    code = Path(path).read_text(encoding="utf-8")
    return analyze_source(code, source_var, target_var)


# --------------------------------------------------------------------------- #
# HTML rendering                                                              #
# --------------------------------------------------------------------------- #

# Use @@PLACEHOLDER@@ tokens so CSS/JS braces are safe.
HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Mapping analysis — @@SOURCE_FILE@@</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 24px 32px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #fafaf9;
    color: #1c1c1c;
    line-height: 1.5;
  }
  h1 { font-size: 22px; margin: 0 0 4px; font-weight: 500; }
  h2 { font-size: 16px; margin: 28px 0 12px; font-weight: 500; }
  .meta { color: #666; font-size: 13px; margin-bottom: 20px; }
  .meta code { background: #eee; padding: 1px 6px; border-radius: 3px; font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 12px; }

  .legend {
    display: flex; gap: 22px; margin: 12px 0 20px;
    font-size: 12px; color: #666; align-items: center; flex-wrap: wrap;
  }
  .legend .swatch { display: inline-block; width: 22px; height: 2px; vertical-align: middle; margin-right: 6px; }
  .legend .badge-mini {
    display: inline-block; width: 14px; height: 14px; border-radius: 50%;
    background: #EF9F27; color: #412402; text-align: center;
    line-height: 14px; font-size: 9px; font-weight: bold; margin-right: 6px;
    vertical-align: middle;
  }

  .container {
    position: relative;
    display: grid;
    grid-template-columns: 1fr 140px 1fr;
    gap: 0;
    background: white;
    border: 1px solid #e5e5e5;
    border-radius: 8px;
    padding: 20px;
    overflow: hidden;
  }
  .col { min-width: 0; }
  .col h3 {
    font-size: 11px; font-weight: 500; color: #888;
    text-transform: uppercase; letter-spacing: 0.08em;
    margin: 0 0 12px;
  }
  .col ul { list-style: none; margin: 0; padding: 0; }
  .col li {
    display: flex; align-items: center; gap: 10px;
    padding: 5px 6px;
    font-family: "SF Mono", Menlo, Consolas, monospace;
    font-size: 12px; color: #222;
    border-radius: 3px;
    transition: background-color 0.15s;
    position: relative;
    z-index: 2;
  }
  .col.source li { justify-content: space-between; }
  .col.source .path { flex: 1; word-break: break-all; }
  .col.target li .path { word-break: break-all; }
  .col li.hl { background: #fff7e6; }
  .dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
  .col.source .dot { background: #2d7dd2; }
  .col.target .dot { background: #5cb85c; }

  #arrows-svg {
    position: absolute; top: 0; left: 0;
    width: 100%; height: 100%;
    pointer-events: none; z-index: 1;
  }
  #arrows-svg path {
    pointer-events: stroke; fill: none;
    stroke-width: 1.5; cursor: pointer;
    transition: stroke-width 0.15s, opacity 0.15s;
  }
  #arrows-svg path.direct { stroke: #999; }
  #arrows-svg path.transform { stroke: #BA7517; }
  #arrows-svg path.active { stroke-width: 3; }
  #arrows-svg path.dim { opacity: 0.12; }
  #arrows-svg circle.badge { fill: #EF9F27; stroke: white; stroke-width: 1.2; pointer-events: none; }
  #arrows-svg text.badge {
    font-family: "SF Mono", Menlo, Consolas, monospace;
    font-size: 9px; fill: #412402; text-anchor: middle;
    dominant-baseline: central; font-weight: 700; pointer-events: none;
  }

  #tooltip {
    position: fixed;
    background: #1c1c1c; color: #f5f5f5;
    padding: 8px 10px;
    border-radius: 5px;
    font-family: "SF Mono", Menlo, Consolas, monospace;
    font-size: 12px;
    max-width: 460px;
    white-space: pre-wrap; word-break: break-word;
    pointer-events: none;
    z-index: 100;
    opacity: 0; transition: opacity 0.12s;
    box-shadow: 0 4px 16px rgba(0,0,0,0.25);
  }
  #tooltip.show { opacity: 1; }
  #tooltip .tt-head {
    font-size: 10px; color: #999; margin-bottom: 4px;
    text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500;
  }

  .details table {
    width: 100%; border-collapse: collapse;
    font-size: 12px; background: white;
    border: 1px solid #e5e5e5; border-radius: 8px; overflow: hidden;
  }
  .details th, .details td {
    padding: 9px 12px; text-align: left;
    border-bottom: 1px solid #f0f0f0; vertical-align: top;
  }
  .details th {
    background: #f7f7f5; font-weight: 500;
    color: #666; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.05em;
  }
  .details tr:last-child td { border-bottom: none; }
  .details tr.active { background: #fff7e6; }
  .details code {
    font-family: "SF Mono", Menlo, Consolas, monospace;
    font-size: 11.5px; background: #f4f4f2;
    padding: 2px 6px; border-radius: 3px;
    color: #1c1c1c; word-break: break-word;
  }
  .details .kind {
    display: inline-block; font-size: 10px;
    padding: 2px 8px; border-radius: 10px; font-weight: 500;
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .details .kind.direct { background: #eee; color: #666; }
  .details .kind.transform { background: #FAEEDA; color: #633806; }
</style>
</head>
<body>
<h1>Mapping analysis</h1>
<div class="meta">
  Extracted from <code>@@SOURCE_FILE@@</code> &nbsp;·&nbsp;
  source variable: <code>@@SOURCE_VAR@@</code>, target variable: <code>@@TARGET_VAR@@</code> &nbsp;·&nbsp;
  <strong>@@MAPPING_COUNT@@</strong> mapping@@PLURAL@@ detected
</div>

<div class="legend">
  <span><span class="swatch" style="background:#999"></span>direct copy</span>
  <span><span class="swatch" style="background:#BA7517"></span><span class="badge-mini">ƒ</span>transformation</span>
  <span style="color:#999;font-style:italic">hover an arrow, dot, or path to inspect the logic</span>
</div>

<div class="container" id="mapping-container">
  <div class="col source">
    <h3>Source paths</h3>
    <ul id="source-list">@@SOURCE_ITEMS@@</ul>
  </div>
  <div></div>
  <div class="col target">
    <h3>Target paths</h3>
    <ul id="target-list">@@TARGET_ITEMS@@</ul>
  </div>
  <svg id="arrows-svg" xmlns="http://www.w3.org/2000/svg"></svg>
</div>

<div id="tooltip"></div>

<div class="details">
  <h2>Mapping details</h2>
  <table id="details-table">
    <thead>
      <tr>
        <th>#</th><th>Target path</th><th>Source path(s)</th>
        <th>Kind</th><th>Code / logic</th><th>Line</th>
      </tr>
    </thead>
    <tbody>@@TABLE_ROWS@@</tbody>
  </table>
</div>

<script>
const MAPPINGS = @@MAPPINGS_JSON@@;

const svg = document.getElementById('arrows-svg');
const container = document.getElementById('mapping-container');
const tooltip = document.getElementById('tooltip');
const detailRows = Array.from(document.querySelectorAll('#details-table tbody tr'));

function attrEscape(s) {
  return s.replace(/"/g, '\\"');
}

function findLi(listId, path) {
  const items = document.querySelectorAll('#' + listId + ' li');
  for (const li of items) if (li.dataset.path === path) return li;
  return null;
}

function centerOfDot(li) {
  const dot = li.querySelector('.dot');
  const dr = dot.getBoundingClientRect();
  const cr = container.getBoundingClientRect();
  return { x: dr.left - cr.left + dr.width / 2, y: dr.top - cr.top + dr.height / 2 };
}

function cubicPoint(p0, p1, p2, p3, t) {
  const mt = 1 - t;
  return mt*mt*mt*p0 + 3*mt*mt*t*p1 + 3*mt*t*t*p2 + t*t*t*p3;
}

function draw() {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const cr = container.getBoundingClientRect();
  svg.setAttribute('viewBox', '0 0 ' + cr.width + ' ' + cr.height);

  MAPPINGS.forEach((m, idx) => {
    const tgtLi = findLi('target-list', m.target_path);
    if (!tgtLi) return;
    const tPos = centerOfDot(tgtLi);

    m.source_paths.forEach(sp => {
      const srcLi = findLi('source-list', sp);
      if (!srcLi) return;
      const sPos = centerOfDot(srcLi);

      const dx = Math.max(60, Math.abs(tPos.x - sPos.x) * 0.5);
      const c1x = sPos.x + dx, c1y = sPos.y;
      const c2x = tPos.x - dx, c2y = tPos.y;
      const d = 'M ' + sPos.x + ' ' + sPos.y +
                ' C ' + c1x + ' ' + c1y + ', ' + c2x + ' ' + c2y +
                ', ' + tPos.x + ' ' + tPos.y;

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d);
      path.setAttribute('class', m.direct ? 'direct' : 'transform');
      path.dataset.idx = idx;
      path.dataset.src = sp;
      svg.appendChild(path);

      if (!m.direct) {
        const bx = cubicPoint(sPos.x, c1x, c2x, tPos.x, 0.5);
        const by = cubicPoint(sPos.y, c1y, c2y, tPos.y, 0.5);
        const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        c.setAttribute('cx', bx); c.setAttribute('cy', by); c.setAttribute('r', 8);
        c.setAttribute('class', 'badge');
        svg.appendChild(c);
        const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        t.setAttribute('x', bx); t.setAttribute('y', by);
        t.setAttribute('class', 'badge');
        t.textContent = 'ƒ';
        svg.appendChild(t);
      }
    });
  });
  attachHandlers();
}

function showTooltip(idx, x, y) {
  const m = MAPPINGS[idx];
  const kind = m.direct ? 'direct copy' : 'transformation';
  tooltip.innerHTML =
    '<div class="tt-head">#' + (idx + 1) + ' · ' + kind + ' · line ' + m.line + '</div>' +
    m.target_path + ' ← ' + m.expression;
  tooltip.classList.add('show');
  const tr = tooltip.getBoundingClientRect();
  let left = x + 14, top = y + 14;
  if (left + tr.width > window.innerWidth - 12) left = window.innerWidth - tr.width - 12;
  if (top + tr.height > window.innerHeight - 12) top = y - tr.height - 14;
  tooltip.style.left = left + 'px';
  tooltip.style.top = top + 'px';
}
function hideTooltip() { tooltip.classList.remove('show'); }

function highlightMapping(idx) {
  document.querySelectorAll('#arrows-svg path').forEach(p => {
    const pi = parseInt(p.dataset.idx);
    p.classList.toggle('active', pi === idx);
    p.classList.toggle('dim', pi !== idx);
  });
  document.querySelectorAll('.col li').forEach(li => li.classList.remove('hl'));
  const m = MAPPINGS[idx];
  findLi('target-list', m.target_path)?.classList.add('hl');
  m.source_paths.forEach(sp => findLi('source-list', sp)?.classList.add('hl'));
  detailRows.forEach((r, i) => r.classList.toggle('active', i === idx));
}

function highlightByPath(p) {
  const idxes = [];
  MAPPINGS.forEach((m, i) => {
    if (m.target_path === p || m.source_paths.includes(p)) idxes.push(i);
  });
  if (!idxes.length) return;
  const set = new Set(idxes);
  document.querySelectorAll('#arrows-svg path').forEach(pp => {
    const pi = parseInt(pp.dataset.idx);
    pp.classList.toggle('active', set.has(pi));
    pp.classList.toggle('dim', !set.has(pi));
  });
  detailRows.forEach((r, i) => r.classList.toggle('active', set.has(i)));
}

function clearHighlight() {
  document.querySelectorAll('#arrows-svg path').forEach(p => {
    p.classList.remove('active'); p.classList.remove('dim');
  });
  document.querySelectorAll('.col li').forEach(li => li.classList.remove('hl'));
  detailRows.forEach(r => r.classList.remove('active'));
}

function attachHandlers() {
  document.querySelectorAll('#arrows-svg path').forEach(p => {
    const idx = parseInt(p.dataset.idx);
    p.addEventListener('mouseenter', e => { highlightMapping(idx); showTooltip(idx, e.clientX, e.clientY); });
    p.addEventListener('mousemove',  e => showTooltip(idx, e.clientX, e.clientY));
    p.addEventListener('mouseleave', () => { clearHighlight(); hideTooltip(); });
  });
  document.querySelectorAll('#source-list li, #target-list li').forEach(li => {
    li.addEventListener('mouseenter', () => highlightByPath(li.dataset.path));
    li.addEventListener('mouseleave', clearHighlight);
  });
  detailRows.forEach((r, i) => {
    r.addEventListener('mouseenter', () => highlightMapping(i));
    r.addEventListener('mouseleave', clearHighlight);
  });
}

window.addEventListener('load', draw);
window.addEventListener('resize', draw);
</script>
</body>
</html>
"""


def render_html(
    mappings: list[ExtractedMapping],
    source_file: str,
    source_var: str = "source",
    target_var: str = "target",
) -> str:
    # Unique source paths (preserve first-seen order)
    source_paths: list[str] = []
    seen_s: set[str] = set()
    for m in mappings:
        for sp in m.source_paths:
            if sp not in seen_s:
                seen_s.add(sp)
                source_paths.append(sp)
    # Unique target paths
    target_paths: list[str] = []
    seen_t: set[str] = set()
    for m in mappings:
        if m.target_path not in seen_t:
            seen_t.add(m.target_path)
            target_paths.append(m.target_path)

    def li(path: str) -> str:
        esc = html_esc.escape(path, quote=True)
        return (f'<li data-path="{esc}">'
                f'<span class="dot"></span>'
                f'<span class="path">{esc}</span></li>')

    source_items = "\n".join(li(p) for p in source_paths)
    target_items = "\n".join(li(p) for p in target_paths)

    def row(i: int, m: ExtractedMapping) -> str:
        kind = "direct" if m.direct else "transform"
        src_html = "<br>".join(
            f"<code>{html_esc.escape(sp)}</code>" for sp in m.source_paths
        ) or "&mdash;"
        return (
            f'<tr data-idx="{i}">'
            f"<td>{i + 1}</td>"
            f"<td><code>{html_esc.escape(m.target_path)}</code></td>"
            f"<td>{src_html}</td>"
            f'<td><span class="kind {kind}">{kind}</span></td>'
            f"<td><code>{html_esc.escape(m.expression)}</code></td>"
            f"<td>{m.line}</td>"
            f"</tr>"
        )

    table_rows = "\n".join(row(i, m) for i, m in enumerate(mappings))

    mappings_json = json.dumps([{
        "target_path": m.target_path,
        "source_paths": m.source_paths,
        "expression": m.expression,
        "direct": m.direct,
        "line": m.line,
    } for m in mappings])

    return (HTML_TEMPLATE
            .replace("@@SOURCE_FILE@@", html_esc.escape(source_file))
            .replace("@@SOURCE_VAR@@", html_esc.escape(source_var))
            .replace("@@TARGET_VAR@@", html_esc.escape(target_var))
            .replace("@@MAPPING_COUNT@@", str(len(mappings)))
            .replace("@@PLURAL@@", "" if len(mappings) == 1 else "s")
            .replace("@@SOURCE_ITEMS@@", source_items)
            .replace("@@TARGET_ITEMS@@", target_items)
            .replace("@@TABLE_ROWS@@", table_rows)
            .replace("@@MAPPINGS_JSON@@", mappings_json))


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze a Python mapping file and emit an HTML visualization."
    )
    parser.add_argument("file", help="Python file that implements the mapping")
    parser.add_argument("--source", default="source",
                        help="Source variable name (default: source)")
    parser.add_argument("--target", default="target",
                        help="Target variable name (default: target)")
    parser.add_argument("--out", default="mapping_analysis.html",
                        help="Output HTML file (default: mapping_analysis.html)")
    args = parser.parse_args()

    mappings = analyze_file(args.file, args.source, args.target)
    if not mappings:
        print(
            f"No mappings extracted. Check the --source/--target variable names "
            f"(got source={args.source!r}, target={args.target!r}).",
            file=sys.stderr,
        )
        return 1

    html_out = render_html(mappings, args.file, args.source, args.target)
    Path(args.out).write_text(html_out, encoding="utf-8")
    print(f"Analyzed {args.file}: {len(mappings)} mapping(s)")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
