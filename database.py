"""База данных SQLite: схема, загрузка, запросы, ER-диаграмма.

Схема (3НФ):
  dim_date          справочник дат (год, месяц, день недели, сезон)
  dim_meter         справочник счётчиков (кухня, прачечная, водонагреватель, остальное)
  fact_hourly       почасовые данные по всему дому
  fact_hourly_meter почасовое потребление по каждому счётчику

Минутные данные (2 млн строк) в SQL не кладём: они лежат в Parquet.
В SQL хранятся почасовые агрегаты (около 34 тысяч часов).
"""
import json
import sqlite3
import time

import numpy as np
import pandas as pd

import config
import data_loader
from queries import QUERIES, MONTHLY_SQL

SCHEMA = """
DROP TABLE IF EXISTS fact_hourly_meter;
DROP TABLE IF EXISTS fact_hourly;
DROP TABLE IF EXISTS dim_meter;
DROP TABLE IF EXISTS dim_date;

CREATE TABLE dim_date (
    date_id INTEGER PRIMARY KEY,              -- формат YYYYMMDD
    date TEXT NOT NULL UNIQUE,                -- YYYY-MM-DD
    year INTEGER NOT NULL,
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    day INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31),
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),  -- 0 = понедельник
    weekday_name TEXT NOT NULL,
    is_weekend INTEGER NOT NULL CHECK (is_weekend IN (0, 1)),
    season TEXT NOT NULL CHECK (season IN ('зима', 'весна', 'лето', 'осень'))
);

CREATE TABLE dim_meter (
    meter_id INTEGER PRIMARY KEY,
    meter_name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL
);

CREATE TABLE fact_hourly (
    hour_ts TEXT PRIMARY KEY,                 -- YYYY-MM-DD HH:00:00
    date_id INTEGER NOT NULL,
    hour INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
    active_kwh REAL NOT NULL CHECK (active_kwh >= 0),   -- кВт·ч за час
    reactive_kvarh REAL NOT NULL CHECK (reactive_kvarh >= 0),
    voltage_avg REAL NOT NULL,
    intensity_avg REAL NOT NULL,
    valid_minutes INTEGER NOT NULL CHECK (valid_minutes BETWEEN 1 AND 60),
    FOREIGN KEY (date_id) REFERENCES dim_date (date_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE fact_hourly_meter (
    hour_ts TEXT NOT NULL,
    meter_id INTEGER NOT NULL,
    energy_wh REAL NOT NULL,                  -- Вт·ч за час
    PRIMARY KEY (hour_ts, meter_id),
    FOREIGN KEY (hour_ts) REFERENCES fact_hourly (hour_ts)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (meter_id) REFERENCES dim_meter (meter_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);
"""

METERS = [
    (1, "Кухня", "Посудомоечная машина, духовка, микроволновка (sub_metering_1)"),
    (2, "Прачечная", "Стиральная машина, сушилка, холодильник, свет (sub_metering_2)"),
    (3, "Водонагреватель и кондиционер", "Электрический водонагреватель и кондиционер (sub_metering_3)"),
    (4, "Остальное", "Всё, что не измеряют три счётчика: общая энергия минус три счётчика"),
]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
SEASONS = {12: "зима", 1: "зима", 2: "зима", 3: "весна", 4: "весна", 5: "весна",
           6: "лето", 7: "лето", 8: "лето", 9: "осень", 10: "осень", 11: "осень"}


