"""Тексты демо «AI-менеджер продаж» (uk по умолчанию, ru, en).

Подстановки из файла компании (salesdemo_company.json): {company}, {m} {m_gen} {m_dat} {m_ins} — менеджер в падежах,
{min} — минуты звонка, {pitch}, {offer}. Остальные поля передаются при вызове st(...)."""

ST = {
    # ---------- вход ----------
    "niche_btn": {"uk": "🤝 Бот продажів (заявки з сайту)", "ru": "🤝 Бот продаж (заявки с сайта)",
                  "en": "🤝 Sales bot (website leads)"},
    "intro": {
        "uk": ("🤝 <b>AI-менеджер продажів</b> — для бізнесу, де заявка з сайту чи реклами має стати дзвінком, "
               "заміром або консультацією.\n\n"
               "Що він робить:\n"
               "• заявка з сайту за секунду з'являється в групі вашої команди\n"
               "• бот сам пише людині, відповідає на питання за вашими цінами і записує на дзвінок у вільне вікно\n"
               "• мовчить — нагадає; питання нестандартне — покличе менеджера\n"
               "• менеджер бачить усе й перехоплює розмову однією кнопкою\n\n"
               "🎭 Зараз ви — <b>клієнт</b> компанії «{company}» (вигадана, сонячні станції). "
               "Ви на її сайті й залишаєте заявку. <b>Що вас цікавить?</b> 👇"),
        "ru": ("🤝 <b>AI-менеджер продаж</b> — для бизнеса, где заявка с сайта или рекламы должна стать звонком, "
               "замером или консультацией.\n\n"
               "Что он делает:\n"
               "• заявка с сайта за секунду появляется в группе вашей команды\n"
               "• бот сам пишет человеку, отвечает на вопросы по вашим ценам и записывает на звонок в свободное окно\n"
               "• молчит — напомнит; вопрос нестандартный — позовёт менеджера\n"
               "• менеджер видит всё и перехватывает разговор одной кнопкой\n\n"
               "🎭 Сейчас вы — <b>клиент</b> компании «{company}» (вымышленная, солнечные станции). "
               "Вы на её сайте и оставляете заявку. <b>Что вас интересует?</b> 👇"),
        "en": ("🤝 <b>AI sales manager</b> — for businesses where a lead from the website or ads has to turn into "
               "a call, a site visit or a consultation.\n\n"
               "What it does:\n"
               "• a website lead appears in your team's group within a second\n"
               "• the bot messages the person, answers questions using your prices and books a call into a free slot\n"
               "• silence — it follows up; an unusual question — it calls in a manager\n"
               "• the manager sees everything and takes over the conversation with one button\n\n"
               "🎭 Now you are a <b>customer</b> of \"{company}\" (a fictional solar company). "
               "You are on its website leaving a request. <b>What are you interested in?</b> 👇"),
    },
    "sent": {
        "uk": ("📝 Заявку з сайту відправлено ✅\n"
               "<i>На сторінці «Дякую» клієнт бачить кнопку «Обрати час у Telegram» — вона відкриває бота. "
               "Ось що він пише 👇</i>"),
        "ru": ("📝 Заявка с сайта отправлена ✅\n"
               "<i>На странице «Спасибо» клиент видит кнопку «Выбрать время в Telegram» — она открывает бота. "
               "Вот что он пишет 👇</i>"),
        "en": ("📝 Website request sent ✅\n"
               "<i>On the \"Thank you\" page the customer sees a \"Pick a time in Telegram\" button that opens the bot. "
               "Here is what it writes 👇</i>"),
    },
    "hint": {
        "uk": ("<i>Далі пишіть як клієнт: питайте про ціни, розстрочку, гарантію або запишіться кнопками. "
               "«👀 Очима менеджера» — що в цей час бачить ваша команда.</i>"),
        "ru": ("<i>Дальше пишите как клиент: спрашивайте о ценах, рассрочке, гарантии или запишитесь кнопками. "
               "«👀 Глазами менеджера» — что в это время видит ваша команда.</i>"),
        "en": ("<i>Now write as a customer: ask about prices, instalments, warranty, or book with the buttons. "
               "\"👀 Manager's view\" shows what your team sees meanwhile.</i>"),
    },
    "btn_mgr": {"uk": "👀 Очима менеджера", "ru": "👀 Глазами менеджера", "en": "👀 Manager's view"},
    "btn_restart": {"uk": "🔄 Пройти демо ще раз", "ru": "🔄 Пройти демо ещё раз", "en": "🔄 Run the demo again"},

    # ---------- бот продаж глазами клиента (как в шаблоне sales-template) ----------
    "hello_lead": {
        "uk": ("Вітаю, {name}! Я AI-асистент {m_gen} з «{company}» 👋\n"
               "Бачу вашу заявку на «{svc}». {pitch}\n\nОберіть зручний день 👇 Або напишіть питання — відповім тут."),
        "ru": ("Здравствуйте, {name}! Я AI-ассистент {m_gen} из «{company}» 👋\n"
               "Вижу вашу заявку на «{svc}». {pitch}\n\nВыберите удобный день 👇 Или напишите вопрос — отвечу здесь."),
        "en": ("Hello, {name}! I'm {m_gen}'s AI assistant at \"{company}\" 👋\n"
               "I see your request for \"{svc}\". {pitch}\n\nPick a convenient day 👇 Or ask a question — I'll answer here."),
    },
    "hello_direct": {
        "uk": "Вітаю! Я AI-асистент {m_gen} з «{company}» 👋 {offer}",
        "ru": "Здравствуйте! Я AI-ассистент {m_gen} из «{company}» 👋 {offer}",
        "en": "Hello! I'm {m_gen}'s AI assistant at \"{company}\" 👋 {offer}",
    },
    "pick_day": {"uk": "Оберіть день дзвінка (час київський):", "ru": "Выберите день звонка (время киевское):",
                 "en": "Pick a day for the call (Kyiv time):"},
    "pick_time": {"uk": "{day} — оберіть час:", "ru": "{day} — выберите время:", "en": "{day} — pick a time:"},
    "pick_format": {"uk": "{when}. Як зручніше поговорити?", "ru": "{when}. Как удобнее поговорить?",
                    "en": "{when}. How would you like to talk?"},
    "fmt": {
        "uk": {"tg": "Дзвінок у Telegram", "meet": "Google Meet", "phone": "Телефоном"},
        "ru": {"tg": "Звонок в Telegram", "meet": "Google Meet", "phone": "По телефону"},
        "en": {"tg": "Telegram call", "meet": "Google Meet", "phone": "Phone call"},
    },
    "next": {
        "uk": {"tg": "{m} подзвонить вам у Telegram. ", "meet": "Посилання на Meet {m} надішле сюди. ",
               "phone": "{m} подзвонить на {phone}. "},
        "ru": {"tg": "{m} позвонит вам в Telegram. ", "meet": "Ссылку на Meet {m} пришлёт сюда. ",
               "phone": "{m} позвонит на {phone}. "},
        "en": {"tg": "{m} will call you on Telegram. ", "meet": "{m} will send the Meet link here. ",
               "phone": "{m} will call {phone}. "},
    },
    "ask_phone": {"uk": "Напишіть номер, на який подзвонити (або надішліть контакт).",
                  "ru": "Напишите номер, на который позвонить (или отправьте контакт).",
                  "en": "Send the number to call (or share your contact)."},
    "btn_share_phone": {"uk": "📱 Надіслати мій номер", "ru": "📱 Отправить мой номер", "en": "📱 Share my number"},
    "bad_phone": {"uk": "Схоже, це не номер телефону. Напишіть, будь ласка, у форматі 0XX XXX XX XX.",
                  "ru": "Похоже, это не номер телефона. Напишите, пожалуйста, в формате 0XX XXX XX XX.",
                  "en": "That doesn't look like a phone number. Please write it like +380 XX XXX XX XX."},
    "booked": {
        "uk": "✅ Готово! Дзвінок з {m_ins} — <b>{when}</b> (Київ), {fmt}.\n{next}За 2 години нагадаю тут.",
        "ru": "✅ Готово! Звонок с {m_ins} — <b>{when}</b> (Киев), {fmt}.\n{next}За 2 часа напомню здесь.",
        "en": "✅ Done! Call with {m_ins} — <b>{when}</b> (Kyiv), {fmt}.\n{next}I'll remind you here 2 hours before.",
    },
    "taken": {"uk": "Це вікно щойно зайняли 🙈 Оберіть інше:", "ru": "Это окно только что заняли 🙈 Выберите другое:",
              "en": "That slot was just taken 🙈 Pick another one:"},
    "already": {"uk": "У вас уже є дзвінок: <b>{when}</b> ({fmt}). Перенести?",
                "ru": "У вас уже есть звонок: <b>{when}</b> ({fmt}). Перенести?",
                "en": "You already have a call: <b>{when}</b> ({fmt}). Reschedule?"},
    "btn_resched": {"uk": "🔁 Перенести", "ru": "🔁 Перенести", "en": "🔁 Reschedule"},
    "btn_cancel": {"uk": "❌ Скасувати", "ru": "❌ Отменить", "en": "❌ Cancel"},
    "btn_back": {"uk": "← Назад", "ru": "← Назад", "en": "← Back"},
    "cancelled": {"uk": "Дзвінок скасовано. Якщо передумаєте — просто напишіть сюди.",
                  "ru": "Звонок отменён. Если передумаете — просто напишите сюда.",
                  "en": "The call is cancelled. If you change your mind, just write here."},
    "busy_ai": {"uk": "{m} відповість вам тут особисто найближчим часом 🙏",
                "ru": "{m} ответит вам здесь лично в ближайшее время 🙏",
                "en": "{m} will reply to you here personally very soon 🙏"},
    # ---------- подсказки демо ----------
    "after_booked": {
        "uk": "🎉 Ви щойно записалися як клієнт. Тепер подивіться, що в цю секунду отримала команда «{company}» 👇",
        "ru": "🎉 Вы только что записались как клиент. Теперь посмотрите, что в эту секунду получила команда «{company}» 👇",
        "en": "🎉 You've just booked as a customer. Now see what the \"{company}\" team received this very second 👇",
    },
    "after_handoff": {
        "uk": ("<i>Демо: у справжньому боті тут ІІ замовкає, а в групу приходить картка «🙋 Потрібна {m}». "
               "Подивіться «👀 Очима менеджера».</i>"),
        "ru": ("<i>Демо: в настоящем боте здесь ИИ замолкает, а в группу приходит карточка «🙋 Нужна {m}». "
               "Посмотрите «👀 Глазами менеджера».</i>"),
        "en": ("<i>Demo: in the real bot the AI goes quiet here and the group gets a \"🙋 {m} needed\" card. "
               "Check \"👀 Manager's view\".</i>"),
    },
    "need_lead": {
        "uk": "Спершу залиште тестову заявку: оберіть, що вас цікавить 👇",
        "ru": "Сначала оставьте тестовую заявку: выберите, что вас интересует 👇",
        "en": "First leave a test request: pick what you're interested in 👇",
    },

    # ---------- глазами менеджера ----------
    "mgr_title": {
        "uk": "👀 <b>Очима менеджера</b>: так це виглядає в групі «{company} · Заявки» 👇",
        "ru": "👀 <b>Глазами менеджера</b>: так это выглядит в группе «{company} · Заявки» 👇",
        "en": "👀 <b>Manager's view</b>: this is how it looks in the \"{company} · Leads\" group 👇",
    },
    "card": {
        "uk": "🆕 <b>Лід #{n}</b> · {src}\n👤 {name} · {contact}{svc}\n📣 google / {campaign}\n🤖 {plan}",
        "ru": "🆕 <b>Лид #{n}</b> · {src}\n👤 {name} · {contact}{svc}\n📣 google / {campaign}\n🤖 {plan}",
        "en": "🆕 <b>Lead #{n}</b> · {src}\n👤 {name} · {contact}{svc}\n📣 google / {campaign}\n🤖 {plan}",
    },
    "src": {"uk": {"site": "заявка з сайту", "tg": "написав боту сам"},
            "ru": {"site": "заявка с сайта", "tg": "написал боту сам"},
            "en": {"site": "website request", "tg": "wrote to the bot directly"}},
    "campaign": {"uk": "сонячні-станції", "ru": "солнечные-станции", "en": "solar-stations"},
    "plan": {
        "uk": "чекаємо 3 хв, чи відкриє Telegram/WhatsApp сам; потім — шаблон у WhatsApp",
        "ru": "ждём 3 мин, откроет ли Telegram/WhatsApp сам; потом — шаблон в WhatsApp",
        "en": "waiting 3 min for them to open Telegram/WhatsApp; then a WhatsApp template",
    },
    "mg_take": {"uk": "🙋 Беру сам", "ru": "🙋 Беру сам", "en": "🙋 I'll take it"},
    "mg_msg": {"uk": "✉️ Написати через бота", "ru": "✉️ Написать через бота", "en": "✉️ Reply via bot"},
    "mg_lost": {"uk": "🚫 Не цільовий", "ru": "🚫 Не целевой", "en": "🚫 Not a fit"},
    "mg_ok": {"uk": "✅ Підтвердити", "ru": "✅ Подтвердить", "en": "✅ Confirm"},
    "alert": {
        "uk": {"take": "У справжньому боті: ІІ і автоматика по цьому ліду вимикаються, далі веде людина.",
               "msg": "У справжньому боті: ви відповідаєте на повідомлення бота, і текст іде клієнту в його канал.",
               "lost": "У справжньому боті: лід позначається нецільовим, бот йому більше не пише.",
               "ok": "У справжньому боті: клієнт отримує «Дзвінок підтверджено» з посиланням на Meet."},
        "ru": {"take": "В настоящем боте: ИИ и автоматика по этому лиду выключаются, дальше ведёт человек.",
               "msg": "В настоящем боте: вы отвечаете на сообщение бота, и текст уходит клиенту в его канал.",
               "lost": "В настоящем боте: лид помечается нецелевым, бот ему больше не пишет.",
               "ok": "В настоящем боте: клиент получает «Звонок подтверждён» со ссылкой на Meet."},
        "en": {"take": "In the real bot: the AI and automation for this lead switch off, a person takes over.",
               "msg": "In the real bot: you reply to the bot's message and the text goes to the customer's channel.",
               "lost": "In the real bot: the lead is marked as not a fit and the bot stops messaging them.",
               "ok": "In the real bot: the customer gets \"Call confirmed\" with the Meet link."},
    },
    "feed_title": {"uk": "Стрічка по ліду #{n} (кожна подія — відповіддю на картку):",
                   "ru": "Лента по лиду #{n} (каждое событие — ответом на карточку):",
                   "en": "Lead #{n} feed (each event is a reply to the card):"},
    "feed_empty": {"uk": "Поки подій немає: напишіть боту або оберіть час.",
                   "ru": "Пока событий нет: напишите боту или выберите время.",
                   "en": "No events yet: write to the bot or pick a time."},
    "ev": {
        "uk": {"open": "📲 Клієнт відкрив Telegram-бота", "in": "💬 {x}",
               "booked": "✅ <b>Записався на дзвінок</b>: {x}", "handoff": "🙋 <b>Потрібна {m}</b>: {x}",
               "info": "📝 Бот дізнався: {x}", "resched": "🔁 Переносить дзвінок {x}", "cancel": "❌ Скасував дзвінок {x}",
               "noai": "⚠️ ІІ не відповів (ліміт) — відповідайте вручну"},
        "ru": {"open": "📲 Клиент открыл Telegram-бота", "in": "💬 {x}",
               "booked": "✅ <b>Записался на звонок</b>: {x}", "handoff": "🙋 <b>Нужна {m}</b>: {x}",
               "info": "📝 Бот узнал: {x}", "resched": "🔁 Переносит звонок {x}", "cancel": "❌ Отменил звонок {x}",
               "noai": "⚠️ ИИ не ответил (лимит) — ответьте вручную"},
        "en": {"open": "📲 The customer opened the Telegram bot", "in": "💬 {x}",
               "booked": "✅ <b>Booked a call</b>: {x}", "handoff": "🙋 <b>{m} needed</b>: {x}",
               "info": "📝 The bot learned: {x}", "resched": "🔁 Rescheduling the call {x}",
               "cancel": "❌ Cancelled the call {x}", "noai": "⚠️ The AI didn't reply (limit) — reply manually"},
    },
    "todo": {
        "uk": {"tg": "📞 Подзвонити в Telegram", "meet": "🔗 Надіслати посилання на Meet", "phone": "☎️ Подзвонити на {phone}"},
        "ru": {"tg": "📞 Позвонить в Telegram", "meet": "🔗 Отправить ссылку на Meet", "phone": "☎️ Позвонить на {phone}"},
        "en": {"tg": "📞 Call on Telegram", "meet": "🔗 Send the Meet link", "phone": "☎️ Call {phone}"},
    },
    "mgr_explain": {
        "uk": ("<b>Що ще робить бот продажів</b> (у демо цього не видно):\n"
               "• не натиснув Telegram за 3 хв — бот пише першим у WhatsApp\n"
               "• мовчить 20 хв — у групу картка «☎️ Подзвонити вручну»\n"
               "• спілкувався, але не записався — одне нагадування через добу\n"
               "• за 2 години до дзвінка — нагадування клієнту і команді\n"
               "• подія в Google Calendar менеджера, вільні вікна — з його календаря\n"
               "• /leads — останні ліди зі статусами\n\n"
               "Під ваш бізнес налаштовуємо ціни, умови, графік і тексти."),
        "ru": ("<b>Что ещё делает бот продаж</b> (в демо этого не видно):\n"
               "• не нажал Telegram за 3 мин — бот пишет первым в WhatsApp\n"
               "• молчит 20 мин — в группу карточка «☎️ Позвонить вручную»\n"
               "• общался, но не записался — одно напоминание через сутки\n"
               "• за 2 часа до звонка — напоминание клиенту и команде\n"
               "• событие в Google Calendar менеджера, свободные окна — из его календаря\n"
               "• /leads — последние лиды со статусами\n\n"
               "Под ваш бизнес настраиваем цены, условия, график и тексты."),
        "en": ("<b>What else the sales bot does</b> (not visible in the demo):\n"
               "• didn't tap Telegram within 3 min — the bot writes first on WhatsApp\n"
               "• silent for 20 min — a \"☎️ Call manually\" card goes to the group\n"
               "• talked but didn't book — one follow-up a day later\n"
               "• 2 hours before the call — a reminder to the customer and the team\n"
               "• an event in the manager's Google Calendar, free slots come from that calendar\n"
               "• /leads — latest leads with statuses\n\n"
               "We set up prices, terms, schedule and texts for your business."),
    },
}


def st(lang: str, key: str, **kw):
    """Текст демо на языке клиента; неизвестный язык — украинский. Словари возвращаются как есть."""
    v = ST[key]
    val = v.get(lang) or v.get("uk")
    if isinstance(val, str) and kw:
        return val.format(**kw)
    return val
