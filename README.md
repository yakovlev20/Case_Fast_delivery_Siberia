# Case_Fast_delivery_Siberia

Веб-приложение для распределения неделимых заказов по машинам с проверкой вместимости.
Учебный проект: система назначает заказы на машины, показывает долю назначенного веса
и позволяет выгрузить нераспределённые заказы в CSV.

## Стек

- Python 3.10+
- FastAPI + Uvicorn
- pytest, httpx (тесты)

## Установка

Необходимо установить зависимости (requirements.txt):

* fastapi
* uvicorn[standard]
* httpx
* pytest

```bash
pip install -r requirements.txt


Запуск через терминал:
Run:   uvicorn main:app --reload
UI:    http://127.0.0.1:8000/        Swagger: http://127.0.0.1:8000/docs


