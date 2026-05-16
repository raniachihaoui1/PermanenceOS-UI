"""
GHPython component: Read a layout JSON file using a path relative to the .gh file.

No more hardcoded absolute paths — works on any computer that clones the repo.

INPUTS:
    relative_path  (str)  - Path relative to the .gh file folder. Required.
                            Examples:
                              "../layout/layout_residential_complex.json"
                              "../layout/layout_schema.json"
                              "../../layout_input/layout_schema.json"

OUTPUTS:
    json_string  (str)  - The contents of the JSON file as a string.
    full_path    (str)  - The resolved absolute path (for debugging).
    info         (str)  - Status message.
"""

import os
import json

# ---- Resolve input ----
try:
    rel = relative_path
    if rel is None or str(rel).strip() == "":
        rel = None
    else:
        rel = str(rel).strip()
except NameError:
    rel = None

# ---- Build absolute path from .gh file location ----
json_string = ""
full_path = ""
info = ""

if rel is None:
    info = "[ERROR] Connect a relative_path input (e.g. '../layout/layout_residential_complex.json')"
else:
  try:
    gh_file = ghenv.Component.OnPingDocument().FilePath
    if gh_file is None or gh_file == "":
        info = "[ERROR] Save the .gh file first — Grasshopper needs a file path to resolve relative paths."
    else:
        gh_folder = os.path.dirname(gh_file)
        resolved = os.path.normpath(os.path.join(gh_folder, rel))
        full_path = resolved

        if not os.path.isfile(resolved):
            info = "[ERROR] File not found: {}".format(resolved)
        else:
            with open(resolved, "r") as f:
                text = f.read()
            # Validate that it's valid JSON
            json.loads(text)
            json_string = text
            info = "[OK] Loaded {} ({} chars)".format(os.path.basename(resolved), len(text))
  except Exception as e:
    info = "[ERROR] {}".format(e)
