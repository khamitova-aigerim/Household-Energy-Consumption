"""Прогноз потребления на следующий день.

Задача: по данным до вчерашнего дня предсказать потребление сегодня (кВт·ч в сутки).
Разбиение по времени, без перемешивания: обучение = всё, кроме последних 365 дней;
тест = последние 365 дней. Признаки используют только прошлые дни, утечки данных нет.

Методы:
  1. naive (baseline)  — завтра будет как сегодня
  2. seasonal_naive_7  — завтра будет как в этот же день недели неделю назад
  3. moving_avg_7      — среднее за последние 7 дней
  4. linear_regression — линейная регрессия по признакам из прошлого
Метрики: MAE и RMSE (кВт·ч в сутки), время и пиковая память.
"""
import time
import tracemalloc

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

import analysis
import config


def prepare_series(daily):
    """Ряд кВт·ч по дням. Пропущенные дни заполняем линейной интерполяцией."""
    s = daily["kwh"].copy()
    s = s.loc[s.first_valid_index():]       # убираем пустое начало
    s = s.loc[:s.last_valid_index()]
    was_missing = s.isna()
    s = s.interpolate(method="linear")
    return s, was_missing


def make_features(s):
    """Признаки из прошлого. shift(1) значит: берём вчерашние данные, не сегодняшние."""
    X = pd.DataFrame(index=s.index)
    X["lag1"] = s.shift(1)
    X["lag2"] = s.shift(2)
    X["lag7"] = s.shift(7)
    X["ma7"] = s.shift(1).rolling(7).mean()
    weekday = pd.get_dummies(s.index.weekday, prefix="wd").astype(float)
    weekday.index = s.index
    X = X.join(weekday.drop(columns="wd_0"))  # день недели, один столбец убираем
    X["month_sin"] = np.sin(2 * np.pi * s.index.month / 12)
    X["month_cos"] = np.cos(2 * np.pi * s.index.month / 12)
    return X


def timed(func):
    """Запускает функцию и меряет время и пиковую память (МБ)."""
    tracemalloc.start()
    t0 = time.perf_counter()
    result = func()
    seconds = time.perf_counter() - t0
    peak = tracemalloc.get_traced_memory()[1] / 1024 ** 2
    tracemalloc.stop()
    return result, seconds, peak


def evaluate(s, was_missing):
    test_start = s.index[-config.TEST_DAYS]
    X = make_features(s)
    train_mask = (s.index < test_start) & X.notna().all(axis=1).to_numpy()
    test_mask = s.index >= test_start
    real_test = test_mask & ~was_missing.to_numpy()   # считаем метрики только по реальным дням
    y_test = s[test_mask]

    preds, rows = {}, []

    methods = {
        "naive (baseline)": lambda: s.shift(1)[test_mask],
        "seasonal_naive_7": lambda: s.shift(7)[test_mask],
        "moving_avg_7": lambda: X.loc[test_mask, "ma7"],
        "linear_regression": None,
    }

    def run_lr():
        model = LinearRegression().fit(X[train_mask], s[train_mask])
        return pd.Series(model.predict(X[test_mask]), index=y_test.index), model

    for name, func in methods.items():
        if name == "linear_regression":
            (pred, model), seconds, peak = timed(run_lr)
        else:
            pred, seconds, peak = timed(func)
        preds[name] = pred
        err = (pred - y_test)[~was_missing[test_mask].to_numpy()]
        rows.append({"method": name,
                     "MAE_kwh": round(err.abs().mean(), 3),
                     "RMSE_kwh": round(float(np.sqrt((err ** 2).mean())), 3),
                     "seconds": round(seconds, 5),
                     "peak_memory_mb": round(peak, 3)})
    table = pd.DataFrame(rows)
    base = table.loc[table["method"] == "naive (baseline)", "MAE_kwh"].iloc[0]
    table["MAE_vs_baseline_percent"] = ((table["MAE_kwh"] / base - 1) * 100).round(1)
    coefs = pd.Series(model.coef_, index=X.columns).round(3)
    return table, pd.DataFrame(preds).assign(actual=y_test), coefs, test_start, int(real_test.sum())


def plot_forecast(predictions, best_name):
    """Рисуем последние 90 дней теста: факт, baseline и лучший метод."""
    tail = predictions.tail(90)
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.plot(tail.index, tail["actual"], color="black", lw=1.8, label="Факт")
    ax.plot(tail.index, tail["naive (baseline)"], color="#9db4c0", lw=1.2, label="Baseline: как вчера")
    ax.plot(tail.index, tail[best_name], color="#c1121f", lw=1.6, label=best_name)
    ax.set_title("Прогноз на следующий день: последние 90 дней теста")
    ax.set_xlabel("Дата")
    ax.set_ylabel("кВт·ч в сутки")
    ax.legend()
    fig.tight_layout()
    path = config.FIGURES_DIR / "06_forecast_test.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def run(daily=None):
    if daily is None:
        daily = analysis.make_daily(analysis.load_hourly())
    s, was_missing = prepare_series(daily)
    table, predictions, coefs, test_start, n_real = evaluate(s, was_missing)
    table.to_csv(config.RESULTS_DIR / "forecast_metrics.csv", index=False)
    predictions.to_csv(config.RESULTS_DIR / "forecast_predictions.csv")
    coefs.to_csv(config.RESULTS_DIR / "forecast_lr_coefficients.csv", header=["coef"])
    best = table.sort_values("MAE_kwh").iloc[0]["method"]
    plot_forecast(predictions, best)
    print(f"Тест начинается с {test_start.date()}, дней в тесте: {config.TEST_DAYS}, "
          f"реальных (без интерполяции): {n_real}, интерполировано во всём ряду: {int(was_missing.sum())}")
    print(table.to_string(index=False))
    print("Лучший метод:", best)
    return table


if __name__ == "__main__":
    run()
