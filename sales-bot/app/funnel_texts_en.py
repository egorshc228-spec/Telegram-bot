"""English versions of the ADrenaline funnel texts (same numbers and sources as uk/ru in funnel_texts.py).
They are merged into FT["key"]["en"] at the end of funnel_texts.py."""

EN = {
    "checklist": ("📋 <b>Checklist: 10 places where your Google Ads budget leaks</b>\n\n"
                  "1. Ads show for the wrong search queries\n2. The conversion counted is not a lead\n"
                  "3. Form leads never reach Google Ads\n4. Phone calls are not tracked\n"
                  "5. The search campaign runs on partner sites\n6. People from other cities see your ads\n"
                  "7. Google applies its own recommendations automatically\n8. Performance Max eats your brand traffic\n"
                  "9. The site is slow on mobile\n10. A lead waits hours for a reply\n\n"
                  "How to check each point in a minute: {url}\n\n"
                  "Point 10 is solved by an AI assistant. Below is a demo: see how it talks to your customers 👇"),
    "intro": ("👋 Hi! This is the demo of the <b>AI assistant by ADrenaline</b>.\n\n"
              "In 2 minutes I'll show how it replies to your customers, books them in, and what you see "
              "as the owner at that moment.\n\n<b>What is your business?</b> I'll tailor the demo to it 👇\n\n"
              "<i>Selling through calls, site visits or consultations? See \"🤝 Sales bot\".</i>"),
    "niche_btn": {"salon": "💇 Beauty salon", "dental": "🦷 Clinic / dentistry", "auto": "🚗 Car service",
                  "shop": "🛍 Shop", "other": "✍️ Other"},
    "ask_biz": "Describe your business in a few words (for example: \"a fitness studio in Odesa\").",
    "biz_mapped": "Thank you! I'll show it with the closest example: <b>{title}</b>. The logic is the same for any business.",
    "role": ("🎭 Now you are the <b>customer</b>: {company} (a fictional company, prices are illustrative).\n\n"
             "Write as you would in a DM, or tap an example below 👇\n"
             "Try to <b>book an appointment</b>: you'll see the whole path of a booking.\n\n"
             "<i>At any moment: \"👀 Owner's view\" — what you see, \"📅 Call\" — talk to us.</i>"),
    "btn_owner": "👀 Owner's view",
    "btn_call": "📅 Call with ADrenaline",
    "nudge_booked": ("🎉 You've just booked as a customer.\n"
                     "Now the interesting part: see what the owner received this very second 👇"),
    "nudge_try_booking": ("💡 Try booking: write, for example, \"book me for tomorrow\".\n"
                          "Or look right away at how it looks from your side 👇"),
    "want_bot": "🙌 Great! The fastest way is a 20-minute call: we'll show the bot on your real questions and name the exact price.",
    "owner_title": "📲 <b>This is how a booking reaches you in Telegram</b> (tap ✅ and the \"customer\", i.e. you, gets a confirmation):\n\n",
    "owner_sample": ("📲 <b>This is how a booking looks in your Telegram</b> (example):\n\n"
                     "🆕 <b>New booking #17</b>\n🏢 {company}\n💼 {service}\n📅 {date} at 18:30\n"
                     "👤 Olena · +380 67 123 45 67\n💬 \"Can I see the stylist Iryna?\"\n\n"
                     "Under the booking there are buttons ✅ Confirm · ❌ Decline · ✉️ Reply.\n"
                     "<i>Book in the demo and you'll see your own booking.</i>"),
    "owner_explain": ("What happens next, without your involvement:\n"
                      "• the customer sees the booking in their account in the bot\n"
                      "• gets a reminder a day and 2 hours before\n"
                      "• after the visit the bot asks for a review; a low rating goes straight to you\n"
                      "• the bot doesn't make things up in hard cases, it hands them to you with the conversation\n"
                      "• all bookings in Excel with one command"),
    "btn_report": "📊 Excel report",
    "btn_remind": "🔔 Reminder to the customer",
    "btn_pitch": "➡️ What it gives your business",
    "need_booking": "First book in the demo as a customer — then your booking will appear here.",
    "p0": ("<b>1/6 · Where customers are lost</b>\n\n"
           "• <b>21×</b> higher chances if you reply within 5 minutes instead of 30 <i>(MIT / InsideSales)</i>\n"
           "• <b>42 h</b> is the average wait for a website lead <i>(Harvard Business Review, 2,241 companies)</i>\n"
           "• <b>39%</b> of calls never reach a live person <i>(Invoca, 60 million calls)</i>\n"
           "• <b>up to 51%</b> of inquiries in some niches come after 5 PM <i>(BrightLocal)</i>\n\n"
           "A customer writes to you and two more competitors. The one who replies first gets the booking."),
    "p1": ("<b>2/6 · What the AI assistant takes over</b>\n\n"
           "• replies in Instagram, Telegram and on the website within seconds, 24/7\n"
           "• knows your price list, hours and frequent questions; looks at photos\n"
           "• books into a free slot (Altegio, EasyWeek, Google Calendar)\n"
           "• reminds about the visit and collects reviews\n"
           "• honestly hands hard cases to a person with the whole conversation\n\n"
           "Your administrator stops being torn between reception, phone and DMs."),
    "p2": "<b>3/6 · What it costs you now</b>\n\nWe'll calculate in 2 taps. <b>How many inquiries a day</b> do you get (DMs, messengers, calls)?",
    "p2_check": "What is the <b>average check</b> of one customer?",
    "p2_result": ("<b>3/6 · Your estimate</b>\n\n"
                  "≈ {month} inquiries a month. If at least <b>15%</b> of them are left without a quick reply "
                  "<i>(the lower bound of MedPlatforma's estimate: medical centers lose 15–30% of inquiries)</i>, that is <b>≈ {lost}</b> people.\n\n"
                  "If one in five of them became a customer (our assumption), that is <b>≈ {money} ₴ a month</b>.\n"
                  "The AI assistant costs <b>$160 a month</b> including the server and AI{ratio}."),
    "ratio": " — {x} {word} less",
    "fmt_short": {"tg": "Telegram call", "meet": "Google Meet", "phone": "by phone"},
    "p3": ("<b>4/6 · How it works in a real business</b>\n\n"
           "A clothing shop on Instagram. A customer saw a post, commented, moved to DMs — "
           "the AI named prices for three items right away. Another one asked about a size missing from the table — "
           "the AI didn't invent anything and handed it to the manager with the whole conversation.\n\n"
           "Real dialogues (names hidden): {site}/ai-admin#dialogs"),
    "p4": ("<b>5/6 · Price and launch</b>\n\n"
           "• launch <b>$800</b> one-time, then <b>$160/month</b> including the server and AI (up to 1,000 dialogues)\n"
           "• the first version works within a week\n"
           "• 14 days of fine-tuning replies on your real dialogues\n"
           "• the bot, dialogues and data are yours; month to month, exit within 14 days\n"
           "• a voice assistant for calls — from $1,000\n\n"
           "Together with Google Ads: the \"Lead → Customer\" package — $685/month on a 6-month contract."),
    "p5": ("<b>6/6 · Next step</b>\n\n"
           "20 minutes with Daniil (Telegram or Google Meet):\n"
           "• we'll look at where your inquiries get lost\n"
           "• show the bot on your real questions\n"
           "• name the exact price and timeline\n\n"
           "No obligations. If it's not a fit, we'll say so."),
    "btn_next": "Next →",
    "btn_back": "← Back",
    "btn_book": "📅 Choose a call time",
    "btn_write": "✍️ Write to Daniil",
    "volume_opts": ["up to 10", "10–30", "30–60", "60+"],
    "check_opts": ["up to 500 ₴", "500–1,500 ₴", "1,500–5,000 ₴", "5,000+ ₴"],
    "q_volume": "To make the call useful, two short questions.\n\n<b>How many inquiries a day</b> do you get?",
    "q_handler": "<b>Who answers customers</b> in DMs and messengers now?",
    "handler_opts": ["I do", "An administrator", "A manager / sales team", "Nobody in time 🙈"],
    "pick_day": "📅 <b>Choose a day</b> for the 20-minute call (Kyiv time):",
    "pick_time": "🕒 <b>{day}</b> — choose a time:",
    "no_slots": "There are no free slots in the coming days. Write to Daniil directly and we'll arrange it: @{tg}",
    "slot_taken": "That time has just been taken 😅 Please choose another:",
    "pick_format": "Great, <b>{when}</b>. How would you prefer to talk?",
    "fmt": {"tg": "📞 Telegram call", "meet": "💻 Google Meet", "phone": "📱 By phone"},
    "ask_phone": "Send your number with the button below or type it in a message.",
    "btn_share_phone": "📱 Send my number",
    "bad_phone": "This doesn't look like a phone number. Please write it in the format +380…",
    "booked": ("✅ <b>Done!</b> Call with Daniil — <b>{when}</b> (Kyiv), {fmt}.\n"
               "{next}I'll remind you here 2 hours before.\n\n"
               "Until the call you can keep testing the demo: just write as a customer."),
    "btn_resched": "🔁 Reschedule",
    "btn_cancel_call": "❌ Cancel",
    "call_cancelled": "The call is cancelled. If you change your mind — /call",
    "next_meet": "Daniil will send the Google Meet link here before the call. ",
    "next_meet_url": "Google Meet link: {url}\n",
    "meet_link": "\n🔗 Google Meet: {url}",
    "move_confirm": "You already have a call: <b>{old}</b>.\nMove it to <b>{new}</b> ({fmt})?",
    "btn_move_yes": "✅ Yes, move it",
    "btn_move_keep": "Keep as is",
    "move_kept": "Okay, we keep the call on <b>{when}</b> 👍",
    "moved_from": "🔁 Moved from {old}.\n",
    "phone_added": "📱 I passed the number {phone} to Daniil — he can call it ({when}).",
    "next_tg": "Daniil will call you in Telegram. ",
    "next_phone": "Daniil will call your number. ",
    "call_confirmed": "👍 Daniil confirmed the call on <b>{when}</b>. See you then!",
    "call_resched_req": "That time doesn't suit Daniil 🙏 Please choose another time:",
    "call_reminder": "⏰ Reminder: call with Daniil <b>{when}</b> ({fmt}).",
    "already_booked": "You already have a call: <b>{when}</b>. Move it?",
    "sales_prefix": "💬 <b>Daniil, ADrenaline:</b>\n{text}",
    "fu1": ("Thanks for trying the demo 🙌\n\n"
            "This AI assistant was built by the ADrenaline team and is tailored to any business: "
            "your price list, hours, tone of voice.\n"
            "It never sleeps, takes no days off and costs less than an administrator's salary.\n\n"
            "We invite you to a short call (20 min): we'll show how it would work for you and how many "
            "inquiries it brings back."),
    "fu2": ("Why reply speed decides everything, in three numbers:\n\n"
            "• <b>21×</b> — higher chances if you reply within 5 minutes instead of 30 <i>(MIT / InsideSales)</i>\n"
            "• <b>42 hours</b> — the average wait for a website lead <i>(HBR, 2,241 companies)</i>\n"
            "• <b>up to 51%</b> of inquiries in some niches come after 5 PM <i>(BrightLocal)</i>\n\n"
            "The AI assistant replies in seconds — in the evening and on weekends too. Want to calculate what "
            "that is worth in money for you?"),
    "fu3": ("What it looks like in a live business: a clothing shop, Instagram.\n\n"
            "A customer from a comment under a post writes in DMs — the AI names prices for three items right away. "
            "Another asks about a size missing from the table — the AI doesn't invent anything and hands it to the "
            "manager with the conversation.\n\nReal dialogues: {site}/ai-admin#dialogs\n\n"
            "In 20 minutes we'll show the same on your customers' questions."),
    "fu4": ("The last message from me 🙂\n\n"
            "If an AI assistant isn't timely for you right now — no problem, I won't bother you again.\n"
            "If you want to come back: the first version in a week, $800 launch + $160/month including the server and AI, "
            "14 days of fine-tuning together with you. The button is below, or write to Daniil directly: @{tg}"),
    "btn_calc": "🧮 Calculate my losses",
    "btn_stop": "Not interested",
    "stopped": "Understood, I won't write anymore 🙂 If you need us — /call",
}
