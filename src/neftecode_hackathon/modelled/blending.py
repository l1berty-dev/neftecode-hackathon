"""Small deterministic blending optimiser for editable demonstration scenarios."""

from __future__ import annotations

from collections.abc import Iterator

from neftecode_hackathon.contracts import (
    Admissibility,
    BlendComponent,
    BlendRecipe,
    BlendShare,
    CheckCategory,
    CheckResult,
    ModelledProductQuality,
    ProductSpecification,
)


def _compositions(parts: int, total: int) -> Iterator[tuple[int, ...]]:
    if parts == 1:
        yield (total,)
        return
    for value in range(total + 1):
        for rest in _compositions(parts - 1, total - value):
            yield (value, *rest)


def _check(
    code: str, actual: float | None, limit: float, lower_bound: bool, unit: str
) -> CheckResult:
    passed = None if actual is None else (actual >= limit if lower_bound else actual <= limit)
    relation = "не ниже" if lower_bound else "не выше"
    return CheckResult(
        code=code,
        passed=passed,
        category=CheckCategory.QUALITY,
        message=f"Показатель должен быть {relation} обязательного предела",
        actual=actual,
        limit=limit,
        unit=unit,
    )


def optimise_blend(
    components: tuple[BlendComponent, ...],
    specification: ProductSpecification,
    additive_ppm: float,
    *,
    min_additive_ppm: float,
    max_additive_ppm: float,
    nominal_cetane_per_1000: float,
    conservative_cetane_per_1000: float,
    additive_relative_cost: float,
) -> BlendRecipe:
    limitations = ["T95 смешивается линейно только как модельное приближение."]
    if additive_ppm > max_additive_ppm:
        return BlendRecipe(
            shares=(),
            additive_ppm=additive_ppm,
            quality=ModelledProductQuality(
                sulfur_mg_kg=None,
                sulfur_lower_mg_kg=None,
                sulfur_upper_mg_kg=None,
                t95_c=None,
                cetane_number_nominal=None,
                cetane_number_conservative=None,
            ),
            relative_cost_proxy=None,
            admissibility=Admissibility.NOT_ASSESSABLE,
            checks=(),
            limitations=(
                *limitations,
                f"Дозировка выше поддерживаемого диапазона {max_additive_ppm:g} ppm.",
            ),
        )
    if 0 < additive_ppm < min_additive_ppm:
        limitations.append(
            f"Дозировка ниже проверяемого модельного диапазона {min_additive_ppm:g} ppm."
        )

    if any(
        component.sulfur_mg_kg is None or component.t95_c is None or component.cetane_number is None
        for component in components
    ):
        return BlendRecipe(
            shares=(),
            additive_ppm=additive_ppm,
            quality=ModelledProductQuality(
                sulfur_mg_kg=None,
                sulfur_lower_mg_kg=None,
                sulfur_upper_mg_kg=None,
                t95_c=None,
                cetane_number_nominal=None,
                cetane_number_conservative=None,
            ),
            relative_cost_proxy=None,
            admissibility=Admissibility.NOT_ASSESSABLE,
            checks=(),
            limitations=(
                *limitations,
                "Для одного из резервуаров не задан обязательный показатель.",
            ),
        )

    candidates: list[
        tuple[float, tuple[float, ...], ModelledProductQuality, tuple[CheckResult, ...]]
    ] = []
    for integer_shares in _compositions(len(components), 20):
        shares = tuple(value / 20 for value in integer_shares)
        pairs = tuple(zip(shares, components, strict=True))
        sulfur = sum(share * float(component.sulfur_mg_kg) for share, component in pairs)
        t95 = sum(share * float(component.t95_c) for share, component in pairs)
        base_cetane = sum(share * float(component.cetane_number) for share, component in pairs)
        nominal = base_cetane + additive_ppm / 1000 * nominal_cetane_per_1000
        conservative = base_cetane + additive_ppm / 1000 * conservative_cetane_per_1000
        quality = ModelledProductQuality(
            sulfur_mg_kg=sulfur,
            sulfur_lower_mg_kg=None,
            sulfur_upper_mg_kg=None,
            t95_c=t95,
            cetane_number_nominal=nominal,
            cetane_number_conservative=conservative,
        )
        checks = (
            _check("product_sulfur", sulfur, specification.sulfur_max_mg_kg, False, "mg/kg"),
            _check("product_t95", t95, specification.t95_max_c, False, "°C"),
            _check("product_cetane", conservative, specification.cetane_min, True, "index"),
        )
        if all(check.passed is True for check in checks):
            component_cost = sum(share * component.relative_cost for share, component in pairs)
            additive_cost = additive_relative_cost * additive_ppm / 1_000_000
            candidates.append((component_cost + additive_cost, shares, quality, checks))

    if not candidates:
        return BlendRecipe(
            shares=tuple(
                BlendShare(component_id=component.component_id, fraction=1.0 / len(components))
                for component in components
            ),
            additive_ppm=additive_ppm,
            quality=ModelledProductQuality(
                sulfur_mg_kg=None,
                sulfur_lower_mg_kg=None,
                sulfur_upper_mg_kg=None,
                t95_c=None,
                cetane_number_nominal=None,
                cetane_number_conservative=None,
            ),
            relative_cost_proxy=None,
            admissibility=Admissibility.REJECTED,
            checks=(),
            limitations=(*limitations, "В сетке 5% не найден допустимый рецепт."),
        )

    cost, shares, quality, checks = min(candidates, key=lambda item: item[0])
    return BlendRecipe(
        shares=tuple(
            BlendShare(component_id=component.component_id, fraction=share)
            for component, share in zip(components, shares, strict=True)
        ),
        additive_ppm=additive_ppm,
        quality=quality,
        relative_cost_proxy=cost,
        admissibility=Admissibility.ADMISSIBLE,
        checks=checks,
        limitations=tuple(limitations),
    )
