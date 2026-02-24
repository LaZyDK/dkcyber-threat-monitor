# Lint tests for Python files in the project
# Uses flake8 for linting

import subprocess
import sys
import os


def get_python_files(directory):
    """Recursively get all Python files in a directory."""
    python_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))
    return python_files


def run_flake8(files):
    """Run flake8 linter on the given list of files."""
    result = subprocess.run([
        sys.executable, '-m', 'flake8', '--max-line-length=120', *files
    ], capture_output=True, text=True)
    return result


def test_lint():
    """Test that all Python files pass flake8 linting."""
    root_dirs = ['scripts', 'data']
    all_py_files = []
    for d in root_dirs:
        if os.path.exists(d):
            all_py_files.extend(get_python_files(d))
    if not all_py_files:
        print('No Python files found to lint.')
        return
    result = run_flake8(all_py_files)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
    assert result.returncode == 0, 'Lint errors found. See output above.'

if __name__ == '__main__':
    test_lint()
