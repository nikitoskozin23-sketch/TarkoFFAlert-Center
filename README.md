# Custom OBS Alerts на Python

Это стартовый каркас для своей системы кастомных алертов под OBS.

## Что уже работает

- локальный Python-сервер на FastAPI
- overlay для OBS через Browser Source
- очередь алертов
- тестовая панель `/control`
- единый формат событий для Twitch / YouTube / Trovo / VK Play / DonationAlerts
- модульная архитектура под будущие интеграции

## Что пока каркас

- Twitch EventSub
- YouTube live chat polling
- Trovo chat/followers/subscriptions integration
- DonationAlerts realtime websocket/Centrifugo
- VK Play адаптер

## Быстрый старт

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.yaml config.yaml
python main.py
```

Сервер поднимется на:

- `http://127.0.0.1:8765/overlay`
- `http://127.0.0.1:8765/control`

## Как подключить в OBS

1. Открой OBS.
2. Добавь **Browser Source**.
3. Укажи URL: `http://127.0.0.1:8765/overlay`
4. Размер можно поставить `1920x1080`.
5. Галочка `Shutdown source when not visible` — лучше выключить.
6. Галочка `Refresh browser when scene becomes active` — можно включить.

## Как развивать дальше

### Ветка 1 — быстро получить рабочий результат
Сначала подключить **DonationAlerts** как самый быстрый реальный источник событий, а поверх него уже делать свой стиль, анимации, очереди, звуки и разные шаблоны.

### Ветка 2 — полностью независимая система
Подключать отдельно:
- Twitch через EventSub
- YouTube через active live chat
- Trovo через chat websocket + followers/subscriptions polling
- VK Play либо отдельным адаптером, либо через связку с DonationAlerts

## Почему эта архитектура удобна

Ты сможешь:
- менять стиль алертов без переписывания логики платформ;
- делать разные шаблоны под донаты, подписки, фоллоу, мемберки;
- добавлять приоритеты и очереди;
- хранить историю событий;
- потом прикрутить GUI, звуки, gif/webm, TTS и пресеты.

## Следующий лучший шаг

Следующим этапом я бы подключал **DonationAlerts realtime** и сразу выводил реальные события в эту же overlay-страницу. Это самый короткий путь до реально живой системы.
