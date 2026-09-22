"""Corrected virtual-analyser formulas supplied by the hackathon organisers."""

from __future__ import annotations

from collections.abc import Mapping

from neftecode_hackathon.contracts import AvtQualityResult


def _values(inputs: Mapping[str, float | None], names: tuple[str, ...]) -> list[float] | None:
    values = [inputs.get(name) for name in names]
    if any(value is None for value in values):
        return None
    return [float(value) for value in values if value is not None]


def calculate_vak(inputs: Mapping[str, float | None]) -> AvtQualityResult:
    """Calculate all available VAK outputs and fail closed per individual formula."""

    reasons: list[str] = []

    def calculate(name: str, required: tuple[str, ...], function):  # noqa: ANN001
        values = _values(inputs, required)
        if values is None:
            missing = ", ".join(key for key in required if inputs.get(key) is None)
            reasons.append(f"{name}: отсутствуют входы {missing}")
            return None
        try:
            return float(function(*values))
        except ZeroDivisionError:
            reasons.append(f"{name}: деление на ноль")
            return None

    t90 = calculate(
        "T90",
        ("T12", "F15", "W7", "T23", "F1", "F26"),
        lambda t12, f15, w7, t23, f1, f26: (
            162.998
            + 0.12945 * t12
            + 59.57 * (f15 / 2000)
            + 0.00036 * w7
            + 0.26366 * t23
            - 424.72638 * f1 / f26
        ),
    )
    t50 = calculate(
        "T50",
        ("P13", "F9", "T6"),
        lambda p13, f9, t6: 44.625 + 10.0224 * p13 + 0.06981 * f9 + 0.471 * t6,
    )
    cloud_point = calculate(
        "CloudPoint",
        ("F22", "W7", "F25", "F1", "T6", "F9", "T16"),
        lambda f22, w7, f25, f1, t6, f9, t16: (
            0.0002 * f22
            + 0.0021 * w7
            + 0.00008 * f25
            - 0.30656 * f1
            + 0.12018 * t6
            + 0.01916 * f9
            - 48.254
            - 0.05249 * t16
            + 0.00011
        ),
    )
    cfpp = calculate(
        "CFPP",
        ("T23", "P8", "F9", "W7", "P24"),
        lambda t23, p8, f9, w7, p24: (
            0.22088 * t23 - 102.375 - 47.75834 * p8 + 0.03862 * f9 + 43.60207 * w7 + 43.81849 * p24
        ),
    )
    t95 = calculate(
        "T95",
        ("F9", "F2", "T6", "LIMS_T95"),
        lambda f9, f2, t6, lims_t95: (
            0.03814 * f9 - 9.201 - 0.00002 * f2 + 0.50 * t6 + 0.48321 * lims_t95
        ),
    )
    return AvtQualityResult(
        t90_c=t90,
        t50_c=t50,
        t95_c=t95,
        cloud_point_c=cloud_point,
        cfpp_c=cfpp,
        reasons=tuple(reasons),
    )


def calculate_avt_cfpp(inputs: Mapping[str, float | None]) -> tuple[float | None, str | None]:
    """Calculate the corrected AVT CFPP expression with the extra bracket removed."""

    required = ("T33", "P67", "P4", "F65", "F32", "F30")
    values = _values(inputs, required)
    if values is None:
        return None, "AVT CFPP: отсутствуют обязательные входы"
    t33, p67, p4, f65, f32, f30 = values
    if f32 == 0:
        return None, "AVT CFPP: деление F65/F32 на ноль"
    return 31.40363 - 0.06784 * t33 + 17.411 * p67 - 8.11544 * p4 - 0.47309 * (
        f65 / f32 + f30
    ), None
