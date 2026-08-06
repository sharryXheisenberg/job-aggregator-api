"""
sources/__init__.py

Auto-discovers every JobSource subclass in this package -- identical
pattern to parsers/__init__.py in the bank statement parser project.
Adding a new source means writing one new file here; nothing else changes.
"""

from __future__ import annotations
import pkgutil
import importlib
import inspect

from sources.base import JobSource

SOURCE_REGISTRY: dict[str, type[JobSource]] = {}

_package = importlib.import_module(__name__)
for _, module_name, _ in pkgutil.iter_modules(_package.__path__):
    if module_name == "base":
        continue
    module = importlib.import_module(f"{__name__}.{module_name}")
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, JobSource) and obj is not JobSource:
            SOURCE_REGISTRY[obj.source_name] = obj

del _package, module_name, module
