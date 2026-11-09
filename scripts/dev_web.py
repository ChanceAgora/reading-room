"""Run the worker-free API companion to Vite; public links remain on 18765."""
from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
runpy.run_module("book_library.dev_web", run_name="__main__")
