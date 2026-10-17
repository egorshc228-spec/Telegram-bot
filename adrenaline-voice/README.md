# adrenaline-voice — голосовой AI для заявок ADrenaline

Голосовой агент ElevenLabs звонит лиду, который оставил заявку на сайте, но не ответил в Telegram/WhatsApp. Он уточняет запрос и записывает на бесплатный 20-минутный звонок с Даниилом. Итог звонка с текстом разговора приходит в группу «ADrenaline · Заявки», ответом на карточку лида.

Сервис тонкий: голос, распознавание и перебивания делает ElevenLabs, а свободные окна и запись — бот продаж (та же логика, что в чате). Здесь только связка между ними.

## Как работает

```
Бот продаж ── POST /call ──────────────▶ adrenaline-voice ── outbound-call ──▶ ElevenLabs ──SIP──▶ Zadarma ──▶ телефон лида
     ▲                                        │   ▲
     │  /api/voice/slots, /api/voice/book     │   │  инструменты агента: /tools/slots, /tools/book
     └────────────────────────────────────────┘   │
     ▲                                            │  после звонка: POST /webhooks/elevenlabs (подписан)
     └──── /api/voice/result (итог в группу) ─────┘
```

1. Лид не открыл Telegram/WhatsApp. Раньше бот ставил в группу карточку «☎️ Позвонить вручную», теперь при `VOICE_CALLS=1` и телефоне в заявке он вызывает `POST /call`.
2. Сервис запускает исходящий звонок агента ElevenLabs через номер Zadarma. Агенту передаются `{{name}}`, `{{service}}`, `{{now}}`, `{{lead_id}}`.
3. В разговоре агент вызывает `get_free_slots` и `book_call`. Сервис передаёт их боту, бот создаёт запись: Google Calendar, напоминания и кнопка «Подтвердить» работают как обычно.
4. После звонка ElevenLabs присылает подписанный вебхук. Сервис отдаёт итог боту, бот пишет его в ветку карточки лида и решает, что дальше:

| Итог (`outcome`) | Что делает бот |
|---|---|
| `booked` | запись уже создана; в ветку — отчёт и текст разговора |
| `callback`, `manager_needed` | карточка «🙋 Нужен Даниил» / «⏰ Перезвонить» с кнопками «Беру сам», «Не целевой» |
| `not_target` | лид «не целевой» |
| `do_not_call` | лид помечается, больше никаких звонков и автосообщений |
| `no_answer`, занято, автоответчик | один повтор через 30 мин, потом обычная карточка «☎️ Позвонить вручную» |

Правила гайда, которые соблюдает код: звонки только 09:00–20:00 (проверяют и бот, и сервис), максимум один повтор, «не звоните» = стоп, ключи только в переменных, итог в группу в течение минуты. Если сервис или ElevenLabs недоступны, бот сразу ставит обычную карточку, и лид не теряется. Если итог не пришёл за 20 минут, бот сам считает это «не дозвонились».

## Переменные (Railway → Variables)

| Переменная | Что это |
|---|---|
| `ELEVENLABS_API_KEY` | ключ API ElevenLabs (аккаунт компании) |
| `ELEVENLABS_AGENT_ID` | id агента «ADrenaline · обзвон заявок» (Agent → в адресе страницы `agent_…`) |
| `ELEVENLABS_PHONE_NUMBER_ID` | id номера Zadarma после импорта в ElevenLabs (Phone numbers) |
| `ELEVENLABS_WEBHOOK_SECRET` | секрет post-call webhook (показывается при создании вебхука) |
| `SALES_BOT_URL` | адрес бота продаж, например `https://….up.railway.app` |
| `VOICE_SECRET` | длинная случайная строка, **то же значение** в боте продаж |
| `TOOL_SECRET` | другая длинная случайная строка: заголовок `X-Tool-Secret` в инструментах агента |
| `LANGUAGE_OVERRIDE` | `1` — лидам с русских страниц агент начинает по-русски (нужно разрешить Language в Security агента). По умолчанию `0` |
| `RINGING_TIMEOUT_SECS` | сколько секунд ждать ответа, по умолчанию 30 |
| `MANAGER_NAME`, `TIMEZONE`, `CONTACT_HOURS` | `Даниил`, `Europe/Kyiv`, `09:00-20:00` |

