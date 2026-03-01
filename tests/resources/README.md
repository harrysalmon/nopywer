# Test Resource Links

This directory holds symlinks to the real project resources used by
resource-file-dependent tests.

Links:
- `user_parameters.yaml` -> `../../user_parameters.yaml`
- `project_file.qgs` -> `../../../QGIS/_cloud.qgs`
- `power.gpkg` -> `../../../QGIS/power/power.gpkg`
- `power_balance.ods` -> `../../../QGIS/Power 2025 map balance.ods`
- `norg_power_inventory.ods` -> `../../../QGIS/power/norg_power_inventory.ods`

Purpose:
- Keep test resource references centralized.
- Make resource-dependent tests explicit and readable.
