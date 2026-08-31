# ObjectMapper

Tools for mapping fields between a source JSON object and a target JSON object,
either visually (a NodeGraphQt-based graph editor) or by analyzing existing
Python mapping code and rendering an interactive HTML diagram of it.

## Contents

- `json_mapper_v2.py` — visual mapping editor (PySide6 + NodeGraphQt). Load
  source/target JSON, draw connections and functoids (String, Math, Logic,
  Custom), export a Markdown mapping spec, and generate Python mapping code
  from the graph.
- `code_to_mapping.py` — reverse direction: given a Python file that maps a
  `source` object to a `target` object, extract the mappings via AST analysis
  and render a self-contained interactive HTML visualization.
- `v2_generated_mapper.py` — example of the Python code `json_mapper_v2.py`
  can generate from a graph.
- `v2_mapping.md` — example of the Markdown mapping spec `json_mapper_v2.py`
  can export.

## Setup

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

This installs `PySide6`, `NodeGraphQt`, and `setuptools` (the last is only
needed because NodeGraphQt imports `distutils`, which Python 3.12+ removed
from the standard library; `setuptools` provides a compatible shim).

## Usage

### Visual mapper (GUI)

```bash
python json_mapper_v2.py
```

Opens the NodeGraphQt editor. Load a source and target JSON file, connect
fields (optionally through functoid nodes), then export the mapping as
Markdown or generate Python mapping code.

### Analyze existing mapping code

```bash
python code_to_mapping.py mapping_impl.py --source source --target target --out mapping.html
```

Reads a Python file implementing a `source -> target` mapping and writes an
interactive HTML file (`mapping.html`) showing every extracted mapping with
hoverable arrows and a details table.

- `--source` / `--target` — variable names used in the mapping file
  (defaults: `source`, `target`).
- `--out` — output HTML path (default: `mapping_analysis.html`).

Example, using the included sample:

```bash
python code_to_mapping.py v2_generated_mapper.py --source source --target result --out mapping.html
```
