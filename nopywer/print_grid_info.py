import json
import numpy as np
from .get_constant_parameters import get_constant_parameters
from .graph_model import depth_list_from_graph

try:
    import networkx as nx
except Exception:
    nx = None


def print_grid_info(grid, cables_dict, phase_balance, has_no_phase, dlist):
    if (nx is not None) and isinstance(grid, nx.Graph):
        G = grid
        CONSTANTS = get_constant_parameters()
        V0 = CONSTANTS["V0"]
        PF = CONSTANTS["PF"]
        if dlist is None:
            dlist = depth_list_from_graph(G, root="generator")

        print("\n === info about the grid === \n")

        total_cum = np.array(G.nodes["generator"]["cum_power"], dtype=float)
        print(
            f"total power: {1e-3 * np.sum(total_cum):.0f}kW \t {np.round(1e-3 * total_cum, 1)}kW "
            + f"/ {np.round(total_cum / PF / V0)}A"
        )

        if phase_balance > 5:
            flag = " <<<<<<<<<<"
        else:
            flag = ""
        print(f"phase balance: {phase_balance.round(1)} % {flag}")

        for deep in range(len(dlist)):
            print(f"\t deepness {deep}")
            for load in dlist[deep]:
                node = G.nodes[load]
                pwr_per_phase = np.round(1e-3 * np.array(node["cum_power"]), 1).tolist()
                pwr_total = 1e-3 * np.sum(node["cum_power"])
                vdrop = float(node.get("vdrop_percent", 0.0))
                flag = " <<<<<<<<<<" if vdrop > 5 else ""
                print(
                    f"\t\t {load:20} cum_power={pwr_per_phase}kW, total {pwr_total:5.1f}kW, vdrop {vdrop:.1f}% {flag} "
                )

        print("\nLoads not connected to a cable:")
        for load in G.nodes():
            if load == "generator":
                continue
            needs_power = bool(np.double(np.array(G.nodes[load]["power"]) > 0).sum())
            if (G.in_degree(load) == 0) and needs_power:
                print(f"\t{load}")

        print(
            f"\nlist of loads on the spreadsheet that don't have a phase assigned: \n\t{has_no_phase} \n "
        )

        print("total power on other grids: ")
        subgrid_dict = {"tot": 0.0, "msg": ""}
        subgrid = {"red": subgrid_dict.copy(), "yellow": subgrid_dict.copy()}
        for load in G.nodes():
            phase = G.nodes[load].get("phase", None)
            if phase == "U":
                g = "red"
            elif phase == "Y":
                g = "yellow"
            else:
                g = None

            if g is not None:
                subgrid[g]["tot"] += np.array(G.nodes[load]["power"], dtype=float)
                subgrid[g]["msg"] += f"\t\t {load} ({G.nodes[load]['power']}W) \n"

        for subgrid_name, subgrid_val in subgrid.items():
            if isinstance(subgrid_val["tot"], float):
                tot = subgrid_val["tot"]
            elif len(subgrid_val["tot"]) > 1:
                tot = sum(subgrid_val["tot"])
            else:
                tot = subgrid_val["tot"]

            print(f"\t {subgrid_name} grid: {tot / 1e3:.1f}kW / {tot / V0:.1f}A")
            print(subgrid_val["msg"])

        return None

    CONSTANTS = get_constant_parameters()
    V0 = CONSTANTS["V0"]
    PF = CONSTANTS["PF"]

    print("\n === info about the grid === \n")

    print(
        f"total power: {1e-3 * np.sum(grid['generator'].cum_power):.0f}kW \t {np.round(1e-3 * grid['generator'].cum_power, 1)}kW "
        + f"/ {np.round(grid['generator'].cum_power / PF / V0)}A"
    )

    # --- print vdrop for each load, sorted by deepness
    if phase_balance > 5:
        flag = " <<<<<<<<<<"
    else:
        flag = ""
    print(f"phase balance: {phase_balance.round(1)} % {flag}")

    for deep in range(len(dlist)):
        print(f"\t deepness {deep}")
        for load in dlist[deep]:
            pwr_per_phase = np.round(1e-3 * grid[load].cum_power, 1).tolist()
            pwr_total = 1e-3 * np.sum(grid[load].cum_power)
            vdrop = grid[load].vdrop_percent
            if vdrop > 5:
                flag = " <<<<<<<<<<"
            else:
                flag = ""

            print(
                f"\t\t {load:20} cum_power={pwr_per_phase}kW, total {pwr_total:5.1f}kW, vdrop {vdrop:.1f}% {flag} "
            )

    # ---

    print("\nLoads not connected to a cable:")
    for load in grid.keys():
        needsPower = bool(np.double(grid[load].power > 0).sum())
        if (grid[load]._cable == []) and not (grid[load] == "generator") and needsPower:
            print(f"\t{load}")

    print(
        f"\nlist of loads on the spreadsheet that don't have a phase assigned: \n\t{has_no_phase} \n "
    )

    # --- compute and print loads on red and yellow grids
    print("total power on other grids: ")
    subgrid_dict = {"tot": 0.0, "msg": ""}
    subgrid = {"red": subgrid_dict.copy(), "yellow": subgrid_dict.copy()}
    for load in grid.keys():
        if grid[load].phase == "U":
            g = "red"
        elif grid[load].phase == "Y":
            g = "yellow"
        else:
            g = None

        if g is not None:
            subgrid[g]["tot"] += grid[load].power
            subgrid[g]["msg"] += f"\t\t {load} ({grid[load].power}W) \n"

    for subgrid_name, subgrid_val in subgrid.items():  #:g in subgrid.keys():
        if isinstance(subgrid_val["tot"], float):
            tot = subgrid_val["tot"]

        elif len(subgrid_val["tot"]) > 1:  # is a np.ndarray
            tot = sum(subgrid_val["tot"])

        else:
            tot = subgrid_val["tot"]

        print(f"\t {subgrid_name} grid: {tot / 1e3:.1f}kW / {tot / V0:.1f}A")
        print(subgrid_val["msg"])

    # --- print distro requirements at each load , sorted by deepness
    if 0:
        print("\ndistro requirements:")
        for deep in range(0, len(dlist)):
            print(f"\t deepness {deep}")
            for load in dlist[deep]:
                print(f"\t\t {load}:")
                distro = grid[load].distro
                print(f"\t\t\t in: {distro['in']}")
                print("\t\t\t out: ")
                for desc in distro["out"].keys():
                    print(f"\t\t\t\t {desc}: {distro['out'][desc]}")

    # --- print usng json (doesnt work if np arrays in dict)
    if 0:
        print("\n")
        print(json.dumps(cables_dict, sort_keys=True, indent=4))
        print(json.dumps(grid, sort_keys=True, indent=4))
