"""Run this once to apply the new UI to app.py."""
import ast, pathlib

HERE = pathlib.Path(__file__).parent
APP  = HERE / "app.py"
UI   = HERE / "_ui_new.py"

if not UI.exists():
    raise SystemExit("_ui_new.py not found — write it first")

head_lines = APP.read_text(encoding="utf-8").splitlines(keepends=True)[:836]
head_text  = "".join(head_lines)

# Patch _ensure_session to include new view_mode keys
OLD = '        "theme":           "dark",\n    }\n'
NEW = '        "theme":           "dark",\n        "view_mode":       "2D",\n        "compare_view_mode": "2D",\n    }\n'
if OLD in head_text:
    head_text = head_text.replace(OLD, NEW)

tail_text = UI.read_text(encoding="utf-8")
combined  = head_text + "\n" + tail_text

try:
    ast.parse(combined)
except SyntaxError as e:
    raise SystemExit(f"Syntax error: {e}")

APP.write_text(combined, encoding="utf-8")
print(f"OK — {len(combined.splitlines())} lines written to app.py")
