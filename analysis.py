"""EDA и временные ряды.

Что считаем:
- описательная статистика и пропуски;
- выбросы методом IQR;
- ресемплинг (час -> день -> неделя -> месяц) и скользящие средние;
- простая сезонная декомпозиция (тренд + сезонность + остаток);
- корреляции.
Данные берём из SQLite через Pandas.
"""
import json

import numpy as np
import pandas as pd

import config
import database


def load_hourly(conn=None):
    """Почасовые данные из SQLite. Индекс времени = hour_ts."""
    own = conn is None
    conn = conn or database.connect()
    df = pd.read_sql_query(
        """SELECT h.hour_ts, h.hour, h.active_kwh, h.reactive_kvarh, h.voltage_avg,
                  h.intensity_avg, h.valid_minutes, d.date, d.year, d.month, d.weekday,
                  d.weekday_name, d.is_weekend, d.season
           FROM fact_hourly h JOIN dim_date d ON d.date_id = h.date_id
           ORDER BY h.hour_ts""", conn, parse_dates=["hour_ts"])
    meters = pd.read_sql_query(
        """SELECT fm.hour_ts, m.meter_name, fm.energy_wh
           FROM fact_hourly_meter fm JOIN dim_meter m ON m.meter_id = fm.meter_id""",
        conn, parse_dates=["hour_ts"])
    if own:
        conn.close()
    wide = meters.pivot(index="hour_ts", columns="meter_name", values="energy_wh")
    df = df.set_index("hour_ts").join(wide)
    return df


def make_daily(hourly):
    """Сутки из часов. Среднюю мощность за часы с данными умножаем на 24.

    День с менее чем 12 часами данных считаем пропуском (NaN).
    """
    g = hourly.groupby(hourly.index.floor("D"))
    daily = pd.DataFrame({
        "kwh": g["active_kwh"].mean() * 24,
        "hours": g["active_kwh"].count(),
        "voltage_avg": g["voltage_avg"].mean(),
        "intensity_avg": g["intensity_avg"].mean(),
        "reactive_kvarh": g["reactive_kvarh"].mean() * 24,
    })
    for col in ("Кухня", "Прачечная", "Водонагреватель и кондиционер", "Остальное"):
        daily[col] = g[col].mean() * 24 / 1000  # кВт·ч в сутки
    daily.loc[daily["hours"] < 12, daily.columns.drop("hours")] = np.nan
    full_index = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_index).rename_axis("date")
    daily["ma7"] = daily["kwh"].rolling(7, min_periods=4).mean()
    daily["ma30"] = daily["kwh"].rolling(30, min_periods=20).mean()
    return daily


def iqr_outliers(series):
    """Считает выбросы по правилу 1.5 * IQR."""
    s = series.dropna()
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return {"q1": round(q1, 3), "q3": round(q3, 3), "low": round(low, 3), "high": round(high, 3),
            "outliers_count": int(((s < low) | (s > high)).sum()), "total": int(len(s))}


def simple_decompose(series, period_kind):
    """Простая аддитивная декомпозиция: наблюдение = тренд + сезонность + остаток.

    period_kind = 'month': ряд по месяцам, сезонность = средний эффект календарного месяца.
    period_kind = 'weekday': ряд по дням, сезонность = средний эффект дня недели.
    Тренд = центрированное скользящее среднее (12 месяцев или 7 дней).
    """
    s = series.copy()
    window = 12 if period_kind == "month" else 7
    trend = s.rolling(window, center=True, min_periods=window).mean()
    detrended = s - trend
    key = s.index.month if period_kind == "month" else s.index.weekday
    seasonal_by_key = detrended.groupby(key).mean()
    seasonal_by_key = seasonal_by_key - seasonal_by_key.mean()  # центрируем вокруг нуля
    seasonal = pd.Series(key.map(seasonal_by_key).to_numpy(), index=s.index)
    resid = s - trend - seasonal
    return pd.DataFrame({"observed": s, "trend": trend, "seasonal": seasonal, "resid": resid})


def run():
    conn = database.connect()
    hourly = load_hourly(conn)
    conn.close()
    daily = make_daily(hourly)

    # 1. Описательная статистика
    desc = daily[["kwh", "voltage_avg", "intensity_avg", "reactive_kvarh"]].describe().round(3)
    desc.to_csv(config.RESULTS_DIR / "eda_describe_daily.csv")
    hourly_desc = hourly[["active_kwh", "voltage_avg", "intensity_avg"]].describe().round(3)
    hourly_desc.to_csv(config.RESULTS_DIR / "eda_describe_hourly.csv")

    # 2. Пропуски и выбросы
    missing_days = int(daily["kwh"].isna().sum())
    outliers = {"daily_kwh": iqr_outliers(daily["kwh"]), "hourly_kw": iqr_outliers(hourly["active_kwh"]),
                "voltage": iqr_outliers(hourly["voltage_avg"])}

    # 3. Ресемплинг и скользящие средние
    weekly = daily["kwh"].resample("W").mean()
    # Месяц = средняя мощность по имеющимся часам * число часов в месяце (пропуски не занижают сумму)
    month_mean = hourly["active_kwh"].resample("ME").mean()
    month_hours_known = hourly["active_kwh"].resample("ME").count()
    monthly = month_mean * (month_mean.index.days_in_month * 24)
    monthly = monthly.where(month_hours_known >= 600)  # только почти полные месяцы
    weekly.to_csv(config.RESULTS_DIR / "weekly_kwh.csv", header=["kwh_per_day"])
    monthly.to_csv(config.RESULTS_DIR / "monthly_kwh.csv", header=["kwh"])
    daily.to_csv(config.RESULTS_DIR / "daily.csv")

    # 4. Декомпозиция
    dec_month = simple_decompose(monthly.dropna().asfreq("ME").interpolate(), "month")
    dec_week = simple_decompose(daily["kwh"].interpolate(limit=7), "weekday")
    dec_month.to_csv(config.RESULTS_DIR / "decomposition_monthly.csv")
    dec_week.to_csv(config.RESULTS_DIR / "decomposition_weekday.csv")
    month_effect = dec_month.groupby(dec_month.index.month)["seasonal"].mean().round(1)
    weekday_effect = dec_week.groupby(dec_week.index.weekday)["seasonal"].mean().round(2)

    # 5. Корреляции (по суткам)
    corr_cols = ["kwh", "voltage_avg", "intensity_avg", "reactive_kvarh",
                 "Кухня", "Прачечная", "Водонагреватель и кондиционер", "Остальное"]
    corr = daily[corr_cols].corr().round(3)
    corr.to_csv(config.RESULTS_DIR / "correlation_daily.csv")

    report = {
        "days_total": int(len(daily)),
        "days_missing": missing_days,
        "outliers_iqr": outliers,
        "daily_kwh_mean": round(float(daily["kwh"].mean()), 2),
        "daily_kwh_median": round(float(daily["kwh"].median()), 2),
        "month_seasonal_effect_kwh": {int(k): float(v) for k, v in month_effect.items()},
        "weekday_seasonal_effect_kwh": {int(k): float(v) for k, v in weekday_effect.items()},
        "strongest_corr_with_kwh": corr["kwh"].drop("kwh").sort_values(ascending=False).round(3).to_dict(),
    }
    (config.RESULTS_DIR / "analysis_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(desc)
    return hourly, daily


if __name__ == "__main__":
    run()
