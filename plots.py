"""5 визуализаций: 4 статичные (Matplotlib/Seaborn) и 1 интерактивная (Plotly)."""
import matplotlib

matplotlib.use("Agg")  # рисуем в файл, окно не нужно
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

import analysis
import config

sns.set_theme(style="whitegrid", font="DejaVu Sans")
METER_COLUMNS = ["Кухня", "Прачечная", "Водонагреватель и кондиционер", "Остальное"]


def fig_daily_trend(daily):
    """График 1: потребление по дням и скользящее среднее за 30 дней."""
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(daily.index, daily["kwh"], color="#9db4c0", lw=0.8, label="По дням")
    ax.plot(daily.index, daily["ma30"], color="#c1121f", lw=2, label="Скользящее среднее, 30 дней")
    ax.set_title("Потребление электричества в доме по дням")
    ax.set_xlabel("Дата")
    ax.set_ylabel("кВт·ч в сутки")
    ax.legend()
    fig.tight_layout()
    path = config.FIGURES_DIR / "01_daily_trend.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def fig_hourly_profile(hourly):
    """График 2: средняя нагрузка по часам суток, будни и выходные, по сезонам."""
    data = hourly.copy()
    data["day_type"] = data["is_weekend"].map({0: "Будни", 1: "Выходные"})
    grid = sns.relplot(data=data, x="hour", y="active_kwh", hue="day_type", col="season",
                       col_order=["зима", "весна", "лето", "осень"], kind="line",
                       errorbar=None, height=3.2, aspect=0.9, palette=["#2f6690", "#c1121f"])
    grid.set_axis_labels("Час суток", "Средняя мощность, кВт")
    grid.set_titles("{col_name}")
    grid.legend.set_title("Тип дня")
    grid.figure.suptitle("Суточный профиль нагрузки: вечерний пик", y=1.03)
    path = config.FIGURES_DIR / "02_hourly_profile.png"
    grid.savefig(path, dpi=150)
    plt.close(grid.figure)
    return path


def fig_decomposition():
    """График 3: сезонная декомпозиция месячного ряда."""
    dec = pd.read_csv(config.RESULTS_DIR / "decomposition_monthly.csv", index_col=0, parse_dates=True)
    names = {"observed": "Наблюдение", "trend": "Тренд (скользящее среднее 12 мес.)",
             "seasonal": "Сезонность (эффект месяца)", "resid": "Остаток"}
    fig, axes = plt.subplots(4, 1, figsize=(10, 8), sharex=True)
    for ax, col in zip(axes, names):
        ax.plot(dec.index, dec[col], color="#2f6690", lw=1.6)
        ax.set_ylabel("кВт·ч")
        ax.set_title(names[col], loc="left", fontsize=10)
    fig.suptitle("Декомпозиция месячного потребления", y=1.0)
    fig.tight_layout()
    path = config.FIGURES_DIR / "03_decomposition.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def fig_correlation(daily):
    """График 4: тепловая карта корреляций (по суткам)."""
    cols = ["kwh", "voltage_avg", "intensity_avg", "reactive_kvarh"] + METER_COLUMNS
    nice = {"kwh": "Общее, кВт·ч", "voltage_avg": "Напряжение", "intensity_avg": "Сила тока",
            "reactive_kvarh": "Реактивная", "Водонагреватель и кондиционер": "Водонагрев. + кондиц."}
    corr = daily[cols].corr().rename(index=nice, columns=nice)
    fig, ax = plt.subplots(figsize=(8, 6.5))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", vmin=-1, vmax=1, ax=ax,
                cbar_kws={"label": "Корреляция Пирсона"})
    ax.set_title("Корреляции показателей (по суткам)")
    fig.tight_layout()
    path = config.FIGURES_DIR / "04_correlation.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def fig_interactive(daily):
    """График 5 (интерактивный, Plotly): расход по счётчикам, ползунок диапазона дат."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        print("plotly не установлен: интерактивный график пропущен. pip install plotly")
        return None
    fig = go.Figure()
    for col in METER_COLUMNS:
        fig.add_trace(go.Scatter(x=daily.index, y=daily[col].rolling(7, min_periods=4).mean(),
                                 mode="lines", stackgroup="one", name=col))
    fig.update_layout(title="Расход по счётчикам, среднее за 7 дней (кВт·ч в сутки)",
                      xaxis_title="Дата", yaxis_title="кВт·ч в сутки",
                      xaxis=dict(rangeslider=dict(visible=True)), hovermode="x unified")
    path = config.FIGURES_DIR / "05_interactive_meters.html"
    fig.write_html(path, include_plotlyjs="cdn")
    return path


def run(hourly=None, daily=None):
    if hourly is None or daily is None:
        hourly, daily = analysis.run()
    paths = [fig_daily_trend(daily), fig_hourly_profile(hourly), fig_decomposition(),
             fig_correlation(daily), fig_interactive(daily)]
    for p in paths:
        print("Сохранено:", p)
    return paths


if __name__ == "__main__":
    import database  # noqa: F401  (проверка, что база есть)
    hourly_df = analysis.load_hourly()
    run(hourly_df, analysis.make_daily(hourly_df))
