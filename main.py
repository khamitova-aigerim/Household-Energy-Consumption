"""Запуск всех шагов проекта по порядку.

Использование:
    python main.py            # меню
    python main.py all        # все шаги подряд
    python main.py load|db|analyze|plots|forecast
"""
import sys

import analysis
import data_loader
import database
import forecast
import plots

STEPS = {
    "load": ("Загрузка и очистка данных (чанки, память, Parquet)", data_loader.run),
    "db": ("SQLite: схема, 10 запросов, ER-диаграмма", database.run),
    "analyze": ("EDA и временные ряды", analysis.run),
    "plots": ("5 графиков", plots.run),
    "forecast": ("Прогноз и сравнение методов", forecast.run),
}


def run_step(key):
    title, func = STEPS[key]
    print(f"\n=== {title} ===")
    func()


def menu():
    """Консольное меню: выбор шага по номеру."""
    keys = list(STEPS)
    while True:
        print("\nВыбери шаг:")
        for i, key in enumerate(keys, 1):
            print(f"  {i} - {STEPS[key][0]}")
        print("  9 - Все шаги подряд")
        print("  0 - Выход")
        choice = input("Номер: ").strip()
        try:
            if choice == "0":
                break
            elif choice == "9":
                for key in keys:
                    run_step(key)
            elif 1 <= int(choice) <= len(keys):
                run_step(keys[int(choice) - 1])
            else:
                print("Такого номера нет.")
        except ValueError:
            print("Введи число из меню.")
        except FileNotFoundError as error:
            print("Не хватает файла:", error)


def main():
    if len(sys.argv) == 1:
        menu()
    elif sys.argv[1] == "all":
        for key in STEPS:
            run_step(key)
    elif sys.argv[1] in STEPS:
        run_step(sys.argv[1])
    else:
        print("Неизвестная команда. Доступно: all,", ", ".join(STEPS))


if __name__ == "__main__":
    main()
