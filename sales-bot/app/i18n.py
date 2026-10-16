"""Языки бота: русский (ru), украинский (uk), английский (en).

Здесь все тексты, которые видит клиент, и переводы данных компаний (названия, адрес, график, услуги).
Чтобы поменять формулировку, правьте строку нужного языка. Чтобы добавить язык, добавьте его код в LANGS
и переводы в каждый ключ TEXTS, в NICHE_TR, MONTHS, WEEKDAYS, COMMANDS (тест tests/test_demo.py проверит полноту).
"""
import re
from types import SimpleNamespace

from . import config
from .niches import NICHES

LANGS = {"ru": "Русский", "uk": "Українська", "en": "English"}


def default_lang() -> str:
    return config.DEFAULT_LANG if config.DEFAULT_LANG in LANGS else "uk"


_UK_LETTERS = set("іїєґІЇЄҐ")
_RU_LETTERS = set("ыэъёЫЭЪЁ")
_UK_WORDS = {"що", "як", "дякую", "дякуємо", "будь", "ласка", "добрий", "день", "вітаю", "привіт", "хочу",
             "потрібно", "можна", "скільки", "коли", "мені", "мене", "мій", "моя", "мої", "так", "ні",
             "записати", "запишіть", "скасуйте", "кабінет", "послуги", "ціна", "години", "завтра", "сьогодні"}
_RU_WORDS = {"что", "как", "спасибо", "пожалуйста", "здравствуйте", "привет", "хочу", "нужно", "можно",
             "сколько", "когда", "мне", "меня", "мой", "моя", "мои", "да", "нет", "записать", "запишите",
             "отмените", "кабинет", "услуги", "цена", "время", "завтра", "сегодня", "добрый", "день"}
_EN_WORDS = {"i", "the", "a", "an", "to", "want", "book", "hello", "hi", "hey", "please", "my", "is", "are",
             "can", "could", "you", "what", "how", "price", "prices", "thanks", "thank", "yes", "no",
             "appointment", "booking", "cancel", "tomorrow", "today", "when", "do", "need", "would", "like",
             "cabinet", "account", "services", "me", "for", "at", "on", "and"}


def detect(text: str | None) -> str | None:
    """Язык сообщения клиента (ru/uk/en) или None, если по тексту не понять (цифры, имя, команда, один смайлик).
    Тогда остаётся язык, который клиент использовал раньше."""
    s = (text or "").strip()
    if not s or s.startswith("/"):
        return None
    cyr = sum(1 for ch in s if "а" <= ch.lower() <= "я" or ch in "іїєґёІЇЄҐЁ")
    lat = sum(1 for ch in s if "a" <= ch.lower() <= "z")
    words = re.findall(r"[^\W\d_]+", s.lower())
    if cyr > lat:
        uk = 3 * sum(ch in _UK_LETTERS for ch in s) + 2 * sum(w in _UK_WORDS for w in words)
        ru = 3 * sum(ch in _RU_LETTERS for ch in s) + 2 * sum(w in _RU_WORDS for w in words)
        if uk > ru:
            return "uk"
        if ru > uk:
            return "ru"
        # ни букв-маркеров, ни слов: кириллица без признаков украинского считается русской
        return "ru" if uk == 0 and cyr >= 4 and not (set(words) & _UK_WORDS) else None
    if lat > cyr and lat >= 2:
        lw = [w for w in words if re.fullmatch(r"[a-z']+", w)]
        if set(lw) & _EN_WORDS or len(lw) >= 3:
            return "en"
    return None


def resolve(row: dict | None, tg_code: str | None = None) -> str:
    """Язык клиента: тот, на котором он писал последний раз (хранится в базе), иначе язык по умолчанию (украинский).
    Язык интерфейса Telegram больше не используется. Параметр tg_code оставлен для совместимости."""
    row = row or {}
    if row.get("lang") in LANGS:
        return row["lang"]
    return default_lang()


def t(lang: str, key: str, **kw) -> str:
    variants = TEXTS[key]
    text = variants.get(lang) or variants["ru"]
    return text.format(**kw) if kw else text


# ---------------------------------------------------------------- тексты