def connect(path=config.DB_FILE):
    """Открывает базу и включает проверку внешних ключей (для каждого соединения)."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def build_hourly(minute_df):
    """Минутные данные -> почасовые.

    active_kwh = средняя мощность за час (кВт) * 1 час. Берём только минуты без пропусков.
    Если в часе нет ни одной минуты с данными, часа в таблице нет (это пропуск).
    """
    df = minute_df.copy()
    df["hour_ts"] = df["timestamp"].dt.floor("h")
    # Общая энергия за минуту в Вт·ч: кВт * 1000 / 60
    df["active_wh"] = df["global_active_power"] * 1000 / 60
    df["other_wh"] = df["active_wh"] - df[["sub_metering_1", "sub_metering_2", "sub_metering_3"]].sum(axis=1)
    g = df.groupby("hour_ts")
    hourly = pd.DataFrame({
        "active_kwh": g["global_active_power"].mean(),
        "reactive_kvarh": g["global_reactive_power"].mean(),
        "voltage_avg": g["voltage"].mean(),
        "intensity_avg": g["global_intensity"].mean(),
        "valid_minutes": g["global_active_power"].count(),
        # сумма Вт·ч по счётчикам, пересчитанная на полный час (60 минут)
        "m1": g["sub_metering_1"].mean() * 60,
        "m2": g["sub_metering_2"].mean() * 60,
        "m3": g["sub_metering_3"].mean() * 60,
        "m4": g["other_wh"].mean() * 60,
    })
    hourly = hourly[hourly["valid_minutes"] > 0].reset_index()
    return hourly


def build_dim_date(dates):
    """Таблица дат для всех дней, которые есть в данных."""
    d = pd.DataFrame({"date": pd.to_datetime(pd.Series(dates).unique())}).sort_values("date")
    d["date_id"] = d["date"].dt.strftime("%Y%m%d").astype(int)
    d["year"] = d["date"].dt.year
    d["month"] = d["date"].dt.month
    d["day"] = d["date"].dt.day
    d["weekday"] = d["date"].dt.weekday
    d["weekday_name"] = d["weekday"].map(lambda i: WEEKDAYS[i])
    d["is_weekend"] = (d["weekday"] >= 5).astype(int)
    d["season"] = d["month"].map(SEASONS)
    d["date"] = d["date"].dt.strftime("%Y-%m-%d")
    return d[["date_id", "date", "year", "month", "day", "weekday", "weekday_name", "is_weekend", "season"]]


def build_database(minute_df):
    """Создаёт базу и заполняет таблицы."""
    hourly = build_hourly(minute_df)
    dim_date = build_dim_date(hourly["hour_ts"].dt.floor("D"))
    hourly["date_id"] = hourly["hour_ts"].dt.strftime("%Y%m%d").astype(int)
    hourly["hour"] = hourly["hour_ts"].dt.hour
    hourly["hour_ts"] = hourly["hour_ts"].dt.strftime("%Y-%m-%d %H:00:00")

    fact_rows = [
        (r.hour_ts, int(r.date_id), int(r.hour), float(r.active_kwh), float(r.reactive_kvarh),
         float(r.voltage_avg), float(r.intensity_avg), int(r.valid_minutes))
        for r in hourly.itertuples(index=False)
    ]
    meter_rows = []
    for r in hourly.itertuples(index=False):
        for meter_id, value in ((1, r.m1), (2, r.m2), (3, r.m3), (4, r.m4)):
            meter_rows.append((r.hour_ts, meter_id, float(value)))
    date_rows = [tuple(x) for x in dim_date.itertuples(index=False, name=None)]

    conn = connect()
    with conn:  # успех = commit, ошибка = rollback
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO dim_date VALUES (?,?,?,?,?,?,?,?,?)", date_rows)
        conn.executemany("INSERT INTO dim_meter VALUES (?,?,?)", METERS)
        conn.executemany("INSERT INTO fact_hourly VALUES (?,?,?,?,?,?,?,?)", fact_rows)
        conn.executemany("INSERT INTO fact_hourly_meter VALUES (?,?,?)", meter_rows)
    return conn


def check_database(conn):
    """Проверки: число строк, внешние ключи, целостность файла."""
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("dim_date", "dim_meter", "fact_hourly", "fact_hourly_meter")}
    # Имена таблиц берём из фиксированного списка, не из ввода пользователя
    fk_problems = conn.execute("PRAGMA foreign_key_check").fetchall()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    return {"row_counts": counts, "foreign_key_problems": len(fk_problems), "integrity_check": integrity}


def run_query(conn, sql, params=()):
    """Выполняет SELECT и возвращает результат в Pandas."""
    return pd.read_sql_query(sql, conn, params=params)


def run_all_queries(conn):
    """Выполняет 10 запросов, сохраняет результаты в results/sql/."""
    out_dir = config.RESULTS_DIR / "sql"
    out_dir.mkdir(exist_ok=True)
    summary = []
    for name, (title, technique, sql) in QUERIES.items():
        t0 = time.perf_counter()
        df = run_query(conn, sql)
        elapsed = time.perf_counter() - t0
        df.to_csv(out_dir / f"{name}.csv", index=False)
        summary.append({"query": name, "title": title, "technique": technique,
                        "rows": len(df), "seconds": round(elapsed, 4)})
    pd.DataFrame(summary).to_csv(config.RESULTS_DIR / "sql_summary.csv", index=False)
    return summary


def compare_sql_pandas(conn, hourly_df=None):
    """Один и тот же расчёт (кВт·ч по месяцам) в SQL и в Pandas: время и совпадение."""
    t0 = time.perf_counter()
    sql_res = run_query(conn, MONTHLY_SQL)
    t_sql = time.perf_counter() - t0

    # Для Pandas берём те же данные, что лежат в базе, и считаем groupby
    t0 = time.perf_counter()
    raw = pd.read_sql_query("SELECT d.year, d.month, h.active_kwh FROM fact_hourly h "
                            "JOIN dim_date d ON d.date_id = h.date_id", conn)
    pd_res = raw.groupby(["year", "month"], as_index=False)["active_kwh"].sum()
    t_pandas = time.perf_counter() - t0
    same = bool(np.allclose(sql_res["total_kwh"].to_numpy(), pd_res["active_kwh"].to_numpy()))
    return {"sql_seconds": round(t_sql, 4), "pandas_seconds_including_read": round(t_pandas, 4),
            "results_match": same, "months": int(len(sql_res))}


def draw_erd():
    """Рисует ER-диаграмму через Graphviz (программа dot). Если её нет, пишет только .dot."""
    dot = '''digraph ERD {
  rankdir=LR; node [shape=plain, fontname="Helvetica"]; edge [fontname="Helvetica", fontsize=10];
  dim_date [label=<<table border="0" cellborder="1" cellspacing="0" cellpadding="4">
    <tr><td bgcolor="#2f6690"><font color="white"><b>dim_date</b></font></td></tr>
    <tr><td align="left"><b>date_id</b> INTEGER (PK)</td></tr>
    <tr><td align="left">date TEXT (UNIQUE)</td></tr>
    <tr><td align="left">year, month, day INTEGER</td></tr>
    <tr><td align="left">weekday INTEGER</td></tr>
    <tr><td align="left">weekday_name TEXT</td></tr>
    <tr><td align="left">is_weekend INTEGER</td></tr>
    <tr><td align="left">season TEXT</td></tr></table>>];
  dim_meter [label=<<table border="0" cellborder="1" cellspacing="0" cellpadding="4">
    <tr><td bgcolor="#2f6690"><font color="white"><b>dim_meter</b></font></td></tr>
    <tr><td align="left"><b>meter_id</b> INTEGER (PK)</td></tr>
    <tr><td align="left">meter_name TEXT (UNIQUE)</td></tr>
    <tr><td align="left">description TEXT</td></tr></table>>];
  fact_hourly [label=<<table border="0" cellborder="1" cellspacing="0" cellpadding="4">
    <tr><td bgcolor="#2f6690"><font color="white"><b>fact_hourly</b></font></td></tr>
    <tr><td align="left"><b>hour_ts</b> TEXT (PK)</td></tr>
    <tr><td align="left">date_id INTEGER (FK)</td></tr>
    <tr><td align="left">hour INTEGER</td></tr>
    <tr><td align="left">active_kwh REAL</td></tr>
    <tr><td align="left">reactive_kvarh REAL</td></tr>
    <tr><td align="left">voltage_avg REAL</td></tr>
    <tr><td align="left">intensity_avg REAL</td></tr>
    <tr><td align="left">valid_minutes INTEGER</td></tr></table>>];
  fact_hourly_meter [label=<<table border="0" cellborder="1" cellspacing="0" cellpadding="4">
    <tr><td bgcolor="#2f6690"><font color="white"><b>fact_hourly_meter</b></font></td></tr>
    <tr><td align="left"><b>hour_ts</b> TEXT (PK, FK)</td></tr>
    <tr><td align="left"><b>meter_id</b> INTEGER (PK, FK)</td></tr>
    <tr><td align="left">energy_wh REAL</td></tr></table>>];
  dim_date -> fact_hourly [label="1 : N", arrowhead=crow];
  fact_hourly -> fact_hourly_meter [label="1 : N", arrowhead=crow];
  dim_meter -> fact_hourly_meter [label="1 : N", arrowhead=crow];
}'''
    dot_path = config.RESULTS_DIR / "erd.dot"
    dot_path.write_text(dot, encoding="utf-8")
    import shutil
    import subprocess
    if shutil.which("dot"):
        subprocess.run(["dot", "-Tpng", "-Gdpi=150", str(dot_path), "-o", str(config.RESULTS_DIR / "erd.png")], check=True)
        return "erd.png"
    return "erd.dot (Graphviz не найден, открой файл на graphviz.org/online или в dbdiagram)"


def run():
    """Полный шаг SQL: строим базу, проверяем, запускаем запросы, сравниваем с Pandas."""
    minute = data_loader.load_clean()
    conn = build_database(minute)
    checks = check_database(conn)
    summary = run_all_queries(conn)
    comparison = compare_sql_pandas(conn)
    erd = draw_erd()
    out = {"checks": checks, "queries": summary, "sql_vs_pandas": comparison, "erd": erd}
    (config.RESULTS_DIR / "database_report.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    conn.close()
    print(json.dumps({"checks": checks, "sql_vs_pandas": comparison, "erd": erd}, indent=2, ensure_ascii=False))
    for s in summary:
        print(f"{s['query']}: {s['rows']} строк, {s['seconds']} с")
    return out


if __name__ == "__main__":
    run()
