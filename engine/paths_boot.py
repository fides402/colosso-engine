"""sys.path bootstrap + shared data dir.

The SampleHunter / loopforge engine modules are vendored under ``engine_libs/``
as *flat* modules (they import each other top-level, e.g. ``import clap_model``).
Importing this module once puts that folder on ``sys.path`` so those imports
resolve, exactly like running uvicorn with ``--app-dir`` did in SampleHunter.

DATA_DIR is where DIGMORE persists profiles, the listened store and per-profile
"seen releases" history. On Hugging Face Spaces set ``DIGMORE_DATA=/data`` (the
persistent volume); locally it defaults to ``engine/data``.
"""
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_LIBS = _HERE / "engine_libs"
if _LIBS.is_dir() and str(_LIBS) not in sys.path:
    sys.path.insert(0, str(_LIBS))

DATA_DIR = Path(os.environ.get("DIGMORE_DATA", str(_HERE / "data"))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

CSV_DIR = _HERE / "profiles_csv"
