import build123d as bd
from cad import model

# Overall envelope, deliberately following Tivoo's rounded-rect proportions.
BASE_L = model.param("base_length", 136.0, min=120, max=150, unit="mm", step=1)
BASE_W = model.param("base_width", 114.0, min=108, max=135, unit="mm", step=1)
BASE_H = model.param("base_height", 29.0, min=24, max=42, unit="mm", step=1)
CORNER_R = model.param("corner_radius", 25.0, min=16, max=32, unit="mm", step=1)
WALL = 3.0
BOTTOM = 3.0

PLATTER_D = model.param("platter_diameter", 108.0, min=104, max=116, unit="mm", step=1)
PLATTER_T = 4.0

# 2:1 reduction, module 1 conceptual envelopes (50T : 25T)
MAIN_GEAR_PD = 50.0
PINION_PD = 25.0
GEAR_T = 5.0
SERVO_SHAFT_X = (MAIN_GEAR_PD + PINION_PD) / 2.0


def rounded_box(length, width, height, radius):
    part = bd.Box(length, width, height, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    vertical_edges = part.edges().filter_by(bd.Axis.Z)
    return part.fillet(radius, vertical_edges)


def color(part, value, label):
    part.color = value
    part.label = label
    return part


def moved(part, x=0, y=0, z=0):
    return bd.Pos(x, y, z) * part


@model
def tivoo_base_layout_v1():
    parts = []

    # Stationary lower shell: 3 mm floor + 3 mm rounded walls, open at the top.
    outer = rounded_box(BASE_L, BASE_W, BASE_H, CORNER_R)
    inner = rounded_box(
        BASE_L - 2 * WALL,
        BASE_W - 2 * WALL,
        BASE_H - BOTTOM + 1,
        max(2, CORNER_R - WALL),
    )
    inner = moved(inner, z=BOTTOM)
    shell = outer - inner
    parts.append(color(shell, "#66727b", "stationary_rounded_shell_136x114"))

    # Rotating platter on top.
    platter = moved(
        bd.Cylinder(PLATTER_D / 2, PLATTER_T, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
        z=BASE_H,
    )
    parts.append(color(platter, "#d7d9da", "rotating_platter_110mm"))

    # Central hollow path reserved for a miniature 6-wire slip ring.
    slip_ring = moved(
        bd.Cylinder(6.25, 18.2, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
        z=3.2,
    )
    parts.append(color(slip_ring, "#c9953f", "slip_ring_12p5x18p2"))

    # Conceptual 2:1 gear pair, kept above the electronics layer.
    main_gear = moved(
        bd.Cylinder((MAIN_GEAR_PD + 2.0) / 2, GEAR_T, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
        z=23.0,
    )
    parts.append(color(main_gear, "#e2b84b", "main_gear_50T_m1_envelope"))
    pinion = moved(
        bd.Cylinder((PINION_PD + 2.0) / 2, GEAR_T, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
        x=SERVO_SHAFT_X,
        z=23.0,
    )
    parts.append(color(pinion, "#e2b84b", "servo_pinion_25T_m1_envelope"))

    # Continuous-rotation micro-servo envelope (FS90R class).
    servo_body = moved(
        bd.Box(23.2, 12.5, 22.0, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
        x=44.0,
        y=0.0,
        z=3.2,
    )
    parts.append(color(servo_body, "#3b74b8", "FS90R_servo_envelope"))

    # Slim solderable carrier boards with female sockets.
    s3_carrier = moved(
        bd.Box(76, 34, 1.6, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
        x=-8, y=-27, z=3.2,
    )
    parts.append(color(s3_carrier, "#295f3a", "S3_carrier_76x34"))
    s3_board = moved(
        bd.Box(69.2, 25.4, 5.5, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
        x=-8, y=-27, z=8.0,
    )
    parts.append(color(s3_board, "#3d9b5a", "ESP32_S3_DevKitC1_envelope"))

    classic_carrier = moved(
        bd.Box(70, 34, 1.6, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
        x=-8, y=27, z=3.2,
    )
    parts.append(color(classic_carrier, "#295f3a", "classic_carrier_70x34"))
    classic_board = moved(
        bd.Box(61, 28, 5.5, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
        x=-8, y=27, z=8.0,
    )
    parts.append(color(classic_board, "#3d9b5a", "ESP32_classic_WROVER_USB_C_envelope"))

    # PCM5102 module and 5 V distribution / buck envelope in the remaining right-side corners.
    dac = moved(
        bd.Box(30, 22, 6, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
        x=45, y=30, z=4.0,
    )
    parts.append(color(dac, "#7a57a5", "PCM5102_module_envelope"))
    power = moved(
        bd.Box(30, 20, 7, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
        x=45, y=-31, z=4.0,
    )
    parts.append(color(power, "#a85757", "USB_C_power_distribution_envelope"))

    # Servo bulk capacitor, placed next to the motor branch.
    capacitor = moved(
        bd.Cylinder(6.5, 18, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
        x=54, y=-12, z=3.2,
    )
    parts.append(color(capacitor, "#222222", "servo_bulk_cap_1000_2200uF_envelope"))

    # Five stationary microphone boards behind the front wall.
    mic_specs = [
        (-42, 10, 7.6, "ICS43434_L"),
        (-21, 15, 12, "INMP441_L"),
        (0, 10, 7.6, "ICS43434_C"),
        (21, 15, 12, "INMP441_R"),
        (42, 10, 7.6, "ICS43434_R"),
    ]
    for x, sx, sz, name in mic_specs:
        mic = moved(
            bd.Box(sx, 2.0, sz, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
            x=x, y=54.5, z=11.0,
        )
        parts.append(color(mic, "#b14b8d" if "ICS" in name else "#4b88b1", name))

    # A simple Tivoo foot keep-out proxy: four pads estimated from product photos.
    for x in (-36, 36):
        for y in (-27, 27):
            pad = moved(
                bd.Cylinder(5.5, 1.8, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)),
                x=x, y=y, z=BASE_H + PLATTER_T,
            )
            parts.append(color(pad, "#333333", f"Tivoo_foot_proxy_{x}_{y}"))

    return bd.Compound(children=parts, label="Tivoo rotating base layout V1")


if __name__ == "__main__":
    tivoo_base_layout_v1()
