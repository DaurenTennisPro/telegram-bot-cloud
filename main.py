import logging
import asyncio
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes, CallbackQueryHandler
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# ==== Логирование ====
logging.basicConfig(level=logging.INFO)

# ==== НАСТРОЙКИ ====
TOKEN = "7339504860:AAEFEXix0Q10SSWSzDk6mfOfVOdwsRnrras"
SPREADSHEET_ID = "1npURWdH4IkFp3C01ZAmLS4PZyhRXqzy-tvmD7QqSNvA"
SHEET_NAME = "Заявки клиента"
MASTER_SHEET = "Мастера"
ADMIN_CHAT_ID = "6126002181"

# ==== Подключение Google Таблицы ====
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
master_sheet = client.open_by_key(SPREADSHEET_ID).worksheet(MASTER_SHEET)

# ==== Состояния ====
NAME, PHONE, SERVICE, MASTER, RESTART_CONFIRMATION = range(5)
user_data_dict = {}
CANCEL_HINT = "\n\nВы можете ввести /cancel, чтобы отменить заявку."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data_dict[update.effective_chat.id] = {"chat_id": update.effective_chat.id}
    context.user_data.clear()
    await update.message.reply_text("\U0001F44B Привет! Давайте оформим заявку.\nВведите ваше имя:" + CANCEL_HINT)
    return NAME

async def name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data_dict[update.effective_chat.id]["Имя"] = update.message.text.strip()
    await update.message.reply_text("Введите ваш номер телефона:" + CANCEL_HINT)
    return PHONE

async def phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data_dict[update.effective_chat.id]["Телефон"] = update.message.text.strip()
    values = master_sheet.get_all_values()
    data = values[1:]
    services = sorted(set(row[0].strip() for row in data if len(row) > 0 and row[0].strip()))
    reply_keyboard = [services[i:i+2] for i in range(0, len(services), 2)]
    await update.message.reply_text("Выберите услугу:" + CANCEL_HINT, reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True))
    return SERVICE

async def service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected_service = update.message.text.strip()
    user_data_dict[update.effective_chat.id]["Услуга"] = selected_service
    values = master_sheet.get_all_values()
    data = values[1:]
    matched_masters = [row[1].strip() for row in data if len(row) >= 2 and row[0].strip().lower() == selected_service.lower() and row[1].strip()]
    matched_masters = sorted(set(matched_masters))
    if not matched_masters:
        await update.message.reply_text("\U0001F614 Нет доступных мастеров для этой услуги." + CANCEL_HINT)
        return ConversationHandler.END
    reply_keyboard = [matched_masters[i:i+2] for i in range(0, len(matched_masters), 2)]
    await update.message.reply_text("Выберите мастера:" + CANCEL_HINT, reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True))
    return MASTER

async def master(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data_dict[update.effective_chat.id]["Мастер"] = update.message.text.strip()
    return await ask_date(update, context)

async def ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    today = datetime.today()
    buttons = []
    for i in range(7):
        date_obj = today + timedelta(days=i)
        day_str = date_obj.strftime("%a %d.%m")
        date_str = date_obj.strftime("%d.%m.%Y")
        buttons.append(InlineKeyboardButton(f"{day_str}", callback_data=f"date|{date_str}"))
    keyboard = [buttons[i:i+3] for i in range(0, len(buttons), 3)]
    await update.message.reply_text("Выберите дату:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def time_manual_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = user_data_dict.get(chat_id, {})

    if "Дата" in data and "Время" not in data:
        data["Время"] = update.message.text.strip()
        data["Время заявки"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        user_data_dict[chat_id] = data

        headers = sheet.row_values(1)
        row_data = [data.get(header, "") for header in headers]
        sheet.append_row(row_data)

        master_values = master_sheet.get_all_values()
        matched_chat_id = None
        for row in master_values[1:]:
            if len(row) >= 3 and row[1].strip().lower() == data["Мастер"].strip().lower():
                matched_chat_id = row[2]
                break

        message = f"\U0001F4EC *Новая заявка!*\nИмя: {data['Имя']}\nТелефон: {data['Телефон']}\nУслуга: {data['Услуга']}\nМастер: {data['Мастер']}\nДата: {data['Дата']}\nВремя: {data['Время']}"
        try:
            matched_chat_id = int(str(matched_chat_id).strip())
            await context.bot.send_message(chat_id=matched_chat_id, text=message, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"❌ Ошибка отправки мастеру: {e}")
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="[Копия админу]\n" + message)

        reply_keyboard = [["Да"], ["Нет"]]
        await update.message.reply_text("✅ Спасибо! Ваша заявка отправлена! Хотите оформить ещё одну?", reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True))

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["Да"], ["Нет"]]
    await update.message.reply_text("❌ Заявка отменена. Хотите начать заново?", reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True))
    return RESTART_CONFIRMATION

