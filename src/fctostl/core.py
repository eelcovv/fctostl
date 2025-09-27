# Core geometry & export logic — runs under FreeCAD's Python runtime.

from __future__ import annotations

import os
from typing import List, Optional, Tuple


def require_freecad():
    """
    Lazy-import FreeCAD modules so normal Python can import this package
    (e.g., for --help) without having FreeCAD installed.
    """
    try:
        import FreeCAD as App  # type: ignore
        import Part  # type: ignore
        import MeshPart  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "This command must run under FreeCAD (use `freecadcmd`).") from exc
    return App, Part, MeshPart


# ---------- Geometry helpers -------------------------------------------------
def find_solid_by_label_hint(
    doc, label_hint: Optional[str]
) -> Tuple[object, object]:
    """Find the hull solid by label/name hint; fallback to the largest solid in the document."""
    App, Part, MeshPart = require_freecad()

    candidates = []
    for obj in doc.Objects:
        shape = getattr(obj, "Shape", None)
        if shape is None or not getattr(shape, "Solids", None):
            continue
        vol = sum(s.Volume for s in shape.Solids if getattr(
            s, "Volume", None) is not None)
        if vol > 0:
            candidates.append((obj, shape, vol))

    if not candidates:
        raise RuntimeError("No solid shapes found in the document.")

    if label_hint:
        key = label_hint.lower()
        by_hint = [t for t in candidates if key in (
            t[0].Label or "").lower() or key in (t[0].Name or "").lower()]
        if by_hint:
            by_hint.sort(key=lambda t: t[2], reverse=True)
            return by_hint[0][0], by_hint[0][1]

    candidates.sort(key=lambda t: t[2], reverse=True)
    return candidates[0][0], candidates[0][1]


def _deep_copy(shape):
    _, Part, _ = require_freecad()
    return Part.Shape(shape)


def make_inner_shape_via_intersection(shape, dy_total: float, dz: float):
    """Shrink via intersection of two lifted left/right copies to respect fillets."""
    App, Part, MeshPart = require_freecad()
    a = _deep_copy(shape)
    b = _deep_copy(shape)
    a.translate(App.Vector(0.0, -dy_total / 2.0, dz / 2.0))
    b.translate(App.Vector(0.0, +dy_total / 2.0, dz / 2.0))
    inner = a.common(b)
    if not inner.Solids:
        raise RuntimeError(
            "Intersection produced no solids; tune --inner-dy/--inner-dz.")
    try:
        inner = inner.removeSplitter()
    except Exception:
        pass
    return inner


def make_gap_cutters(bbox, n_long: int, n_trans: int, gap_x: float, gap_y: float, zmin: float, zmax: float):
    """Create rectangular cutter boxes to carve longitudinal/transverse gaps."""
    _, Part, _ = require_freecad()

    cutters: List[object] = []
    xmin, xmax = bbox.XMin, bbox.XMax
    ymin, ymax = bbox.YMin, bbox.YMax

    if n_long > 1 and gap_x > 0:
        dx = (xmax - xmin) / n_long
        for i in range(1, n_long):
            x_center = xmin + i * dx
            box = Part.makeBox(gap_x, (ymax - ymin) + 2.0, (zmax - zmin) + 2.0)
            box.translate(require_freecad()[0].Vector(
                x_center - gap_x / 2.0, ymin - 1.0, zmin - 1.0))
            cutters.append(box)

    if n_trans > 1 and gap_y > 0:
        dy = (ymax - ymin) / n_trans
        for j in range(1, n_trans):
            y_center = ymin + j * dy
            box = Part.makeBox((xmax - xmin) + 2.0, gap_y, (zmax - zmin) + 2.0)
            box.translate(require_freecad()[0].Vector(
                xmin - 1.0, y_center - gap_y / 2.0, zmin - 1.0))
            cutters.append(box)

    return cutters


def fuse_cutters(cutters: List[object]) -> Optional[object]:
    """Fuse all cutters into a single solid to speed up booleans."""
    if not cutters:
        return None
    u = cutters[0]
    for c in cutters[1:]:
        u = u.fuse(c)
    try:
        u = u.removeSplitter()
    except Exception:
        pass
    return u


def cut_and_extract_solids(base, cutter_union: Optional[object]):
    """Subtract cutter union from base; return separate solids."""
    result = base.cut(cutter_union) if cutter_union else base.copy()
    solids = list(result.Solids)
    if not solids:
        try:
            result2 = result.removeSplitter()
            solids = list(result2.Solids)
        except Exception:
            pass
    if not solids:
        raise RuntimeError(
            "No solids after cutting; adjust gap or inner shrink.")
    return solids


