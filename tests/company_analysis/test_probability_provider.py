from __future__ import annotations

from pathlib import Path

import pandas as pd

from company_quality.company_analysis.probability_provider import (
    calibrate_current_generation,
)


def _series(multiplier: float) -> pd.Series:
    index = pd.to_datetime([f"{year}-07-31" for year in range(2007, 2027)])
    return pd.Series(
        [100.0 * (multiplier**offset) for offset in range(len(index))],
        index=index,
    )


def test_builds_same_generation_formal_calibration(tmp_path: Path) -> None:
    calls: list[tuple[int, int, int, Path]] = []

    def benchmark(start: int, end: int, month: int, output: Path) -> pd.Series:
        calls.append((start, end, month, output))
        return _series(1.05)

    result = calibrate_current_generation(
        issuer_id="22099131",
        security_code="2330",
        market="TWSE",
        as_of="2026-07-29T14:00:00+08:00",
        generated_at="2026-07-29T14:01:00+08:00",
        generation_id="generation-current",
        output_root=tmp_path,
        company_loader=lambda _: _series(1.10),
        benchmark_loader=benchmark,
    )

    assert result is not None
    assert result.status == "formal"
    assert result.generation_id == "generation-current"
    assert result.final_oos_start == "2026-01-01"
    assert result.positive_return.trials == 18
    assert result.ignored_final_oos_company_points == 1
    assert calls == [(2007, 2025, 7, tmp_path / "twse_return_index")]


def test_tpex_returns_unavailable_without_loading_sources(tmp_path: Path) -> None:
    called = False

    def company(_: str) -> pd.Series:
        nonlocal called
        called = True
        return _series(1.10)

    result = calibrate_current_generation(
        issuer_id="03564798",
        security_code="6488",
        market="TPEx",
        as_of="2026-07-29T14:00:00+08:00",
        generated_at="2026-07-29T14:01:00+08:00",
        generation_id="generation-current",
        output_root=tmp_path,
        company_loader=company,
    )

    assert result is None
    assert called is False
