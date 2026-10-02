import sys
from pathlib import Path

# Rende importabile il pacchetto ``pubblicita`` anche lanciando pytest da altre cartelle.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