def classify_and_label_tanks(solids: List[object], n_long: int, n_trans: int) -> List[tuple[str, object]]:
    """Sort along +X; within each X-row by Y; label TNK{i}{P/C/S} or TNK{i}{j}."""
    solids_sorted = sorted(solids, key=lambda s: s.CenterOfMass.x)
    rows: List[List[object]] = []
    idx = 0
    for _ in range(n_long):
        row = solids_sorted[idx: idx + n_trans]
        if not row:
            break
        rows.append(sorted(row, key=lambda s: s.CenterOfMass.y))
        idx += n_trans

    labeled: List[tuple[str, object]] = []
    for i, row in enumerate(rows, start=1):
        if n_trans == 3 and len(row) == 3:
            tags = ["P", "C", "S"]
        else:
            tags = [str(k + 1) for k in range(len(row))]
        for j, solid in enumerate(row):
            labeled.append((f"TNK{i}{tags[j]}", solid))
    return labeled


def export_stl(shape, path: str, lin_defl: float, ang_defl: float) -> None:
    """Triangulate a Part.Shape and write STL."""
    App, Part, MeshPart = require_freecad()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mesh = MeshPart.meshFromShape(
        Shape=shape, LinearDeflection=lin_defl, AngularDeflection=ang_defl, Relative=False)
    mesh.write(path)


# ---------- CFD hull clipping ------------------------------------------------
def _clip_box_below(bbox, zmin: float, zcut: float):
    App, Part, _ = require_freecad()
    margin = 1.0
    box = Part.makeBox(
        (bbox.XMax - bbox.XMin) + 2 * margin,
        (bbox.YMax - bbox.YMin) + 2 * margin,
        (zcut - zmin) + 2 * margin,
    )
    box.translate(App.Vector(bbox.XMin - margin,
                  bbox.YMin - margin, zmin - margin))
    return box


def _clip_box_above(bbox, zcut: float, zmax: float):
    App, Part, _ = require_freecad()
    margin = 1.0
    box = Part.makeBox(
        (bbox.XMax - bbox.XMin) + 2 * margin,
        (bbox.YMax - bbox.YMin) + 2 * margin,
        (zmax - zcut) + 2 * margin,
    )
    box.translate(App.Vector(bbox.XMin - margin,
                  bbox.YMin - margin, zcut - margin))
    return box


def build_cfd_hull(
    hull_shape,
    keel_elev: float,
    draft_rel_to_keel: float,
    clip_mode: str,
    cfd_lin_defl: float,
    cfd_ang_defl: float,
    export_path: str,
) -> None:
    """Intersect hull with a clip box to get a capped, watertight CFD STL."""
    zcut = keel_elev + draft_rel_to_keel
    bbox = hull_shape.BoundBox
    if clip_mode in ("below", "submerged"):
        box = _clip_box_below(bbox, zmin=bbox.ZMin, zcut=zcut)
    elif clip_mode in ("above", "emerged"):
        box = _clip_box_above(bbox, zcut=zcut, zmax=bbox.ZMax)
    else:
        raise ValueError(
            "clip_mode must be 'below'/'submerged' or 'above'/'emerged'.")
    clipped = hull_shape.common(box)
    if not clipped.Solids:
        raise RuntimeError(
            "CFD clipping produced no solids; check draft/clip.")
    try:
        clipped = clipped.removeSplitter()
    except Exception:
        pass
    export_stl(clipped, export_path, cfd_lin_defl, cfd_ang_defl)


