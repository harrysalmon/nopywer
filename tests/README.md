# Test Classification

## Resource-Independent Tests
These do **not** require project/resource files under `QGIS/` and are safe for fast migration checks.

- `tests/test_migration_confidence.py`
- `tests/test_representation_contract.py`

Run:

```bash
cd /Users/harrysalmon/repos/nowhere_power_grid/nopywer-main
/Applications/QGIS.app/Contents/MacOS/python -m unittest \
  tests.test_migration_confidence \
  tests.test_representation_contract -v
```

## Resource-File-Dependent Tests
These require specific repository data files (for example `QGIS/_cloud.qgs`, inventory/spreadsheet files, or fixed `grid.pkl` fixtures).

Committed modules:
- `tests/test_resource_real_project_contract.py`
  - uses real `main()` + `qgis2list()` + `find_optimal_layout()` against project resources.
  - reads resources through symlinks in `tests/resources/`.

Naming convention when adding them:
- file name prefix: `test_resource_*.py`
- module docstring must list required files explicitly.

Run pattern for resource-file-dependent tests:

```bash
cd /Users/harrysalmon/repos/nowhere_power_grid/nopywer-main
/Applications/QGIS.app/Contents/MacOS/python -m unittest discover -s tests -p 'test_resource_*.py' -v
```
