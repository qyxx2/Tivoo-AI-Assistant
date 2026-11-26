import build123d as bd
from cad import model

LENGTH = model.param("length", 120.0, min=60, max=200, unit="mm", step=1)
WIDTH = model.param("width", 110.0, min=60, max=200, unit="mm", step=1)
HEIGHT = model.param("height", 8.0, min=3, max=30, unit="mm", step=0.5)
CORNER_RADIUS = model.param("corner_radius", 12.0, min=2, max=30, unit="mm", step=1)


@model
def base():
    body = bd.Box(LENGTH, WIDTH, HEIGHT)
    vertical_edges = body.edges().filter_by(bd.Axis.Z)
    body = body.fillet(CORNER_RADIUS, vertical_edges)
    body.label = "rounded_rect_base"
    body.color = "#7f8c8d"
    return body


if __name__ == "__main__":
    base()
