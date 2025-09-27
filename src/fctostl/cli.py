# src/fc2stl/cli.py
# Typer-based CLI + shim that re-execs under freecadcmd when needed.

from __future__ import annotations

import os
import sys
import site
import shutil
import subprocess
import typer

from .core import process_barge2dave

app = typer.Typer(
    help="fc2stl: FreeCAD conversion toolkit (run standalone; re-execs under freecadcmd if needed).")


# --------- Shim helpers ------------------------------------------------------
def _under_freecad() -> bool:
    """Detect whether we're already inside FreeCAD's Python."""
    try:
        import FreeCAD  # type: ignore
        return True
    except Exception:
        return False


def _find_freecadcmd() -> str | None:
    """Find a freecadcmd binary in PATH or via FREECAD_CMD."""
    env_cmd = os.environ.get("FREECAD_CMD")
    if env_cmd and shutil.which(env_cmd):
        return env_cmd
    for name in ("freecadcmd", "freecadcmd.exe", "FreeCADCmd.exe", "freecadcmd-real"):
        found = shutil.which(name)
        if found:
            return found
    mac_guess = "/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd"
    if os.path.exists(mac_guess):
        return mac_guess
    return None


def _reexec_under_freecad() -> int:
    """
    Re-exec this CLI under FreeCAD's interpreter, injecting our src/site-packages paths.
    """
    freecadcmd = _find_freecadcmd()
    if not freecadcmd:
        typer.echo(
            "[error] FreeCAD (freecadcmd) not found. Install FreeCAD or set FREECAD_CMD=/path/to/freecadcmd.",
            err=True,
        )
        return 127

    # Compute import paths to inject with -P so FreeCAD can import this package
    pkg_dir = os.path.dirname(os.path.dirname(__file__))  # .../src/fc2stl
    src_root = os.path.dirname(pkg_dir) if os.path.basename(
        pkg_dir) == "fc2stl" else pkg_dir

    inject_paths: list[str] = [src_root]
    for p in site.getsitepackages() + [site.getusersitepackages()]:
        if p and os.path.isdir(p):
            inject_paths.append(p)

    cmd = [freecadcmd]
    for p in inject_paths:
        cmd += ["-P", p]
    # Re-run this module as a script entry point under Typer
    cmd += ["-m", "fc2stl.cli"]
    cmd += sys.argv[1:]

    return subprocess.call(cmd)


# --------- Subcommands -------------------------------------------------------
@app.command("barge2dave")
def barge2dave(
    doc: str = typer.Option(..., help="Path to FreeCAD .FCStd"),
    out: str = typer.Option(..., help="Directory for STL exports"),
    dave_out: str = typer.Option(..., help="Path to DAVE input file"),
    resource_prefix: str = typer.Option(
        ..., help="DAVE resource prefix, e.g. 'res: Muskox/geometry'"),
    hull_label_hint: str | None = typer.Option(
        None, help="Substring to find hull object"),
    hull_basename: str = typer.Option(
        "Hull", help="Basename for exported hull STL(s)"),
    length: float = typer.Option(..., help="Barge length [m]"),
    width: float = typer.Option(..., help="Barge width [m]"),
    deck_elev: float = typer.Option(5.5, help="Deck elevation [m]"),
    keel_elev: float = typer.Option(0.0, help="Keel elevation [m]"),
    tank_cut_elev: float = typer.Option(5.0, help="Tank cut elevation [m]"),
    barge_cut_elevations: float = typer.Option(
        5.3, help="Barge cut elevations [m]"),
    inner_dy: float = typer.Option(0.60, help="Total transverse shrink [m]"),
    inner_dz: float = typer.Option(0.40, help="Vertical shrink [m]"),
    n_long: int = typer.Option(6, help="Longitudinal bins"),
    n_trans: int = typer.Option(3, help="Transverse bins"),
    gap_x: float = typer.Option(0.25, help="Longitudinal gap [m]"),
    gap_y: float = typer.Option(0.15, help="Transverse gap [m]"),
    buoy_lin_defl: float = typer.Option(
        0.2, help="Buoyancy mesh linear deflection"),
    buoy_ang_defl: float = typer.Option(
        0.523599, help="Buoyancy mesh angular deflection (rad)"),
    tank_lin_defl: float = typer.Option(
        0.2, help="Tank mesh linear deflection"),
    tank_ang_defl: float = typer.Option(
        0.523599, help="Tank mesh angular deflection (rad)"),
    cfd_draft: float | None = typer.Option(
        None, help="Draft above keel for CFD clipping"),
    cfd_clip: str = typer.Option(
        "below", help="CFD keep side: below/submerged/above/emerged"),
    cfd_lin_defl: float = typer.Option(
        0.02, help="CFD mesh linear deflection"),
    cfd_ang_defl: float = typer.Option(
        0.174533, help="CFD mesh angular deflection (rad)"),
):
    """
    Export:
      • DAVE buoyancy hull (full, coarse) → <hull>.stl
      • CFD hull (clipped at draft, fine) → <hull>_cfd.stl (optional)
      • Tank STL set (grid from inner hull)
      • DAVE input file
    """
    if not _under_freecad():
        raise typer.Exit(code=_reexec_under_freecad())

    export_dir = os.path.abspath(out)
    os.makedirs(export_dir, exist_ok=True)

    try:
        process_barge2dave(
            doc_path=os.path.abspath(doc),
            hull_label_hint=hull_label_hint,
            export_dir=export_dir,
            dave_out_path=os.path.abspath(dave_out),
            resource_prefix=resource_prefix,
            length=length,
            width=width,
            deck_elev=deck_elev,
            keel_elev=keel_elev,
            tank_cut_elev=tank_cut_elev,
            barge_cut_elevations=barge_cut_elevations,
            inner_dy=inner_dy,
            inner_dz=inner_dz,
            n_long=n_long,
            n_trans=n_trans,
            gap_x=gap_x,
            gap_y=gap_y,
            buoy_lin_defl=buoy_lin_defl,
            buoy_ang_defl=buoy_ang_defl,
            cfd_draft=cfd_draft,
            cfd_clip=cfd_clip,
            cfd_lin_defl=cfd_lin_defl,
            cfd_ang_defl=cfd_ang_defl,
            tank_lin_defl=tank_lin_defl,
            tank_ang_defl=tank_ang_defl,
            hull_basename=hull_basename,
        )
    except Exception as exc:
        typer.echo(f"[error] {exc}", err=True)
        raise typer.Exit(code=1)


def main() -> None:
    # If invoked as a console script, ensure we bounce into FreeCAD when needed.
    if not _under_freecad():
        rc = _reexec_under_freecad()
        sys.exit(rc)
    app()


if __name__ == "__main__":
    main()
