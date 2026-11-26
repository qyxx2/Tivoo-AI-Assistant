import build123d as bd
from cad import model

BASE_L = model.param("base_length", 136.0, min=124, max=150, unit="mm", step=1)
BASE_W = model.param("base_width", 114.0, min=108, max=130, unit="mm", step=1)
BASE_H = model.param("base_height", 29.0, min=24, max=40, unit="mm", step=1)
CORNER_R = model.param("corner_radius", 25.0, min=18, max=32, unit="mm", step=1)
PLATTER_D = model.param("platter_diameter", 108.0, min=104, max=114, unit="mm", step=1)
PLATTER_T = 4.0

def rounded_box(length, width, height, radius):
    part = bd.Box(
        length, width, height,
        align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)
    )
    return part.fillet(radius, part.edges().filter_by(bd.Axis.Z))

def paint(part, value, label):
    part.color = value
    part.label = label
    return part

@model
def tivoo_base_external_v1():
    parts = []

    base = rounded_box(BASE_L, BASE_W, BASE_H, CORNER_R)
    parts.append(paint(base, "#6f7c85", "rounded_base_body"))

    # Thin dark reveal around the rotating plate makes the plate read as intentional,
    # rather than a circle randomly sitting on a box.
    reveal = bd.Cylinder(
        PLATTER_D / 2 + 0.9, 1.2,
        align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)
    )
    reveal = bd.Pos(0, 0, BASE_H - 0.2) * reveal
    parts.append(paint(reveal, "#22272b", "platter_reveal_gap"))

    platter = bd.Cylinder(
        PLATTER_D / 2, PLATTER_T,
        align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)
    )
    platter = bd.Pos(0, 0, BASE_H + 0.4) * platter
    parts.append(paint(platter, "#d7d9da", "rotating_platter_108mm"))

    # Tivoo silhouette proxy, only to judge proportion. Official 100 x 83 x 83 mm envelope.
    # We model 76 mm body + 7 mm feet so the visual total height stays 83 mm.
    body = bd.Box(
        100, 83, 76,
        align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)
    )
    try:
        body = body.fillet(15, body.edges())
    except Exception:
        body = body.fillet(15, body.edges().filter_by(bd.Axis.Z))
    body = bd.Pos(0, 0, BASE_H + PLATTER_T + 7.4) * body
    parts.append(paint(body, "#f1f1f0", "Tivoo_100x83_proxy"))

    # Four foot proxies. Positions are visual estimates from product photos,
    # deliberately not presented as factory dimensions.
    for x in (-36, 36):
        for y in (-27, 27):
            foot = bd.Cylinder(
                5.5, 7.0,
                align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)
            )
            foot = bd.Pos(x, y, BASE_H + PLATTER_T + 0.4) * foot
            parts.append(paint(foot, "#2a2a2a", f"Tivoo_foot_proxy_{x}_{y}"))

    return bd.Compound(children=parts, label="Tivoo base external proportion V1")

if __name__ == "__main__":
    tivoo_base_external_v1()
