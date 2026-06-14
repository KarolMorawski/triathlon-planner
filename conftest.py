"""Pytest config — puts the project root on sys.path so tests under tests/
can `import triathlon_core`, `import strength_core`, etc.

(An empty root-level conftest.py is enough: pytest prepends its directory to
sys.path, and the planner modules live flat in the repo root.)
"""
