"""10 SQL-запросов к базе energy.db.

Каждый запрос: (название, что показывает, SQL).
Приёмы: JOIN, GROUP BY/HAVING, подзапрос, CTE, оконные функции (AVG OVER, LAG, RANK, SUM OVER), CASE.
"""

QUERIES = {
    "q01_season_weekend": (
        "Средняя нагрузка по сезонам: будни и выходные",
        "JOIN + GROUP BY",
        """
SELECT d.season,
       CASE WHEN d.is_weekend = 1 THEN 'выходной' ELSE 'будни' END AS day_type,
       ROUND(AVG(h.active_kwh), 3) AS avg_kw,
       COUNT(*) AS hours_count
FROM fact_hourly AS h
JOIN dim_date AS d ON d.date_id = h.date_id
GROUP BY d.season, d.is_weekend
ORDER BY d.season, d.is_weekend;
"""),
    "q02_monthly_total": (
        "Сумма кВт·ч по имеющимся часам за месяц (месяцы с 600+ часов данных)",
        "GROUP BY + HAVING",
        """
SELECT d.year, d.month,
       ROUND(SUM(h.active_kwh), 1) AS total_kwh,
       COUNT(*) AS hours_count
FROM fact_hourly AS h
JOIN dim_date AS d ON d.date_id = h.date_id
GROUP BY d.year, d.month
HAVING COUNT(*) >= 600
ORDER BY d.year, d.month;
"""),
    "q03_top_peak_hours": (
        "10 самых нагруженных часов за всё время",
        "JOIN + ORDER BY + LIMIT",
        """
SELECT h.hour_ts, d.weekday_name, ROUND(h.active_kwh, 2) AS kwh
FROM fact_hourly AS h
JOIN dim_date AS d ON d.date_id = h.date_id
ORDER BY h.active_kwh DESC
LIMIT 10;
"""),
    "q04_days_above_average": (
        "Дни с потреблением выше среднего за все полные дни",
        "CTE + подзапрос",
        """
WITH daily AS (
    SELECT date_id, SUM(active_kwh) AS kwh
    FROM fact_hourly
    GROUP BY date_id
    HAVING COUNT(*) = 24
)
SELECT d.date, ROUND(daily.kwh, 1) AS kwh
FROM daily
JOIN dim_date AS d ON d.date_id = daily.date_id
WHERE daily.kwh > (SELECT AVG(kwh) FROM daily)
ORDER BY daily.kwh DESC
LIMIT 15;
"""),
    "q05_moving_average": (
        "Скользящее среднее за 7 полных дней",
        "CTE + оконная функция AVG OVER",
        """
WITH daily AS (
    SELECT date_id, SUM(active_kwh) AS kwh
    FROM fact_hourly
    GROUP BY date_id
    HAVING COUNT(*) = 24
)
SELECT d.date,
       ROUND(daily.kwh, 2) AS kwh,
       ROUND(AVG(daily.kwh) OVER (ORDER BY daily.date_id
             ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS moving_avg_7
FROM daily
JOIN dim_date AS d ON d.date_id = daily.date_id
ORDER BY d.date
LIMIT 20;
"""),
    "q06_day_change": (
        "Изменение потребления к предыдущему полному дню",
        "оконная функция LAG",
        """
WITH daily AS (
    SELECT date_id, SUM(active_kwh) AS kwh
    FROM fact_hourly
    GROUP BY date_id
    HAVING COUNT(*) = 24
),
changes AS (
    SELECT date_id, kwh,
           LAG(kwh) OVER (ORDER BY date_id) AS prev_kwh
    FROM daily
)
SELECT d.date, ROUND(c.kwh, 1) AS kwh, ROUND(c.prev_kwh, 1) AS prev_kwh,
       ROUND(c.kwh - c.prev_kwh, 1) AS change_kwh
FROM changes AS c
JOIN dim_date AS d ON d.date_id = c.date_id
WHERE c.prev_kwh IS NOT NULL
ORDER BY ABS(c.kwh - c.prev_kwh) DESC
LIMIT 10;
"""),
    "q07_top_hours_by_season": (
        "Три самых нагруженных часа суток в каждом сезоне",
        "CTE + оконная функция RANK",
        """
WITH avg_by_hour AS (
    SELECT d.season, h.hour, AVG(h.active_kwh) AS avg_kw
    FROM fact_hourly AS h
    JOIN dim_date AS d ON d.date_id = h.date_id
    GROUP BY d.season, h.hour
),
ranked AS (
    SELECT season, hour, avg_kw,
           RANK() OVER (PARTITION BY season ORDER BY avg_kw DESC) AS rnk
    FROM avg_by_hour
)
SELECT season, hour, ROUND(avg_kw, 3) AS avg_kw, rnk
FROM ranked
WHERE rnk <= 3
ORDER BY season, rnk;
"""),
    "q08_meter_share": (
        "Доля каждого счётчика в потреблении по годам",
        "3 JOIN + оконная функция SUM OVER",
        """
WITH per_year AS (
    SELECT d.year, m.meter_name, SUM(fm.energy_wh) / 1000.0 AS kwh
    FROM fact_hourly_meter AS fm
    JOIN fact_hourly AS h ON h.hour_ts = fm.hour_ts
    JOIN dim_date AS d ON d.date_id = h.date_id
    JOIN dim_meter AS m ON m.meter_id = fm.meter_id
    GROUP BY d.year, m.meter_name
)
SELECT year, meter_name, ROUND(kwh, 0) AS kwh,
       ROUND(100.0 * kwh / SUM(kwh) OVER (PARTITION BY year), 1) AS share_percent
FROM per_year
ORDER BY year, kwh DESC;
"""),
    "q09_longest_gaps": (
        "Самые длинные пропуски в почасовых данных",
        "CTE + оконная функция LAG + julianday",
        """
WITH g AS (
    SELECT hour_ts,
           LAG(hour_ts) OVER (ORDER BY hour_ts) AS prev_ts
    FROM fact_hourly
)
SELECT prev_ts AS gap_starts_after, hour_ts AS gap_ends_at,
       CAST(ROUND((julianday(hour_ts) - julianday(prev_ts)) * 24) AS INTEGER) AS gap_hours
FROM g
WHERE prev_ts IS NOT NULL
  AND (julianday(hour_ts) - julianday(prev_ts)) * 24 > 1.5
ORDER BY gap_hours DESC
LIMIT 10;
"""),
    "q10_evening_peak": (
        "Вечерний пик (18–22 ч) против остального времени по дням недели",
        "JOIN + CASE внутри AVG",
        """
SELECT d.weekday_name,
       ROUND(AVG(CASE WHEN h.hour BETWEEN 18 AND 22 THEN h.active_kwh END), 3) AS evening_avg_kw,
       ROUND(AVG(CASE WHEN h.hour NOT BETWEEN 18 AND 22 THEN h.active_kwh END), 3) AS other_avg_kw
FROM fact_hourly AS h
JOIN dim_date AS d ON d.date_id = h.date_id
GROUP BY d.weekday, d.weekday_name
ORDER BY d.weekday;
"""),
}

# Тот же расчёт, что q02, но без HAVING: нужен для сравнения SQL и Pandas
MONTHLY_SQL = """
SELECT d.year, d.month, SUM(h.active_kwh) AS total_kwh
FROM fact_hourly AS h
JOIN dim_date AS d ON d.date_id = h.date_id
GROUP BY d.year, d.month
ORDER BY d.year, d.month;
"""
