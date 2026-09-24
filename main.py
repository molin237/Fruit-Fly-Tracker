import sys
import os

# Add project root to path before any local imports.

# use __file__ here since get_app_dir() is in utils.config which isn't
# importable yet. PyInstaller sets sys.path itself 
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils.config import load_config
from app.gui import build_ui

# simple entry point, GUI handles everything else
if __name__ == "__main__":
    load_config()
    build_ui()