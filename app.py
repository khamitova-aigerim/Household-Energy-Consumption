"""Мини-дашборд Streamlit. Запуск: streamlit run app.py

Вкладки: Обзор, Суточный профиль, Счётчики, Прогноз, SQL-запросы.
Фильтры слева: период, шаг агрегации, показатель, сезон, тип дня.
"""
import pandas as pd
import streamlit as st

import config
import dashboard_logic as dl
import database
from analysis import load_hourly
from queries import QUERIES

try:
    import plotly.express as px
except ImportError:  # без plotly показываем простые графики Streamlit
    px = None

st.set_page_config(page_title="Потребление электричества в доме", layout="wide")


@st.cache_data
def get_hourly():
    return load_hourly()


@st.cache_data
def get_forecast_tables():
    metrics = pd.read_csv(config.RESULTS_DIR / "forecast_metrics.csv")
    preds = pd.read_csv(config.RESULTS_DIR / "forecast_predictions.csv", index_col=0, parse_dates=True)
    return metrics, preds


@st.cache_data
def run_sql(sql):
    conn = database.connect()
    try:
        return database.run_query(conn, sql)
    finally:
        conn.close()


def show_line(series, title, ylabel):
    """Линейный график: Plotly, если он есть."""
    if series.empty:
        st.info("В выбранном периоде нет данных. Измени фильтры.")
        return
    if px is None:
        st.line_chart(series)
        return
    fig = px.line(series.reset_index(), x=series.index.name or "index", y=series.name, title=title,
                  labels={series.name: ylabel})
    st.plotly_chart(fig, use_container_width=True)


def main():
    st.title("Потребление электричества в доме")
    st.caption("Данные UCI: Individual Household Electric Power Consumption, декабрь 2006 – ноябрь 2010, "
               "Франция. Минутные замеры сведены в почасовые.")
    try:
        hourly = get_hourly()
    except Exception as error:  # нет базы или файла
        st.error(f"Не удалось открыть базу данных: {error}. Сначала запусти: python main.py all")
        st.stop()

    st.sidebar.header("Фильтры")
    first, last = hourly.index.min().date(), hourly.index.max().date()
    period = st.sidebar.date_input("Период", value=(first, last), min_value=first, max_value=last)
    start, end = (period[0], period[1]) if isinstance(period, (list, tuple)) and len(period) == 2 else (first, last)
    freq_label = st.sidebar.selectbox("Шаг агрегации", list(dl.FREQS), index=1)
    metric_label = st.sidebar.selectbox("Показатель", list(dl.METRICS))
    seasons = st.sidebar.multiselect("Сезон", ["зима", "весна", "лето", "осень"],
                                     default=["зима", "весна", "лето", "осень"])
    day_type = st.sidebar.radio("Тип дня", ["Все", "Будни", "Выходные"])

    df = dl.filter_hours(hourly, start, end, seasons, day_type)
    column = dl.METRICS[metric_label]

    tab_overview, tab_profile, tab_meters, tab_forecast, tab_sql = st.tabs(
        ["Обзор", "Суточный профиль", "Счётчики", "Прогноз", "SQL-запросы"])

    with tab_overview:
        cards = dl.summary_cards(df)
        for col, (name, value) in zip(st.columns(len(cards)), cards.items()):
            col.metric(name, "нет данных" if value is None else value)
        show_line(dl.aggregate(df, column, freq_label), f"{metric_label}: шаг «{freq_label}»", metric_label)
        with st.expander("Показать таблицу"):
            st.dataframe(dl.aggregate(df, column, freq_label).reset_index(), use_container_width=True)

    with tab_profile:
        profile = dl.hourly_profile(df, column)
        if profile.empty:
            st.info("Нет данных для выбранных фильтров.")
        elif px is None:
            st.line_chart(profile.pivot(index="hour", columns="Тип дня", values=column))
        else:
            fig = px.line(profile, x="hour", y=column, color="Тип дня",
                          labels={"hour": "Час суток", column: metric_label},
                          title="Среднее по часам суток")
            st.plotly_chart(fig, use_container_width=True)

    with tab_meters:
        share = dl.meter_share(df)
        if share.empty:
            st.info("Нет данных для выбранных фильтров.")
        else:
            if px is None:
                st.bar_chart(share.set_index("Счётчик")["Доля, %"])
            else:
                st.plotly_chart(px.bar(share, x="Счётчик", y="Доля, %", title="Доля счётчиков, %"),
                                use_container_width=True)
            st.dataframe(share, use_container_width=True)

    with tab_forecast:
        st.write("Прогноз на следующий день. Тест: последние 365 дней, разбиение по времени.")
        try:
            metrics, preds = get_forecast_tables()
        except FileNotFoundError:
            st.warning("Нет результатов прогноза. Запусти: python main.py forecast")
        else:
            st.dataframe(metrics, use_container_width=True)
            methods = [c for c in preds.columns if c != "actual"]
            chosen = st.multiselect("Какие методы показать", methods, default=[methods[0], methods[-1]])
            view = preds[["actual"] + chosen].tail(120)
            if px is None:
                st.line_chart(view)
            else:
                st.plotly_chart(px.line(view, title="Факт и прогноз, последние 120 дней"),
                                use_container_width=True)

    with tab_sql:
        name = st.selectbox("Запрос", list(QUERIES), format_func=lambda k: QUERIES[k][0])
        title, technique, sql = QUERIES[name]
        st.caption(f"Приём: {technique}")
        st.code(sql.strip(), language="sql")
        st.dataframe(run_sql(sql), use_container_width=True)


main()
