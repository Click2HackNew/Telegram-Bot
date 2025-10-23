# main.py
import logging
import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
QR_CODE_URL = os.getenv("QR_CODE_URL")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

(
    SELECTING_DATA_TYPE,
    SELECTING_RECHARGE,
    AWAITING_SCREENSHOT,
    AWAITING_ADMIN_DATA,
) = range(4)

def setup_database():
    conn = sqlite3.connect("orders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            data_type TEXT NOT NULL,
            recharge_plan TEXT NOT NULL,
            status TEXT NOT NULL,
            order_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            screenshot_file_id TEXT
        )
    """
    )
    conn.commit()
    conn.close()
    logger.info("डेटाबेस सफलतापूर्वक सेटअप हो गया।")

def create_order(user_id, username, data_type, recharge_plan):
    conn = sqlite3.connect("orders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO orders (user_id, username, data_type, recharge_plan, status) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, data_type, recharge_plan, "Pending"),
    )
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id

def update_order_status(order_id, status):
    conn = sqlite3.connect("orders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()

def update_order_screenshot(order_id, file_id):
    conn = sqlite3.connect("orders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET screenshot_file_id = ? WHERE id = ?", (file_id, order_id))
    conn.commit()
    conn.close()

def get_order_details(order_id):
    conn = sqlite3.connect("orders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, data_type, recharge_plan, status, screenshot_file_id, username, id, order_time FROM orders WHERE id = ?", (order_id,))
    result = cursor.fetchone()
    conn.close()
    return result

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("Data", callback_data="show_data_options")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "नमस्ते! डेटा खरीदने के लिए नीचे दिए गए बटन का उपयोग करें।", reply_markup=reply_markup
    )
    return SELECTING_DATA_TYPE

async def show_data_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Fresh Bank Data", callback_data="Fresh Bank Data")],
        [InlineKeyboardButton("Old Bank Data", callback_data="Old Bank Data")],
        [InlineKeyboardButton("Mix Data", callback_data="Mix Data")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("कृपया डेटा का प्रकार चुनें:", reply_markup=reply_markup)
    return SELECTING_RECHARGE

async def show_recharge_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["data_type"] = query.data
    keyboard = [
        [InlineKeyboardButton("₹3000 में 500 Data", callback_data="3000_500")],
        [InlineKeyboardButton("₹6000 में 1000 Data", callback_data="6000_1000")],
        [InlineKeyboardButton("₹10000 में 1500 Data", callback_data="10000_1500")],
        [InlineKeyboardButton("₹20000 में 3000 Data", callback_data="20000_3000")],
        [InlineKeyboardButton("<< वापस", callback_data="show_data_options")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("कृपया अपना रिचार्ज प्लान चुनें:", reply_markup=reply_markup)
    return AWAITING_SCREENSHOT

async def process_recharge_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    
    if query.data == "show_data_options":
        keyboard = [
            [InlineKeyboardButton("Fresh Bank Data", callback_data="Fresh Bank Data")],
            [InlineKeyboardButton("Old Bank Data", callback_data="Old Bank Data")],
            [InlineKeyboardButton("Mix Data", callback_data="Mix Data")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("कृपया डेटा का प्रकार चुनें:", reply_markup=reply_markup)
        return SELECTING_RECHARGE
        
    data_type = context.user_data["data_type"]
    recharge_plan = query.data
    order_id = create_order(user.id, user.username or user.first_name, data_type, recharge_plan)
    context.user_data["order_id"] = order_id
    
    await query.edit_message_text(f"आपका ऑर्डर (ID: {order_id}) सफलतापूर्वक बना दिया गया है।")
    
    await context.bot.send_photo(
        chat_id=user.id,
        photo=QR_CODE_URL,
        caption="यह रहा आपका QR, स्कैन करके पेमेंट करें और पेमेंट का स्क्रीनशॉट यहीं भेजें।",
    )
    return AWAITING_SCREENSHOT

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    photo_file = update.message.photo[-1]
    order_id = context.user_data.get("order_id")

    if not order_id:
        await update.message.reply_text("कोई सक्रिय ऑर्डर नहीं मिला। कृपया /start से दोबारा शुरू करें।")
        return ConversationHandler.END

    update_order_screenshot(order_id, photo_file.file_id)
    
    await update.message.reply_text("धन्यवाद! आपका स्क्रीनशॉट मिल गया है। यह अभी प्रोसेसिंग में है, एडमिन जल्द ही इसे वेरिफाई करेगा।")

    keyboard = [
        [
            InlineKeyboardButton("✅ Send Data", callback_data=f"admin_approve_{order_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"admin_cancel_{order_id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    caption = f"नया पेमेंट स्क्रीनशॉट!\nऑर्डर ID: {order_id}\nयूज़र: @{user.username} (ID: {user.id})"
    
    await context.bot.send_photo(
        chat_id=ADMIN_ID, photo=photo_file.file_id, caption=caption, reply_markup=reply_markup
    )
    return ConversationHandler.END

async def admin_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    action = parts[1]
    order_id = int(parts[2])

    order_details = get_order_details(order_id)
    if not order_details:
        await query.edit_message_text("यह ऑर्डर अब मौजूद नहीं है।")
        return ConversationHandler.END

    user_id = order_details[0]
    
    if action == "approve":
        context.user_data[f"admin_order_user_{order_id}"] = user_id
        await query.edit_message_text(f"ऑर्डर ID: {order_id} को डेटा भेजने के लिए, कृपया इस संदेश का रिप्लाई करके डेटा भेजें।")
        return AWAITING_ADMIN_DATA
        
    elif action == "cancel":
        update_order_status(order_id, "Cancelled")
        await context.bot.send_message(chat_id=user_id, text=f"आपका ऑर्डर (ID: {order_id}) एडमिन द्वारा कैंसिल कर दिया गया है।")
        await query.edit_message_text(f"ऑर्डर ID: {order_id} को सफलतापूर्वक कैंसिल कर दिया गया है।")
        return ConversationHandler.END

async def admin_data_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.reply_to_message and "रिप्लाई करके डेटा भेजें" in update.message.reply_to_message.text:
        try:
            text = update.message.reply_to_message.text
            order_id = int(text.split("ID: ")[1].split(" ")[0])
        except (IndexError, ValueError):
            await update.message.reply_text("ऑर्डर आईडी नहीं मिल सका। कृपया सही तरीके से रिप्लाई करें।")
            return AWAITING_ADMIN_DATA

        user_id = context.user_data.get(f"admin_order_user_{order_id}")
        if not user_id:
            order_details = get_order_details(order_id)
            if not order_details:
                await update.message.reply_text(f"ऑर्डर ID {order_id} के लिए यूज़र नहीं मिला।")
                return AWAITING_ADMIN_DATA
            user_id = order_details[0]

        await context.bot.copy_message(
            chat_id=user_id,
            from_chat_id=update.message.chat_id,
            message_id=update.message.message_id,
            caption=f"आपके ऑर्डर (ID: {order_id}) का डेटा यहाँ है।"
        )
        
        update_order_status(order_id, "Completed")
        await context.bot.send_message(chat_id=user_id, text="आपका ऑर्डर पूरा हो गया है। धन्यवाद!")
        await update.message.reply_text(f"डेटा सफलतापूर्वक यूज़र को भेज दिया गया है। ऑर्डर ID: {order_id} पूरा हुआ।")

        if f"admin_order_user_{order_id}" in context.user_data:
            del context.user_data[f"admin_order_user_{order_id}"]
            
        return ConversationHandler.END
        
    return AWAITING_ADMIN_DATA

async def get_pending_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = sqlite3.connect("orders.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, username, data_type, recharge_plan FROM orders WHERE status = 'Pending'")
    orders = cursor.fetchall()
    conn.close()

    if not orders:
        await update.message.reply_text("कोई भी पेंडिंग ऑर्डर नहीं है।")
        return

    message = "📋 **पेंडिंग ऑर्डर्स:**\n\n"
    for order in orders:
        order_id, user_id, username, data_type, recharge_plan = order
        recharge_text = recharge_plan.replace('_', ' में ')
        message += f"🔹 **ID:** `{order_id}`\n   - **यूज़र:** @{username} ({user_id})\n   - **प्लान:** {data_type} - {recharge_text}\n   - कमांड: `/order {order_id}`\n\n"
    await update.message.reply_text(message, parse_mode='Markdown')

async def get_order_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        order_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("उदाहरण: /order 123")
        return

    order = get_order_details(order_id)

    if not order:
        await update.message.reply_text(f"ऑर्डर आईडी {order_id} नहीं मिला।")
        return
    
    user_id, data_type, recharge_plan, status, screenshot_id, username, oid, order_time_str = order
    
    try:
        order_time = datetime.fromisoformat(order_time_str).strftime('%d %b %Y, %I:%M %p')
    except:
        order_time = order_time_str

    recharge_text = recharge_plan.replace('_', ' में ')
    
    message = (
        f"**ऑर्डर विवरण (ID: {oid})**\n\n"
        f"**यूज़र ID:** `{user_id}`\n"
        f"**यूज़रनेम:** @{username}\n"
        f"**डेटा प्रकार:** {data_type}\n"
        f"**रिचार्ज प्लान:** {recharge_text}\n"
        f"**स्टेटस:** {status}\n"
        f"**ऑर्डर समय:** {order_time}\n"
    )
    await update.message.reply_text(message, parse_mode='Markdown')
    
    if screenshot_id:
        await update.message.reply_text("यूज़र द्वारा भेजा गया स्क्रीनशॉट:")
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=screenshot_id)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("ऑपरेशन रद्द कर दिया गया है।", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main() -> None:
    if not all([BOT_TOKEN, ADMIN_ID, QR_CODE_URL]):
        logger.error("एक या अधिक पर्यावरण चर (BOT_TOKEN, ADMIN_ID, QR_CODE_URL) सेट नहीं हैं।")
        return

    setup_database()
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECTING_DATA_TYPE: [CallbackQueryHandler(show_data_options, pattern="^show_data_options$")],
            SELECTING_RECHARGE: [CallbackQueryHandler(show_recharge_options, pattern="^(Fresh Bank Data|Old Bank Data|Mix Data)$")],
            AWAITING_SCREENSHOT: [
                CallbackQueryHandler(process_recharge_selection, pattern=r"^\d+_\d+$|show_data_options"),
                MessageHandler(filters.PHOTO, handle_screenshot),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    admin_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_action_handler, pattern=r"^admin_(approve|cancel)_\d+$")],
        states={
            AWAITING_ADMIN_DATA: [MessageHandler(filters.REPLY & (filters.TEXT | filters.Document.ALL), admin_data_reply_handler)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    application.add_handler(conv_handler)
    application.add_handler(admin_conv_handler)
    application.add_handler(CommandHandler("orders", get_pending_orders, filters=filters.User(user_id=ADMIN_ID)))
    application.add_handler(CommandHandler("order", get_order_by_id, filters=filters.User(user_id=ADMIN_ID)))

    logger.info("बॉट Long Polling मोड में शुरू हो रहा है...")
    application.run_polling()

if __name__ == "__main__":
    main()
          
