"""Общие настройки проекта: пути и имена столбцов."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
FIGURES_DIR = BASE_DIR / "figures"

RAW_FILE = DATA_DIR / "household_power_consumption.txt"
CLEAN_PARQUET = DATA_DIR / "minute_clean.parquet"
CLEAN_CSV_GZ = DATA_DIR / "minute_clean.csv.gz"  # запасной формат, если нет pyarrow
DB_FILE = DATA_DIR / "energy.db"

CHUNK_SIZE = 200_000

# Названия столбцов в исходном файле -> наши названия
RENAME = {
    "Global_active_power": "global_active_power",      # кВт, средняя мощность за минуту
    "Global_reactive_power": "global_reactive_power",  # кВт (реактивная)
    "Voltage": "voltage",                              # В
    "Global_intensity": "global_intensity",            # А
    "Sub_metering_1": "sub_metering_1",                # Вт·ч за минуту, кухня
    "Sub_metering_2": "sub_metering_2",                # Вт·ч за минуту, прачечная
    "Sub_metering_3": "sub_metering_3",                # Вт·ч за минуту, водонагреватель и кондиционер
}
VALUE_COLUMNS = list(RENAME.values())

# Тестовый период для прогноза: последние N дней
TEST_DAYS = 365

for _d in (DATA_DIR, RESULTS_DIR, FIGURES_DIR):
    _d.mkdir(exist_ok=True)
