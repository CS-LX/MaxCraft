"""3ds Max: Scripting > Run Script > choose this file."""
from pathlib import Path
import sys
root = str(Path(__file__).resolve().parent)
if root not in sys.path:
    sys.path.insert(0, root)
from maxcraft.ui import show
show()