TEXTS = {
    # --- приветствие
    "welcome": {
        "ru": (
            "👋 Здравствуйте! Я AI-администратор — <b>{company}</b>.\n{about}\n\n"
            "<b>Какие услуги есть</b>\n{services}\n\n"
            "🕒 {hours}\n📍 {address}\n\n"
            "<b>Что я могу для вас сделать</b>\n"
            "• назвать цены и ответить на вопросы\n"
            "• показать свободное время и записать вас\n"
            "• посмотреть фото: {photo}\n"
            "• показать ваши записи, перенести или отменить их\n"
            "• напомнить о визите за сутки и за 2 часа\n"
            "• принять ваш отзыв\n"
            "• если не смогу помочь, спрошу у владельца\n\n"
            "<b>Как пользоваться</b>\nКнопок нет: просто напишите сообщение или пришлите фото, "
            "как живому администратору. Например:\n{examples}\n\n"
            "Команды: /cabinet — личный кабинет · /profile — мои данные · /review — оставить отзыв\n\n🌐 Можно писать по-украински, по-русски или по-английски — отвечу на вашем языке."
        ),
        "uk": (
            "👋 Вітаю! Я AI-адміністратор — <b>{company}</b>.\n{about}\n\n"
            "<b>Які послуги є</b>\n{services}\n\n"
            "🕒 {hours}\n📍 {address}\n\n"
            "<b>Що я можу для вас зробити</b>\n"
            "• назвати ціни та відповісти на запитання\n"
            "• показати вільний час і записати вас\n"
            "• подивитися фото: {photo}\n"
            "• показати ваші записи, перенести або скасувати їх\n"
            "• нагадати про візит за добу та за 2 години\n"
            "• прийняти ваш відгук\n"
            "• якщо не зможу допомогти, запитаю у власника\n\n"
            "<b>Як користуватися</b>\nКнопок немає: просто напишіть повідомлення або надішліть фото, "
            "як живому адміністратору. Наприклад:\n{examples}\n\n"
            "Команди: /cabinet — особистий кабінет · /profile — мої дані · /review — залишити відгук\n\n🌐 Можна писати українською, російською або англійською — відповім вашою мовою."
        ),
        "en": (
            "👋 Hello! I'm the AI assistant of <b>{company}</b>.\n{about}\n\n"
            "<b>Our services</b>\n{services}\n\n"
            "🕒 {hours}\n📍 {address}\n\n"
            "<b>What I can do for you</b>\n"
            "• tell you prices and answer questions\n"
            "• show free time slots and book you in\n"
            "• look at a photo: {photo}\n"
            "• show your bookings, reschedule or cancel them\n"
            "• remind you about your visit a day and 2 hours before\n"
            "• take your review\n"
            "• if I can't help, I'll ask the owner\n\n"
            "<b>How to use</b>\nThere are no buttons: just write a message or send a photo, "
            "as you would to a real receptionist. For example:\n{examples}\n\n"
            "Commands: /cabinet — your account · /profile — your details · /review — leave a review\n\n🌐 You can write in Ukrainian, Russian or English — I'll reply in your language."
        ),
    },
    "welcome_demo": {
        "ru": ("🎬 <b>Демо-режим</b>\nДругие компании: /salon /auto /shop /dental\n"
               "Посмотреть глазами владельца: /owner (заявка) и /report (Excel)\n"
               "Как приходит напоминание: /reminder\nКак это устроено: /how\n"
               "Хотите такого бота для своего бизнеса? Просто напишите об этом."),
        "uk": ("🎬 <b>Демо-режим</b>\nІнші компанії: /salon /auto /shop /dental\n"
               "Подивитися очима власника: /owner (заявка) і /report (Excel)\n"
               "Як приходить нагадування: /reminder\nЯк це влаштовано: /how\n"
               "Хочете такого бота для свого бізнесу? Просто напишіть про це."),
        "en": ("🎬 <b>Demo mode</b>\nOther companies: /salon /auto /shop /dental\n"
               "See it as the owner does: /owner (booking) and /report (Excel)\n"
               "What a reminder looks like: /reminder\nHow it works: /how\n"
               "Want a bot like this for your business? Just write about it."),
    },
    "how": {
        "ru": (
            "🧭 <b>Как это работает</b>\n\n"
            "<pre>Клиент пишет текст или шлёт фото\n        ↓\n"
            "Бот (Claude) понимает, что нужно\n        ↓\n"
            "Отвечает, смотрит фото, записывает\n        ↓\n"
            "Заявка летит владельцу в Telegram\n        ↓\n"
            "Владелец: ✅ / ❌ / ✉️ ответить\n        ↓\n"
            "Клиент видит запись в кабинете,\nполучает напоминание, оставляет отзыв</pre>\n"
            "Если бот не уверен или клиент просит человека, вопрос уходит владельцу, а клиенту приходит "
            "«сейчас уточню у владельца».\n\nПод ваш бизнес: загружаем ваш прайс, график и частые вопросы, "
            "и бот готов за 1–2 дня."
        ),
        "uk": (
            "🧭 <b>Як це працює</b>\n\n"
            "<pre>Клієнт пише текст або надсилає фото\n        ↓\n"
            "Бот (Claude) розуміє, що потрібно\n        ↓\n"
            "Відповідає, дивиться фото, записує\n        ↓\n"
            "Заявка летить власнику в Telegram\n        ↓\n"
            "Власник: ✅ / ❌ / ✉️ відповісти\n        ↓\n"
            "Клієнт бачить запис у кабінеті,\nотримує нагадування, залишає відгук</pre>\n"
            "Якщо бот не впевнений або клієнт просить людину, питання йде власнику, а клієнту приходить "
            "«зараз уточню у власника».\n\nПід ваш бізнес: завантажуємо ваш прайс, графік і поширені запитання, "
            "і бот готовий за 1–2 дні."
        ),
        "en": (
            "🧭 <b>How it works</b>\n\n"
            "<pre>Client writes text or sends a photo\n        ↓\n"
            "The bot (Claude) understands the need\n        ↓\n"
            "Replies, looks at photos, books\n        ↓\n"
            "The booking goes to the owner in Telegram\n        ↓\n"
            "Owner: ✅ / ❌ / ✉️ reply\n        ↓\n"
            "Client sees the booking in the account,\ngets a reminder, leaves a review</pre>\n"
            "If the bot is unsure or the client asks for a person, the question goes to the owner and the "
            "client sees \"let me check with the owner\".\n\nFor your business: we load your price list, "
            "hours and FAQ, and the bot is ready in 1–2 days."
        ),
    },
    # --- общие ответы
    "handover_ok": {
        "ru": "Сейчас уточню у владельца и отвечу вам здесь 🙏",
        "uk": "Зараз уточню у власника і відповім вам тут 🙏",
        "en": "Let me check with the owner and I'll get back to you here 🙏",
    },
    "handover_fail": {
        "ru": "Сейчас не могу ответить на это. Попробуйте, пожалуйста, чуть позже.",
        "uk": "Зараз не можу на це відповісти. Спробуйте, будь ласка, трохи пізніше.",
        "en": "I can't answer that right now. Please try again a little later.",
    },
    "cancel_state": {
        "ru": "Хорошо, отменил. Напишите, что вам нужно.",
        "uk": "Добре, скасував. Напишіть, що вам потрібно.",
        "en": "OK, cancelled. Tell me what you need.",
    },
    "just_write": {
        "ru": "Просто напишите, что вам нужно 🙂",
        "uk": "Просто напишіть, що вам потрібно 🙂",
        "en": "Just write what you need 🙂",
    },
    "unknown_cmd": {
        "ru": "Не знаю такой команды 🙂 Просто напишите, что вам нужно, или откройте /cabinet.",
        "uk": "Не знаю такої команди 🙂 Просто напишіть, що вам потрібно, або відкрийте /cabinet.",
        "en": "I don't know that command 🙂 Just write what you need, or open /cabinet.",
    },
    "other_content": {
        "ru": "Пока я понимаю текст и фото. Напишите словами, что вам нужно, или пришлите фото 🙂",
        "uk": "Поки що я розумію текст і фото. Напишіть словами, що вам потрібно, або надішліть фото 🙂",
        "en": "For now I understand text and photos. Write what you need in words, or send a photo 🙂",
    },
    # --- профиль
    "name_usage": {
        "ru": "Напишите имя после команды, например: <code>/name Анна</code>",
        "uk": "Напишіть ім'я після команди, наприклад: <code>/name Анна</code>",
        "en": "Write your name after the command, e.g.: <code>/name Anna</code>",
    },
    "name_saved": {
        "ru": "✅ Имя сохранено: {v}", "uk": "✅ Ім'я збережено: {v}", "en": "✅ Name saved: {v}",
    },
    "phone_usage": {
        "ru": "Напишите номер после команды, например: <code>/phone 0501234567</code>",
        "uk": "Напишіть номер після команди, наприклад: <code>/phone 0501234567</code>",
        "en": "Write your number after the command, e.g.: <code>/phone 0501234567</code>",
    },
    "phone_saved": {
        "ru": "✅ Телефон сохранён: {v}", "uk": "✅ Телефон збережено: {v}", "en": "✅ Phone saved: {v}",
    },
    "profile": {
        "ru": ("👤 <b>Ваши данные</b>\nИмя: {name}\nТелефон: {phone}\n\n"
               "Эти данные подставляются в запись автоматически, поэтому я не спрашиваю их каждый раз.\n\n"
               "<b>Как изменить</b>\n"
               "• словами: «изменить имя на Анна», «мой новый номер 050 123 45 67»\n"
               "• или командой: <code>/name Анна</code> и <code>/phone 0501234567</code>"),
        "uk": ("👤 <b>Ваші дані</b>\nІм'я: {name}\nТелефон: {phone}\n\n"
               "Ці дані підставляються в запис автоматично, тому я не питаю їх щоразу.\n\n"
               "<b>Як змінити</b>\n"
               "• словами: «змінити ім'я на Анна», «мій новий номер 050 123 45 67»\n"
               "• або командою: <code>/name Анна</code> і <code>/phone 0501234567</code>"),
        "en": ("👤 <b>Your details</b>\nName: {name}\nPhone: {phone}\n\n"
               "These details are filled into bookings automatically, so I don't ask for them every time.\n\n"
               "<b>How to change</b>\n"
               "• in words: \"change my name to Anna\", \"my new number is 050 123 45 67\"\n"
               "• or with commands: <code>/name Anna</code> and <code>/phone 0501234567</code>"),
    },
    "not_set_name": {"ru": "не указано", "uk": "не вказано", "en": "not set"},
    "not_set_phone": {"ru": "не указан", "uk": "не вказано", "en": "not set"},
    # --- отзывы
    "review_prompt": {
        "ru": ("⭐ Как вам у нас? Напишите оценку от 1 до 5 и пару слов о визите.\n"
               "Например: «5 всё понравилось» или «3 долго ждал».\nОтмена: /cancel"),
        "uk": ("⭐ Як вам у нас? Напишіть оцінку від 1 до 5 і кілька слів про візит.\n"
               "Наприклад: «5 все сподобалось» або «3 довго чекав».\nСкасувати: /cancel"),
        "en": ("⭐ How was your visit? Write a rating from 1 to 5 and a few words about it.\n"
               "For example: \"5 loved it\" or \"3 waited too long\".\nCancel: /cancel"),
    },
    "review_need_rating": {
        "ru": "Поставьте оценку числом от 1 до 5 (например: «5 отлично»). Отмена: /cancel",
        "uk": "Поставте оцінку числом від 1 до 5 (наприклад: «5 чудово»). Скасувати: /cancel",
        "en": "Please give a rating as a number from 1 to 5 (e.g. \"5 great\"). Cancel: /cancel",
    },
    "review_thanks_hi": {
        "ru": "Спасибо за отзыв! 💛", "uk": "Дякуємо за відгук! 💛", "en": "Thank you for your review! 💛",
    },
    "review_thanks_lo": {
        "ru": "Спасибо, что сказали. Мы передали отзыв владельцу и постараемся стать лучше.",
        "uk": "Дякуємо, що сказали. Ми передали відгук власнику і постараємося стати кращими.",
        "en": "Thank you for telling us. We've passed your review to the owner and will try to do better.",
    },
    # --- ответы владельца и уведомления клиенту
    "admin_prefix": {
        "ru": "👤 <b>Администратор · {company}</b>\n{text}",
        "uk": "👤 <b>Адміністратор · {company}</b>\n{text}",
        "en": "👤 <b>Administrator · {company}</b>\n{text}",
    },
    "confirm_ok": {
        "ru": "✅ {company}: ваша запись подтверждена — {service}, {date} в {time}. Ждём вас!",
        "uk": "✅ {company}: ваш запис підтверджено — {service}, {date} о {time}. Чекаємо на вас!",
        "en": "✅ {company}: your booking is confirmed — {service}, {date} at {time}. See you!",
    },
    "confirm_no": {
        "ru": "❌ {company}: к сожалению, это время недоступно. Мы свяжемся, чтобы подобрать другое.",
        "uk": "❌ {company}: на жаль, цей час недоступний. Ми зв'яжемося, щоб підібрати інший.",
        "en": "❌ {company}: unfortunately that time is unavailable. We'll contact you to find another.",
    },
    # --- напоминания
    "remind_24h": {
        "ru": ("⏰ <b>Напоминаем о вашей записи</b>\n🏢 {company}\n🧾 {service}\n📅 {date} ({wd}) в {time}\n"
               "📍 {address}\n\nЕсли планы изменились, напишите: «отмените запись №{id}» "
               "или «перенесите на другое время»."),
        "uk": ("⏰ <b>Нагадуємо про ваш запис</b>\n🏢 {company}\n🧾 {service}\n📅 {date} ({wd}) о {time}\n"
               "📍 {address}\n\nЯкщо плани змінилися, напишіть: «скасуйте запис №{id}» "
               "або «перенесіть на інший час»."),
        "en": ("⏰ <b>Reminder about your booking</b>\n🏢 {company}\n🧾 {service}\n📅 {date} ({wd}) at {time}\n"
               "📍 {address}\n\nIf your plans have changed, write: \"cancel booking #{id}\" "
               "or \"move it to another time\"."),
    },
    "remind_2h": {
        "ru": ("⏰ <b>Через пару часов ваша запись</b>\n🏢 {company}\n🧾 {service}\n📅 {date} ({wd}) в {time}\n"
               "📍 {address}\n\nЖдём вас! Если не получается прийти, напишите нам."),
        "uk": ("⏰ <b>Через пару годин ваш запис</b>\n🏢 {company}\n🧾 {service}\n📅 {date} ({wd}) о {time}\n"
               "📍 {address}\n\nЧекаємо на вас! Якщо не виходить прийти, напишіть нам."),
        "en": ("⏰ <b>Your booking is in a couple of hours</b>\n🏢 {company}\n🧾 {service}\n📅 {date} ({wd}) at {time}\n"
               "📍 {address}\n\nSee you soon! If you can't make it, let us know."),
    },
    "remind_demo_note": {
        "ru": "👆 Так клиент получает напоминание за сутки до записи. За 2 часа приходит такое же короткое сообщение.",
        "uk": "👆 Так клієнт отримує нагадування за добу до запису. За 2 години приходить таке саме коротке повідомлення.",
        "en": "👆 This is how a client gets a reminder a day before the booking. A similar short message arrives 2 hours before.",
    },
    "remind_demo_need": {
        "ru": "Сначала запишитесь (напишите, например, «запишите меня на завтра»), и здесь покажу напоминание.",
        "uk": "Спершу запишіться (напишіть, наприклад, «запишіть мене на завтра»), і тут я покажу нагадування.",
        "en": "Book something first (e.g. write \"book me for tomorrow\") and I'll show the reminder here.",
    },
    # --- демо: взгляд владельца
    "owner_view_need": {
        "ru": ("Сначала запишитесь (напишите, например, «запишите меня на завтра»), "
               "и здесь появится заявка так, как её видит владелец."),
        "uk": ("Спершу запишіться (напишіть, наприклад, «запишіть мене на завтра»), "
               "і тут з'явиться заявка так, як її бачить власник."),
        "en": ("Book something first (e.g. write \"book me for tomorrow\"), "
               "and the booking will appear here as the owner sees it."),
    },
    "owner_view_title": {
        "ru": "👔 <b>Так заявка выглядит у владельца в его Telegram:</b>\n\n",
        "uk": "👔 <b>Так заявка виглядає у власника в його Telegram:</b>\n\n",
        "en": "👔 <b>This is how the booking looks to the owner in their Telegram:</b>\n\n",
    },
    "report_need": {
        "ru": "Пока нет записей. Запишитесь, и отчёт появится.",
        "uk": "Поки немає записів. Запишіться, і звіт з'явиться.",
        "en": "No bookings yet. Book something and the report will appear.",
    },
    "report_caption": {
        "ru": "📊 Так выглядит отчёт по заявкам для владельца.",
        "uk": "📊 Так виглядає звіт із заявок для власника.",
        "en": "📊 This is what the bookings report looks like for the owner.",
    },
    # --- карточка заявки и кнопки владельца
    "card_new": {"ru": "🔔 Новая заявка", "uk": "🔔 Нова заявка", "en": "🔔 New booking"},
    "card_demo": {"ru": "🔔 Демо-заявка", "uk": "🔔 Демо-заявка", "en": "🔔 Demo booking"},
    "card_when": {"ru": "📅 {date} в {time}", "uk": "📅 {date} о {time}", "en": "📅 {date} at {time}"},
    "card_source": {"ru": "Источник: {v}", "uk": "Джерело: {v}", "en": "Source: {v}"},
    "card_ok": {"ru": "✅ <b>Подтверждена</b>", "uk": "✅ <b>Підтверджено</b>", "en": "✅ <b>Confirmed</b>"},
    "card_no": {"ru": "❌ <b>Отклонена</b>", "uk": "❌ <b>Відхилено</b>", "en": "❌ <b>Declined</b>"},
    "card_cancel": {"ru": "🚫 <b>Отменена клиентом</b>", "uk": "🚫 <b>Скасовано клієнтом</b>",
                    "en": "🚫 <b>Cancelled by the client</b>"},
    "card_sent": {"ru": "📨 <b>Клиенту отправлено:</b>", "uk": "📨 <b>Клієнту надіслано:</b>",
                  "en": "📨 <b>Sent to the client:</b>"},
    "btn_ok": {"ru": "✅ Подтвердить", "uk": "✅ Підтвердити", "en": "✅ Confirm"},
    "btn_no": {"ru": "❌ Отклонить", "uk": "❌ Відхилити", "en": "❌ Decline"},
    "btn_reply": {"ru": "✉️ Ответить клиенту", "uk": "✉️ Відповісти клієнту", "en": "✉️ Reply to client"},
    "btn_contacts": {"ru": "💬 Контакты", "uk": "💬 Контакти", "en": "💬 Contacts"},
    "alert_not_found": {"ru": "Заявка не найдена.", "uk": "Заявку не знайдено.", "en": "Booking not found."},
    "alert_foreign": {"ru": "Это чужая заявка.", "uk": "Це чужа заявка.", "en": "This is someone else's booking."},
    "alert_cancelled": {"ru": "Клиент уже отменил эту запись.", "uk": "Клієнт уже скасував цей запис.",
                        "en": "The client has already cancelled this booking."},
    "alert_done": {"ru": "Готово", "uk": "Готово", "en": "Done"},
    "alert_contact": {"ru": "Клиент: {who}, {phone}", "uk": "Клієнт: {who}, {phone}",
                      "en": "Client: {who}, {phone}"},
    # --- личный кабинет
    "cab_title": {"ru": "🗂 <b>Личный кабинет</b> · {company}", "uk": "🗂 <b>Особистий кабінет</b> · {company}",
                  "en": "🗂 <b>Your account</b> · {company}"},
    "cab_profile": {"ru": "👤 {name}   📞 {phone}", "uk": "👤 {name}   📞 {phone}", "en": "👤 {name}   📞 {phone}"},
    "cab_no_name": {"ru": "имя не указано", "uk": "ім'я не вказано", "en": "name not set"},
    "cab_no_phone": {"ru": "телефон не указан", "uk": "телефон не вказано", "en": "phone not set"},
    "cab_profile_note": {
        "ru": "<i>Данные сохранены, при записи я их больше не спрашиваю.</i>",
        "uk": "<i>Дані збережено, під час запису я їх більше не питаю.</i>",
        "en": "<i>Your details are saved, I won't ask for them again when booking.</i>",
    },
    "cab_profile_empty": {
        "ru": "👤 Профиль пока пустой: имя и телефон сохранятся при первой записи.",
        "uk": "👤 Профіль поки порожній: ім'я та телефон збережуться під час першого запису.",
        "en": "👤 Your profile is empty for now: name and phone will be saved at your first booking.",
    },
    "cab_cal_h": {"ru": "📅 <b>Календарь записей</b>", "uk": "📅 <b>Календар записів</b>",
                  "en": "📅 <b>Booking calendar</b>"},
    "cab_cal_legend": {
        "ru": "<i>[15] день с записью, (13) сегодня</i>",
        "uk": "<i>[15] день із записом, (13) сьогодні</i>",
        "en": "<i>[15] day with a booking, (13) today</i>",
    },
    "cab_up_h": {"ru": "🔜 <b>Ближайшие записи</b>", "uk": "🔜 <b>Найближчі записи</b>",
                 "en": "🔜 <b>Upcoming bookings</b>"},
    "cab_more": {"ru": "…и ещё {n}", "uk": "…і ще {n}", "en": "…and {n} more"},
    "cab_up_none": {
        "ru": "🔜 Ближайших записей нет. Напишите, например: «запишите меня на завтра».",
        "uk": "🔜 Найближчих записів немає. Напишіть, наприклад: «запишіть мене на завтра».",
        "en": "🔜 No upcoming bookings. Write, for example: \"book me for tomorrow\".",
    },
    "cab_hist_h": {"ru": "📊 <b>История</b>", "uk": "📊 <b>Історія</b>", "en": "📊 <b>History</b>"},
    "cab_hist": {
        "ru": "Визитов: {visits} · потрачено: {spent} ₴ · отзывов: {reviews}",
        "uk": "Візитів: {visits} · витрачено: {spent} ₴ · відгуків: {reviews}",
        "en": "Visits: {visits} · spent: {spent} ₴ · reviews: {reviews}",
    },
    "cab_loyal_have": {
        "ru": "🎁 Скидка {pct}% на ближайший визит у вас уже есть, напомните администратору.",
        "uk": "🎁 Знижка {pct}% на найближчий візит у вас уже є, нагадайте адміністратору.",
        "en": "🎁 You already have a {pct}% discount for your next visit, remind the administrator.",
    },
    "cab_loyal_left": {
        "ru": "🎁 До скидки {pct}%: ещё {left} визит(а)",
        "uk": "🎁 До знижки {pct}%: ще {left} візит(и)",
        "en": "🎁 {left} more visit(s) until a {pct}% discount",
    },
    "cab_rate": {
        "ru": "⭐ Оцените визит №{id}: напишите /review",
        "uk": "⭐ Оцініть візит №{id}: напишіть /review",
        "en": "⭐ Rate visit #{id}: write /review",
    },
    "cab_todo": {
        "ru": ("<b>Что можно сделать</b>\n"
               "• Отменить или перенести: напишите «отмени запись №…» или «перенесите на…»\n"
               "• Изменить данные: /profile\n• Оставить отзыв: /review\n"
               "• Напоминания придут за сутки и за 2 часа до визита"),
        "uk": ("<b>Що можна зробити</b>\n"
               "• Скасувати або перенести: напишіть «скасуй запис №…» або «перенесіть на…»\n"
               "• Змінити дані: /profile\n• Залишити відгук: /review\n"
               "• Нагадування прийдуть за добу та за 2 години до візиту"),
        "en": ("<b>What you can do</b>\n"
               "• Cancel or reschedule: write \"cancel booking #…\" or \"move it to…\"\n"
               "• Change your details: /profile\n• Leave a review: /review\n"
               "• Reminders arrive a day and 2 hours before your visit"),
    },
    "st_new": {"ru": "⏳ ждёт подтверждения", "uk": "⏳ чекає підтвердження", "en": "⏳ awaiting confirmation"},
    "st_ok": {"ru": "✅ подтверждена", "uk": "✅ підтверджено", "en": "✅ confirmed"},
    "st_no": {"ru": "❌ отклонена", "uk": "❌ відхилено", "en": "❌ declined"},
    "st_cancel": {"ru": "🚫 отменена", "uk": "🚫 скасовано", "en": "🚫 cancelled"},
}

