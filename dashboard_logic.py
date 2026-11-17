"""Расчёты для дашборда. Здесь только Pandas, без Streamlit: так код проще проверять."""
import pandas as pd

METRICS = {
    "Средняя мощность, кВт": "active_kwh",
    "Напряжение, В": "voltage_avg",
    "Сила тока, А": "intensity_avg",
    "Кухня, Вт·ч в час": "Кухня",
    "Прачечная, Вт·ч в час": "Прачечная",
    "Водонагреватель и кондиционер, Вт·ч в час": "Водонагреватель и кондиционер",
    "Остальное, Вт·ч в час": "Остальное",
}
FREQS = {"Час": "h", "День": "D", "Неделя": "W", "Месяц": "ME"}
METER_COLUMNS = ["Кухня", "Прачечная", "Водонагреватель и кондиционер", "Остальное"]


def filter_hours(hourly, start, end, seasons=None, day_type="Все"):
    """Фильтры дашборда: период, сезоны, будни/выходные."""
    mask = (hourly.index >= pd.Timestamp(start)) & (hourly.index < pd.Timestamp(end) + pd.Timedelta(days=1))
    df = hourly[mask]
    if seasons:
        df = df[df["season"].isin(seasons)]
    if day_type == "Будни":
        df = df[df["is_weekend"] == 0]
    elif day_type == "Выходные":
        df = df[df["is_weekend"] == 1]
    return df


def aggregate(df, column, freq_label):
    """Среднее значение показателя по выбранному шагу: час, день, неделя, месяц."""
    if df.empty:
        return pd.Series(dtype=float, name=column)
    return df[column].resample(FREQS[freq_label]).mean().dropna().rename(column)


def hourly_profile(df, column):
    """Среднее значение по часам суток для будней и выходных."""
    if df.empty:
        return pd.DataFrame(columns=["hour", "Тип дня", column])
    out = df.assign(**{"Тип дня": df["is_weekend"].map({0: "Будни", 1: "Выходные"})})
    return out.groupby(["hour", "Тип дня"], as_index=False)[column].mean()


def meter_share(df):
    """Доля каждого счётчика в потреблении за выбранный период."""
    if df.empty:
        return pd.DataFrame(columns=["Счётчик", "Вт·ч в час", "Доля, %"])
    totals = df[METER_COLUMNS].mean()
    share = (totals / totals.sum() * 100).round(1)
    return pd.DataFrame({"Счётчик": totals.index, "Вт·ч в час": totals.round(1).to_numpy(),
                         "Доля, %": share.to_numpy()})


def summary_cards(df):
    """Четыре числа для карточек сверху."""
    if df.empty:
        return {"Часов в выборке": 0, "Средняя мощность, кВт": None,
                "Пиковый час, кВт": None, "Расход по имеющимся часам, кВт·ч": None}
    hours = len(df)
    mean_kw = float(df["active_kwh"].mean())
    return {"Часов в выборке": hours,
            "Средняя мощность, кВт": round(mean_kw, 3),
            "Пиковый час, кВт": round(float(df["active_kwh"].max()), 2),
            "Расход по имеющимся часам, кВт·ч": round(float(df["active_kwh"].sum()), 0)}
