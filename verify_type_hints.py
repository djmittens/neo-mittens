import ast
import os
import re
import sys
from typing import List, Any


def get_python_files(directory: str) -> List[str]:
    python_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                python_files.append(os.path.join(root, file))
    return python_files


def has_valid_type_hint(node: ast.AST) -> bool:
    """Check if a function has valid type hints."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False

    # Skip private functions
    if node.name.startswith("_"):
        return True

    # Check return annotation
    if not node.returns:
        return False

    # Check argument annotations
    for arg in node.args.args:
        if not arg.annotation:
            return False

    # Check docstring exists and is long enough
    docstring = ast.get_docstring(node)
    if not docstring or len(docstring.strip()) < 10:
        return False

    return True


def check_type_hints(file_path: str) -> List[str]:
    """Check type hints and return a list of functions missing type hints."""
    errors = []

    with open(file_path, "r") as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError:
            print(f"Error parsing {file_path}")
            return []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not has_valid_type_hint(node):
                errors.append(f"{file_path}:{node.lineno} - {node.name}")

    return errors


def main(target_file: str = None):
    if target_file:
        # Check specific file
        all_errors = check_type_hints(target_file)
    else:
        # Check all files in the project
        ralph_dir = "/Users/ngridinskiy/src/neo-mittens/ralph"
        python_files = get_python_files(ralph_dir)

        all_errors = []
        for file_path in python_files:
            if "tests" in file_path:
                continue  # Skip test files
            file_errors = check_type_hints(file_path)
            all_errors.extend(file_errors)

    if all_errors:
        print("Type hint errors found:")
        for error in all_errors:
            print(error)
        sys.exit(1)
    else:
        print("All public functions have type hints and docstrings!")
        sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main()