async def restart_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip().lower() == "да":
        return await start(update, context)
    else:
        await update.message.reply_text("Хорошо, если что — я здесь \U0001F4AC\n\nЧтобы начать оформление новой заявки, просто напишите /start.")
        return ConversationHandler.END

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Чтобы начать оформление заявки, введите /start или нажмите кнопку \U0001F4DD Оформить заявку")

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Ваш Chat ID: `{chat_id}`", parse_mode="Markdown")

async def handle_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")
    if data[0] == "feedback":
        row_num = int(data[1])
        rating = data[2]
        try:
            sheet.update_cell(row_num, sheet.find("Оценка").col, rating)
            await query.edit_message_text("✅ Спасибо за вашу оценку!")
        except Exception as e:
            logging.error(f"Ошибка записи оценки: {e}")
            await query.edit_message_text("⚠️ Не удалось сохранить вашу оценку.")
    elif data[0] == "date":
        selected_date = data[1]
        chat_id = update.effective_chat.id
        user_data_dict[chat_id]["Дата"] = selected_date
        await query.edit_message_text(f"📅 Вы выбрали дату: *{selected_date}*", parse_mode="Markdown")
        await context.bot.send_message(chat_id=chat_id, text="Теперь введите удобное время (например: 15:00):")

async def request_feedback(application):
    while True:
        try:
            values = sheet.get_all_values()
            headers = values[0]
            data = values[1:]
            for i, row in enumerate(data, start=2):
                row_dict = dict(zip(headers, row))
                if not all(k in row_dict for k in ["Дата", "Время", "chat_id"]):
                    continue
                if row_dict.get("Оценка"):
                    continue
                dt_str = f"{row_dict['Дата']} {row_dict['Время']}"
                try:
                    appointment_time = datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
                    now = datetime.now()
                    if timedelta(minutes=115) < now - appointment_time <= timedelta(minutes=125):
                        chat_id = int(row_dict["chat_id"])
                        service = row_dict.get("Услуга", "услуга")
                        master = row_dict.get("Мастер", "мастер")
                        msg = f"\U0001F4DD Как вам услуга '{service}' от мастера {master}?\nПожалуйста, выберите оценку от 1 до 5:"
                        keyboard = [[
                            InlineKeyboardButton("⭐1", callback_data=f"feedback|{i}|1"),
                            InlineKeyboardButton("⭐2", callback_data=f"feedback|{i}|2"),
                            InlineKeyboardButton("⭐3", callback_data=f"feedback|{i}|3"),
                            InlineKeyboardButton("⭐4", callback_data=f"feedback|{i}|4"),
                            InlineKeyboardButton("⭐5", callback_data=f"feedback|{i}|5")
                        ]]
                        await application.bot.send_message(chat_id=chat_id, text=msg, reply_markup=InlineKeyboardMarkup(keyboard))
                except Exception as e:
                    logging.error(f"Ошибка при отправке отзыва: {e}")
        except Exception as e:
            logging.error(f"Цикл отзывов: {e}")
        await asyncio.sleep(600)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone)],
            SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, service)],
            MASTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, master)],
            RESTART_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, restart_decision)]
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.ALL, fallback)]
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CallbackQueryHandler(handle_feedback_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, time_manual_handler))
    print("✅ Бот запущен. Ожидает команду /start.")
    loop = asyncio.get_event_loop()
    loop.create_task(request_feedback(app))
    loop.run_until_complete(app.run_polling())