Случайную строку для секретов можно получить командой `python -c "import secrets; print(secrets.token_urlsafe(32))"`. В репозитории только `.env.example` с пустыми полями.

В боте продаж (Variables): `VOICE_CALLS=1`, `VOICE_SERVICE_URL=<адрес этого сервиса>`, `VOICE_SECRET=<то же значение>`.

## Настройка агента в ElevenLabs

Промпт, первые фразы, голос, LLM, системные инструменты и поля итога описаны в документе «Голосовой агент ADrenaline — настройка ElevenLabs». Здесь — то, что связывает агента с сервисом.

**Инструменты (Agent → Tools → Add tool → Webhook):**

| | `get_free_slots` | `book_call` |
|---|---|---|
| Описание | Свободные окна для звонка с Даниилом на ближайшие дни. Вызывай перед тем, как предлагать время. | Записать на звонок с Даниилом. datetime — время из ответа get_free_slots. |
| Метод, URL | `POST https://<сервис>/tools/slots` | `POST https://<сервис>/tools/book` |
| Заголовок | `X-Tool-Secret` = `TOOL_SECRET` (как секрет) | то же |
| Тело | `lead_id` — **dynamic variable** `lead_id` | `lead_id` — dynamic variable `lead_id`; `datetime` — заполняет LLM: «YYYY-MM-DDTHH:MM по Киеву, только из get_free_slots» |

`lead_id` обязательно ставить как dynamic variable, а не «заполняет LLM». Иначе модель может перепутать заявку.

**Post-call webhook:** URL `https://<сервис>/webhooks/elevenlabs`, авторизация HMAC. Включить события transcription и call initiation failure, аудио не нужно. Секрет → `ELEVENLABS_WEBHOOK_SECRET`.

## Запуск на Railway

Сервис лежит папкой `adrenaline-voice/` в общем репозитории рядом с `sales-bot/` и `demo-bot/`.

1. В проекте Railway: **Add** → GitHub repo `Telegram-bot` → новый сервис. В Settings → Source:
   - Root Directory: `/adrenaline-voice`
   - Dockerfile Path: `/adrenaline-voice/Dockerfile`
   - Watch Paths: `/adrenaline-voice/**` — чтобы изменения в других ботах не пересобирали этот сервис.

   Volume не нужен: сервис ничего не хранит.
2. Settings → Networking → Generate Domain.
3. Variables из таблицы. Проверка: `https://<адрес>/health` → `{"ok": true, "configured": true}`.
4. В боте продаж: `VOICE_SERVICE_URL`, `VOICE_SECRET`, затем `VOICE_CALLS=1`. Выключить голос — `VOICE_CALLS=0`, бот вернётся к карточкам «Позвонить вручную».

## Тесты

```
pip install -r requirements.txt
python -m tests.test_service      # сервис: звонок, инструменты, вебхук, подпись, повторы доставки
python -m tests.test_with_bot     # сквозной: бот продаж + сервис по HTTP, подменён только ElevenLabs
```

`test_with_bot` ищет бот продаж с доработкой в соседней папке `../sales-bot` (или `SALES_BOT_DIR=путь`). В боте есть свой тест голосовой части: `python -m tests.test_voice`.

## Структура

| Файл | За что отвечает |
|---|---|
| `voice/web.py` | HTTP: `/call`, `/tools/*`, `/webhooks/elevenlabs`, `/health` |
| `voice/elevenlabs.py` | исходящий звонок, проверка подписи вебхука (как в официальном SDK), разбор итога |
| `voice/bot.py` | запросы к боту продаж, доставка итога с повторами |
| `voice/config.py` | переменные окружения |
