#!/usr/bin/env python3
import os
import ast
import importlib
import inspect
import sys
from typing import Any, Callable, List, Dict, Union, Optional


def has_type_annotations(obj: Any, check_fields: bool = False) -> bool:
    """
    Check if an object has type annotations.

    Args:
        obj: Object to check for type annotations.
        check_fields: If True, also checks dataclass field annotations.

    Returns:
        True if the object has type annotations, False otherwise.
    """
    # For functions
    if inspect.isfunction(obj):
        signature = inspect.signature(obj)
        return (
            all(
                param.annotation != param.empty
                for param in signature.parameters.values()
            )
            and signature.return_annotation != signature.empty
        )

    # For dataclasses
    if hasattr(obj, "__dataclass_fields__") and check_fields:
        return all(
            field.type is not None for field in obj.__dataclass_fields__.values()
        )

    return False


def find_missing_type_hints_and_docstrings(module_name: str) -> Dict[str, List[str]]:
    """
    Find public functions, methods, and dataclasses without type hints or docstrings.

    Args:
        module_name (str): Name of the module to inspect.

    Returns:
        Dict[str, List[str]]: Dictionary of missing features for each object.
    """
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        print(f"Could not import module: {module_name}", file=sys.stderr)
        return {}

    missing_features = {}

    # Check functions
    for name, func in inspect.getmembers(module, inspect.isfunction):
        if not name.startswith("_"):
            features_to_add = []

            # Check type hints
            if not has_type_annotations(func):
                features_to_add.append("type_hints")

            # Check docstring
            if not (func.__doc__ and len(func.__doc__.strip()) > 0):
                features_to_add.append("docstring")

            if features_to_add:
                missing_features[name] = features_to_add

    # Check classes (especially dataclasses)
    for name, cls in inspect.getmembers(module, inspect.isclass):
        if not name.startswith("_"):
            # Check dataclass fields
            if hasattr(cls, "__dataclass_fields__"):
                if not has_type_annotations(cls, check_fields=True):
                    missing_features[name] = ["type_hints"]
                elif name not in missing_features:
                    missing_features[name] = []

                # Check dataclass method type hints
                for meth_name, meth in inspect.getmembers(cls, inspect.isfunction):
                    if not meth_name.startswith("_"):
                        features_to_add = []
                        if not has_type_annotations(meth):
                            features_to_add.append("type_hints")
                        if not (meth.__doc__ and len(meth.__doc__.strip()) > 0):
                            features_to_add.append("docstring")

                        if features_to_add:
                            full_name = f"{name}.{meth_name}"
                            missing_features[full_name] = features_to_add

    return missing_features


def find_missing_in_codebase(
    base_path: str = "ralph",
) -> Dict[str, Dict[str, List[str]]]:
    """
    Find missing type hints and docstrings across all Python files in the codebase.

    Args:
        base_path (str): Base directory to search for Python modules.

    Returns:
        Dict[str, Dict[str, List[str]]]: Mapping of modules to their missing features.
    """
    missing_by_module = {}

    # Walk through the directory
    for root, _, files in os.walk(base_path):
        for file in files:
            if file.endswith(".py") and not file.startswith("__"):
                # Convert file path to module path
                module_path = os.path.join(root, file)
                module_name = (
                    module_path.replace("/", ".")
                    .replace(".py", "")
                    .replace(base_path + ".", "")
                )

                # Ignore test files and specific problematic modules
                if "test" in module_name or module_name in ["__init__"]:
                    continue

                try:
                    module_missing = find_missing_type_hints_and_docstrings(
                        f"ralph.{module_name}"
                    )
                    if module_missing:
                        missing_by_module[module_name] = module_missing
                except Exception as e:
                    print(
                        f"Error processing module {module_name}: {e}", file=sys.stderr
                    )

    return missing_by_module


def main():
    """
    Main entry point for type hint and docstring verification script.
    """
    missing_features = find_missing_in_codebase()

    if not missing_features:
        print(
            "✅ All public functions, methods, and dataclass attributes have type hints and docstrings!"
        )
        sys.exit(0)

    print("🚨 Missing type hints or docstrings found:")
    for module, functions in missing_features.items():
        print(f"\nModule: {module}")
        for func_name, issues in functions.items():
            print(f"  Item: {func_name}")
            print(f"    Missing: {', '.join(issues)}")

    sys.exit(1)


if __name__ == "__main__":
    main()