MONTHS = {
    "ru": ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь",
           "Октябрь", "Ноябрь", "Декабрь"],
    "uk": ["", "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень", "Серпень", "Вересень",
           "Жовтень", "Листопад", "Грудень"],
    "en": ["", "January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"],
}
WEEKDAYS = {                      # короткие, в списке записей
    "ru": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"],
    "uk": ["пн", "вт", "ср", "чт", "пт", "сб", "нд"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
WEEKDAYS2 = {                     # двухбуквенные, шапка календаря
    "ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
    "uk": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"],
    "en": ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"],
}

COMMANDS = {
    "ru": [("start", "Начать: что я умею"), ("cabinet", "Личный кабинет: мои записи"),
           ("profile", "Мои данные"), ("review", "Оставить отзыв")],
    "uk": [("start", "Почати: що я вмію"), ("cabinet", "Особистий кабінет: мої записи"),
           ("profile", "Мої дані"), ("review", "Залишити відгук")],
    "en": [("start", "Start: what I can do"), ("cabinet", "Your account: my bookings"),
           ("profile", "Your details"), ("review", "Leave a review")],
}
COMMANDS_DEMO = {
    "ru": [("owner", "Демо: заявка глазами владельца"), ("report", "Демо: Excel-отчёт"),
           ("reminder", "Демо: напоминание клиенту"), ("how", "Как это работает"), ("call", "Звонок с ADrenaline")],
    "uk": [("owner", "Демо: заявка очима власника"), ("report", "Демо: Excel-звіт"),
           ("reminder", "Демо: нагадування клієнту"), ("how", "Як це працює"), ("call", "Дзвінок з ADrenaline")],
    "en": [("owner", "Demo: booking as the owner sees it"), ("report", "Demo: Excel report"),
           ("reminder", "Demo: reminder to the client"), ("how", "How it works"), ("call", "Call with ADrenaline")],
}

# ---------------------------------------------------------------- данные компаний

NICHE_TR = {
    "salon": {
        "uk": dict(
            title="Салон краси", company="Салон «Лаванда»",
            about="Стрижки, фарбування, манікюр. Демо-версія: компанія вигадана.",
            address="Київ, вул. Прикладна, 12 (м. Центральна, 3 хвилини пішки)", hours="Щодня 10:00–20:00",
            services=["Жіноча стрижка", "Чоловіча стрижка", "Фарбування в один тон", "Мелірування",
                      "Манікюр із покриттям", "Укладання"],
            samples=["Скільки коштує фарбування?", "Є час у суботу ввечері?", "Хочу як на фото"],
            photo_example="зачіска або нігті, які хочете повторити (підкажу послугу та ціну)"),
        "en": dict(
            title="Beauty salon", company="Lavender Salon",
            about="Haircuts, hair colouring, manicure. Demo version: the company is fictional.",
            address="Kyiv, Primernaya St. 12 (Tsentralna metro, 3 min on foot)", hours="Daily 10:00–20:00",
            services=["Women's haircut", "Men's haircut", "Single-colour hair dye", "Highlights",
                      "Gel manicure", "Styling"],
            samples=["How much is hair colouring?", "Any slots on Saturday evening?", "I want this look"],
            photo_example="a hairstyle or nails you'd like to copy (I'll suggest a service and price)"),
    },
    "auto": {
        "uk": dict(
            title="Автосервіс", company="Автосервіс «Мотор-Сервіс»",
            about="Діагностика, ТО, ремонт ходової, шиномонтаж. Демо-версія: компанія вигадана.",
            address="Київ, вул. Заводська, 5, бокс 3", hours="Пн–Сб 09:00–19:00, неділя вихідний",
            services=["Комп'ютерна діагностика", "Заміна масла та фільтра (робота)",
                      "Заміна гальмівних колодок (вісь)", "Шиномонтаж (4 колеса)", "Діагностика ходової",
                      "Розвал-сходження"],
            samples=["Горить check engine, що робити?", "Скільки коштує заміна колодок?", "Запишіть на четвер"],
            photo_example="пошкодження, панель приладів або деталь (підкажу, що перевірити, і запишу на діагностику)"),
        "en": dict(
            title="Auto service", company="Motor-Service Auto Shop",
            about="Diagnostics, maintenance, suspension repair, tyre fitting. Demo version: the company is fictional.",
            address="Kyiv, Zavodska St. 5, bay 3", hours="Mon–Sat 09:00–19:00, closed on Sundays",
            services=["Computer diagnostics", "Oil and filter change (labour)",
                      "Brake pad replacement (per axle)", "Tyre fitting (4 wheels)", "Suspension check",
                      "Wheel alignment"],
            samples=["My check engine light is on, what should I do?", "How much is a brake pad replacement?",
                     "Book me in for Thursday"],
            photo_example="damage, a dashboard warning or a part (I'll suggest what to check and book a diagnostic)"),
    },
    "shop": {
        "uk": dict(
            title="Магазин одягу", company="Магазин «Міський стиль»",
            about="Одяг і взуття. Бронь на примірку та самовивіз. Демо-версія: компанія вигадана.",
            address="Київ, ТЦ «Приклад», 2 поверх, павільйон 47", hours="Щодня 10:00–21:00",
            services=["Куртка демісезонна чорна", "Джинси прямі сині", "Худі оверсайз сіре", "Кросівки білі",
                      "Сукня літня міді", "Сорочка лляна"],
            samples=["Що є з курток?", "Потрібні білі кросівки", "Забронюйте худі на завтра"],
            photo_example="річ, яка сподобалась (знайду найсхожіше в каталозі)"),
        "en": dict(
            title="Clothing store", company="City Style Store",
            about="Clothing and footwear. Try-on reservations and pickup. Demo version: the company is fictional.",
            address="Kyiv, Primer Mall, 2nd floor, unit 47", hours="Daily 10:00–21:00",
            services=["Black mid-season jacket", "Straight blue jeans", "Grey oversized hoodie", "White sneakers",
                      "Summer midi dress", "Linen shirt"],
            samples=["What jackets do you have?", "I need white sneakers", "Reserve the hoodie for tomorrow"],
            photo_example="an item you like (I'll find the closest match in the catalogue)"),
    },
    "dental": {
        "uk": dict(
            title="Стоматологія", company="Клініка «Біла усмішка»",
            about="Огляд, лікування, гігієна, відбілювання. Демо-версія: клініка вигадана.",
            address="Київ, просп. Зразковий, 20, 3 поверх", hours="Пн–Пт 09:00–19:00, субота 10:00–15:00",
            services=["Консультація та огляд", "Професійна гігієна", "Лікування карієсу", "Відбілювання",
                      "Видалення зуба (просте)"],
            samples=["Скільки коштує гігієна?", "Болить зуб, можна сьогодні?", "Працюєте в суботу?"],
            photo_example="усмішка або знімок (підкажу, на який прийом записатися, без діагнозів)"),
        "en": dict(
            title="Dental clinic", company="White Smile Clinic",
            about="Check-ups, treatment, hygiene, whitening. Demo version: the clinic is fictional.",
            address="Kyiv, Obraztsovy Ave. 20, 3rd floor", hours="Mon–Fri 09:00–19:00, Sat 10:00–15:00",
            services=["Consultation and check-up", "Professional hygiene", "Cavity treatment", "Whitening",
                      "Tooth extraction (simple)"],
            samples=["How much is a hygiene visit?", "My tooth hurts, can I come today?", "Are you open on Saturday?"],
            photo_example="a smile or an X-ray (I'll suggest which appointment to book, no diagnoses)"),
    },
}


def niche_view(niche_key: str, lang: str) -> SimpleNamespace:
    """Данные компании на нужном языке (для русского берутся основные данные из niches.py)."""
    n = NICHES[niche_key]
    tr = NICHE_TR.get(niche_key, {}).get(lang)
    if lang == "ru" or not tr:
        return SimpleNamespace(title=n.title, company=n.company, about=n.about, address=n.address, hours=n.hours,
                               services=[s[0] for s in n.services], samples=list(n.samples),
                               photo_example=n.photo_example)
    return SimpleNamespace(**tr)


def service_label(niche_key: str, ru_name: str, lang: str) -> str:
    """Название услуги на языке клиента (в базе и CRM всегда хранится русское название из прайса)."""
    for i, s in enumerate(NICHES[niche_key].services):
        if s[0] == ru_name:
            return niche_view(niche_key, lang).services[i]
    return ru_name


def find_service_any(niche_key: str, name: str):
    """Ищет услугу по названию на любом из трёх языков. Возвращает (индекс, запись прайса) или None."""
    name = re.sub(r"\s+", " ", (name or "").strip().lower())
    if not name:
        return None
    services = NICHES[niche_key].services
    names = {lang: [x.lower() for x in niche_view(niche_key, lang).services] for lang in LANGS}
    for lang in LANGS:                                   # точное совпадение
        for i, n in enumerate(names[lang]):
            if n == name:
                return i, services[i]
    for lang in LANGS:                                   # вхождение
        for i, n in enumerate(names[lang]):
            if name in n or n in name:
                return i, services[i]
    return None


def lang_name_ru(lang: str) -> str:
    return {"ru": "русский", "uk": "украинский", "en": "английский"}[lang]