# ---------- DAVE writer ------------------------------------------------------
def write_dave_input(
    hull_basename: str,
    tank_names: List[str],
    resource_prefix: str,
    dave_out_path: str,
    length: float,
    width: float,
    deck_elev: float,
    keel_elev: float,
    tank_cut_elev: float,
    barge_cut_elevations: float,
) -> None:
    """Emit a DAVE input file with buoyancy hull + tanks."""
    def tank_sort_key(nm: str):
        digits = "".join(ch for ch in nm if ch.isdigit()) or "0"
        return (int(digits), nm)

    lines: List[str] = []
    lines += [
        "# Auto-generated by fc2stl barge2dave",
        "# General",
        f"deck_elevation\t{deck_elev}",
        f"keel_elevation\t{keel_elev}",
        f"tank_cut_elevation\t{tank_cut_elev}",
        f"barge_cut_elevations\t{barge_cut_elevations}",
        f"width\t{width}",
        f"length\t{length}",
        "Cd_air_long\t1.2",
        "Cd_water_long\t1.2",
        "Cd_air_trans\t1.2",
        "Cd_water_trans\t1.2",
        "",
        "*BallastTanks",
        "# Name\tresource\tpermeability\tdensity\tFill-pct\toff-x\toff-y\toff-z\trot-x\trot-y\trot-z\tscale-x\tscale-y\tscale-z\tinvert-normals",
    ]
    for tname in sorted(tank_names, key=tank_sort_key):
        lines.append(
            f"{tname}\t{resource_prefix}/{tname}.stl\t0.0\t-1\t0\t0\t0\t0\t0\t0\t0\t1\t1\t1\tFalse")

    lines += [
        "",
        "*Buoyancy",
        "# Name\tresource\toff-x\toff-y\toff-z\trot-x\trot-y\trot-z\tscale-x\tscale-y\tscale-z\tinvert-normals",
        f"HULL\t{resource_prefix}/{hull_basename}.stl\t0\t0\t0\t0\t0\t0\t1\t1\t1\tFalse",
        "",
        "*Draft_measurement_points",
        "AFT\t13\t0\t0",
        "BOW\t71.0\t0\t0",
        "PS\t44.0\t11.762\t0",
        "SB\t44.0\t-11.762\t0",
        "",
        "*Visuals",
        f"HULL\t{resource_prefix}/{hull_basename}.glb\t0\t0\t0\t90\t0\t0\t1\t1\t1",
        "",
        "*LightWeight",
        "lightweight\t1500\t44.\t0\t3.5\t0\t0\t84\t-12\t12\t0\t0\t0",
        "",
        "*Bollards",
        "",
    ]
    os.makedirs(os.path.dirname(dave_out_path), exist_ok=True)
    with open(dave_out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------- Orchestrator -----------------------------------------------------
def process_barge2dave(
    *,
    doc_path: str,
    hull_label_hint: Optional[str],
    export_dir: str,
    dave_out_path: str,
    resource_prefix: str,
    length: float,
    width: float,
    deck_elev: float,
    keel_elev: float,
    tank_cut_elev: float,
    barge_cut_elevations: float,
    inner_dy: float,
    inner_dz: float,
    n_long: int,
    n_trans: int,
    gap_x: float,
    gap_y: float,
    buoy_lin_defl: float,
    buoy_ang_defl: float,
    cfd_draft: Optional[float],
    cfd_clip: str,
    cfd_lin_defl: float,
    cfd_ang_defl: float,
    tank_lin_defl: float,
    tank_ang_defl: float,
    hull_basename: str,
) -> None:
    """Open the FCStd, generate tanks, export STLs, write DAVE file, and optionally CFD hull."""
    App, Part, MeshPart = require_freecad()

    doc = App.openDocument(doc_path)
    App.setActiveDocument(doc.Name)

    hull_obj, hull_shape = find_solid_by_label_hint(doc, hull_label_hint)
    print(f"[info] Using hull object: {hull_obj.Label} (Name={hull_obj.Name})")

    # Tanks: shrink, cut, label
    inner = make_inner_shape_via_intersection(
        hull_shape, dy_total=inner_dy, dz=inner_dz)
    cutters = make_gap_cutters(
        inner.BoundBox, n_long, n_trans, gap_x, gap_y, zmin=keel_elev, zmax=deck_elev)
    cutter_union = fuse_cutters(cutters) if cutters else None
    tank_solids = cut_and_extract_solids(inner, cutter_union)
    print(f"[info] Produced {len(tank_solids)} tank solids.")
    labeled = classify_and_label_tanks(tank_solids, n_long, n_trans)

    # Hull buoyancy STL (full hull)
    os.makedirs(export_dir, exist_ok=True)
    buoy_path = os.path.join(export_dir, f"{hull_basename}.stl")
    export_stl(hull_shape, buoy_path, buoy_lin_defl, buoy_ang_defl)
    print(f"[info] Exported DAVE buoyancy STL: {buoy_path}")

    # Hull CFD STL (optional)
    if cfd_draft is not None:
        cfd_path = os.path.join(export_dir, f"{hull_basename}_cfd.stl")
        build_cfd_hull(
            hull_shape=hull_shape,
            keel_elev=keel_elev,
            draft_rel_to_keel=cfd_draft,
            clip_mode=cfd_clip,
            cfd_lin_defl=cfd_lin_defl,
            cfd_ang_defl=cfd_ang_defl,
            export_path=cfd_path,
        )
        print(f"[info] Exported CFD STL: {cfd_path}")
    else:
        print("[info] CFD export skipped (no --cfd-draft).")

    # Export tanks
    tank_names: List[str] = []
    for name, solid in labeled:
        p = os.path.join(export_dir, f"{name}.stl")
        export_stl(solid, p, tank_lin_defl, tank_ang_defl)
        tank_names.append(name)
        print(f"[info] Exported tank STL: {p}")

    # DAVE input
    write_dave_input(
        hull_basename=hull_basename,
        tank_names=tank_names,
        resource_prefix=resource_prefix,
        dave_out_path=dave_out_path,
        length=length,
        width=width,
        deck_elev=deck_elev,
        keel_elev=keel_elev,
        tank_cut_elev=tank_cut_elev,
        barge_cut_elevations=barge_cut_elevations,
    )
    print(f"[done] Wrote DAVE input: {dave_out_path}")
