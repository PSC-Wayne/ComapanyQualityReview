"""Live sources for current-generation single-company probability calibration."""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import threading
import time
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from company_quality.company_analysis.probability_calibration import (
    SingleCompanyProbabilityCalibration,
    calibrate_single_company_annual_base_rates,
)


_TWSE_RETURN_INDEX_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MFI94U"
_DEFAULT_TOKEN_PATH = Path("/mnt/d/Claude_Code/Hermes/Self_code_strategy/api.txt")
_FRAME_LOCK = threading.Lock()
_ADJUSTED_FRAME: pd.DataFrame | None = None


class ProbabilitySourceError(RuntimeError):
    """Raised when a required live calibration source is unavailable."""


def load_finlab_company_adjusted_series(security_code: str) -> pd.Series:
    """Load FinLab etl:adj_close once per process and return one company series."""

    global _ADJUSTED_FRAME
    with _FRAME_LOCK:
        if _ADJUSTED_FRAME is None:
            token_path = Path(os.environ.get("FINLAB_API_TOKEN_FILE", _DEFAULT_TOKEN_PATH))
            if not token_path.is_file():
                raise ProbabilitySourceError("FinLab token file unavailable")
            token = token_path.read_text(encoding="utf-8").strip()
            if not token:
                raise ProbabilitySourceError("FinLab token file is empty")
            try:
                import finlab
                from finlab import data

                finlab.login(token)
                frame = data.get("etl:adj_close")
            except Exception as exc:
                raise ProbabilitySourceError(f"FinLab adjusted wealth unavailable: {exc}") from exc
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                raise ProbabilitySourceError("FinLab adjusted wealth returned no rows")
            frame = frame.copy()
            frame.columns = [str(column).split()[0] for column in frame.columns]
            _ADJUSTED_FRAME = frame.T.groupby(level=0).first().T.sort_index()
        frame = _ADJUSTED_FRAME
        assert frame is not None
    if security_code not in frame.columns:
        raise ProbabilitySourceError("company missing from FinLab adjusted wealth")
    series = frame[security_code].dropna()
    if series.empty:
        raise ProbabilitySourceError("company FinLab adjusted wealth has no valid points")
    return series


def fetch_twse_official_return_index(
    start_year: int,
    end_year: int,
    season_month: int,
    output_dir: Path,
) -> pd.Series:
    """Fetch monthly official total-return index rows used by the annual labels."""

    output_dir.mkdir(parents=True, exist_ok=True)
    values: dict[pd.Timestamp, float] = {}
    for year in range(start_year, end_year + 1):
        destination = output_dir / f"{year}-{season_month:02d}.json"
        query = urlencode({"response": "json", "date": f"{year}{season_month:02d}01"})
        url = f"{_TWSE_RETURN_INDEX_URL}?{query}"
        request = Request(url, headers={"User-Agent": "CompanyQualityResearch/0.1"})
        if destination.is_file():
            payload = json.loads(destination.read_text(encoding="utf-8"))
        else:
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    with urlopen(request, timeout=30) as response:
                        payload = json.load(response)
                    destination.write_text(
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        encoding="utf-8",
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(attempt + 1)
            else:
                raise ProbabilitySourceError(
                    f"TWSE return index unavailable for {year}: {last_error}"
                ) from last_error
        if not isinstance(payload, dict) or not isinstance(payload.get("fields"), list):
            raise ProbabilitySourceError("TWSE return index schema drifted")
        fields = ["".join(str(field).split()) for field in payload["fields"]]
        try:
            date_index = fields.index("日期")
            value_index = fields.index("發行量加權股價報酬指數")
        except ValueError as exc:
            raise ProbabilitySourceError("TWSE total-return field missing") from exc
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ProbabilitySourceError("TWSE return index rows missing")
        for row in rows:
            if not isinstance(row, list) or len(row) <= max(date_index, value_index):
                continue
            raw_date = str(row[date_index]).strip()
            parts = raw_date.split("/")
            if len(parts) != 3:
                continue
            try:
                day = pd.Timestamp(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))
                value = float(str(row[value_index]).replace(",", ""))
            except ValueError:
                continue
            values[day] = value
    if not values:
        raise ProbabilitySourceError("TWSE return index has no valid rows")
    return pd.Series(values, dtype="float64", name="official_total_return_index").sort_index()


CompanyLoader = Callable[[str], pd.Series]
BenchmarkLoader = Callable[[int, int, int, Path], pd.Series]


def calibrate_current_generation(
    *,
    issuer_id: str,
    security_code: str,
    market: str,
    as_of: str,
    generated_at: str,
    generation_id: str,
    output_root: Path,
    company_loader: CompanyLoader = load_finlab_company_adjusted_series,
    benchmark_loader: BenchmarkLoader = fetch_twse_official_return_index,
) -> SingleCompanyProbabilityCalibration | None:
    """Build formal historical base rates for TWSE companies; TPEx is unsupported."""

    if market != "TWSE":
        return None
    decision = pd.Timestamp(as_of)
    company = company_loader(security_code)
    if company.empty:
        raise ProbabilitySourceError("company calibration series is empty")
    first_year = int(pd.DatetimeIndex(company.index).year.min())
    cutoff = date(decision.year, 1, 1)
    benchmark = benchmark_loader(
        first_year,
        cutoff.year - 1,
        decision.month,
        output_root / "twse_return_index",
    )
    return calibrate_single_company_annual_base_rates(
        issuer_id=issuer_id,
        security_code=security_code,
        market="TWSE",
        company_total_return_wealth=company,
        official_benchmark_total_return=benchmark,
        season_month=decision.month,
        final_oos_start=cutoff,
        minimum_observations=15,
        generated_at=generated_at,
        generation_id=generation_id,
    )


__all__ = [
    "ProbabilitySourceError",
    "calibrate_current_generation",
    "fetch_twse_official_return_index",
    "load_finlab_company_adjusted_series",
]
