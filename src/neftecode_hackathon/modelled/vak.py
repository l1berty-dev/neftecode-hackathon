"""Versioned organizer-corrected virtual-analyser formulae.

These equations are deterministic transformations, not intervention models. Missing
inputs and zero denominators remain missing instead of being silently imputed.
"""

from __future__ import annotations

from collections.abc import Mapping

from neftecode_hackathon.contracts import AvtQualityResult

VAK_VERSION = "organizer-corrected-v1-20260915"


def _formula(values: Mapping[str, float | None], required: tuple[str, ...], function):
    if any(values.get(key) is None for key in required):
        return None
    try:
        return float(function(*(float(values[key]) for key in required)))
    except ZeroDivisionError:
        return None


def evaluate_avt_vak(values: Mapping[str, float | None]) -> AvtQualityResult:
    """Evaluate the corrected AVT B5 CFPP expression when all inputs exist."""

    required = ("T33", "P67", "P4", "F65", "F32", "F30")
    cfpp = _formula(
        values,
        required,
        lambda t33, p67, p4, f65, f32, f30: (
            31.40363 - 0.06784 * t33 + 17.411 * p67 - 8.11544 * p4 - 0.47309 * (f65 / f32 + f30)
        ),
    )
    reason = (
        f"AVT CFPP calculated by {VAK_VERSION}; F65/F32 + F30 grouping is applied."
        if cfpp is not None
        else "AVT CFPP is unavailable: a required input is missing or F32 is zero."
    )
    return AvtQualityResult(
        t90_c=None,
        t50_c=None,
        t95_c=None,
        cloud_point_c=None,
        cfpp_c=cfpp,
        reasons=(reason,),
    )


def evaluate_hydrotreating_vak(values: Mapping[str, float | None]) -> AvtQualityResult:
    """Evaluate the five corrected 24-2000 VAK formulae.

    The returned DTO is shared with AVT for transport convenience. The caller must
    preserve the ``ht:`` namespace and provide only facts available at evaluation time.
    """

    t90 = _formula(
        values,
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
    t50 = _formula(
        values,
        ("P13", "F9", "T6"),
        lambda p13, f9, t6: 44.625 + 10.0224 * p13 + 0.06981 * f9 + 0.471 * t6,
    )
    cloud = _formula(
        values,
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
    cfpp = _formula(
        values,
        ("T23", "P8", "F9", "W7", "P24"),
        lambda t23, p8, f9, w7, p24: (
            0.22088 * t23 - 102.375 - 47.75834 * p8 + 0.03862 * f9 + 43.60207 * w7 + 43.81849 * p24
        ),
    )
    t95 = _formula(
        values,
        ("F9", "F2", "T6", "LIMS:24-2000.Pipeline.95%.T"),
        lambda f9, f2, t6, lab: 0.03814 * f9 - 9.201 - 0.00002 * f2 + 0.50 * t6 + 0.48321 * lab,
    )
    missing = sum(item is None for item in (t90, t50, t95, cloud, cfpp))
    return AvtQualityResult(
        t90_c=t90,
        t50_c=t50,
        t95_c=t95,
        cloud_point_c=cloud,
        cfpp_c=cfpp,
        reasons=(f"Hydrotreating VAK {VAK_VERSION}: {5 - missing}/5 formulae available.",),
    )
