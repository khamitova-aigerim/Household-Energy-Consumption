"""Загрузка и очистка данных.

Что делает:
1. Читает большой файл по частям (chunksize), чтобы не забивать память.
2. Собирает дату и время в один столбец timestamp.
3. Заменяет '?' на пропуски (NaN) и уменьшает типы данных (float64 -> float32).
4. Измеряет память и время: обычное чтение против чтения по частям.
5. Сохраняет чистые данные в Parquet (или в csv.gz, если нет pyarrow).
"""
import json
import time

import pandas as pd

import config


def read_chunks(path=config.RAW_FILE, chunksize=config.CHUNK_SIZE):
    """Читает файл кусками и сразу очищает каждый кусок. Возвращает один DataFrame."""
    parts = []
    for chunk in pd.read_csv(path, sep=";", na_values="?", chunksize=chunksize,
                             low_memory=False):
        chunk["timestamp"] = pd.to_datetime(
            chunk["Date"] + " " + chunk["Time"], format="%d/%m/%Y %H:%M:%S")
        chunk = chunk.drop(columns=["Date", "Time"]).rename(columns=config.RENAME)
        chunk[config.VALUE_COLUMNS] = chunk[config.VALUE_COLUMNS].astype("float32")
        parts.append(chunk[["timestamp"] + config.VALUE_COLUMNS])
    return pd.concat(parts, ignore_index=True)


def read_naive(path=config.RAW_FILE):
    """Обычное чтение всего файла сразу, без оптимизации. Нужно только для сравнения."""
    return pd.read_csv(path, sep=";", na_values="?", low_memory=False)


def memory_mb(df):
    """Память DataFrame в мегабайтах."""
    return df.memory_usage(deep=True).sum() / 1024 ** 2


def measure_memory_and_time(path=config.RAW_FILE):
    """Сравнивает обычное чтение и чтение по частям с оптимизацией типов."""
    t0 = time.perf_counter()
    raw = read_naive(path)
    t_naive = time.perf_counter() - t0
    mem_naive = memory_mb(raw)
    del raw

    t0 = time.perf_counter()
    clean = read_chunks(path)
    t_chunks = time.perf_counter() - t0
    mem_clean = memory_mb(clean)

    report = {
        "rows": int(len(clean)),
        "naive_read_seconds": round(t_naive, 2),
        "naive_memory_mb": round(mem_naive, 1),
        "chunked_read_seconds": round(t_chunks, 2),
        "optimized_memory_mb": round(mem_clean, 1),
        "memory_saving_percent": round(100 * (1 - mem_clean / mem_naive), 1),
    }
    return clean, report


def quality_report(df):
    """Краткий аудит качества: пропуски, дубликаты, диапазон дат, разрывы."""
    missing = df[config.VALUE_COLUMNS].isna().sum()
    rows_missing = int(df[config.VALUE_COLUMNS].isna().any(axis=1).sum())
    ts = df["timestamp"]
    step = ts.diff().dropna()
    return {
        "rows": int(len(df)),
        "date_from": str(ts.min()),
        "date_to": str(ts.max()),
        "missing_by_column": {k: int(v) for k, v in missing.items()},
        "rows_with_missing": rows_missing,
        "missing_percent": round(100 * rows_missing / len(df), 2),
        "duplicate_timestamps": int(ts.duplicated().sum()),
        "timestamps_sorted": bool(ts.is_monotonic_increasing),
        "gaps_longer_than_1_min": int((step > pd.Timedelta(minutes=1)).sum()),
        "longest_gap_minutes": int(step.max() / pd.Timedelta(minutes=1)),
        "negative_values": int((df[config.VALUE_COLUMNS] < 0).sum().sum()),
    }


def save_clean(df):
    """Сохраняет чистые данные. Parquet быстрее и меньше. Если нет pyarrow, пишем csv.gz."""
    try:
        df.to_parquet(config.CLEAN_PARQUET, index=False)
        return config.CLEAN_PARQUET
    except ImportError:
        print("pyarrow не установлен, сохраняю в csv.gz. Для Parquet: pip install pyarrow")
        df.to_csv(config.CLEAN_CSV_GZ, index=False)
        return config.CLEAN_CSV_GZ


def load_clean():
    """Читает чистые данные из Parquet или из csv.gz."""
    if config.CLEAN_PARQUET.exists():
        return pd.read_parquet(config.CLEAN_PARQUET)
    if config.CLEAN_CSV_GZ.exists():
        return pd.read_csv(config.CLEAN_CSV_GZ, parse_dates=["timestamp"])
    raise FileNotFoundError("Нет чистых данных. Сначала запусти: python main.py load")


def compare_formats(df):
    """Сравнивает CSV и Parquet по размеру файла и времени чтения."""
    csv_path = config.DATA_DIR / "_tmp_compare.csv"
    df.to_csv(csv_path, index=False)
    t0 = time.perf_counter()
    pd.read_csv(csv_path, parse_dates=["timestamp"])
    result = {
        "csv_size_mb": round(csv_path.stat().st_size / 1024 ** 2, 1),
        "csv_read_seconds": round(time.perf_counter() - t0, 2),
    }
    csv_path.unlink()
    try:
        pq_path = config.DATA_DIR / "_tmp_compare.parquet"
        df.to_parquet(pq_path, index=False)
        t0 = time.perf_counter()
        pd.read_parquet(pq_path)
        result["parquet_size_mb"] = round(pq_path.stat().st_size / 1024 ** 2, 1)
        result["parquet_read_seconds"] = round(time.perf_counter() - t0, 2)
        pq_path.unlink()
    except ImportError:
        result["parquet"] = "пропущено: не установлен pyarrow"
    return result


def run():
    """Полный шаг загрузки: чтение, замеры, аудит, сохранение."""
    try:
        clean, mem_report = measure_memory_and_time()
    except FileNotFoundError:
        raise SystemExit(f"Не найден файл {config.RAW_FILE}. Положи его в папку data/.")
    quality = quality_report(clean)
    formats = compare_formats(clean)
    saved = save_clean(clean)
    out = {"memory_and_time": mem_report, "quality": quality, "csv_vs_parquet": formats,
           "saved_to": str(saved.name)}
    (config.RESULTS_DIR / "load_report.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return clean


if __name__ == "__main__":
    run()
