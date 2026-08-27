import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# IMPORTANT: Keep your API token secret in production!
TOKEN = os.getenv("BOT_TOKEN", "8916229616:AAHIgqw2rhSaO2DibAfiBOQu-F1qOfTnMVM")

# ADMIN & GROUP LIST
ADMIN_CHAT_IDS = [
    5549781932,          # Primary Admin (@Papapepprotide)
    -1004456380335,      # Telegram Group Chat ID
]

PAYMENT_TIMEOUT_SECONDS = 1800  # 30 Minutes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Conversation States
SHOPPING, WAITING_FOR_NAME, WAITING_FOR_PHONE, WAITING_FOR_ADDRESS = range(4)

PRICES = {
    "retatrutide": 100.0,
    "bacwater": 10.0,
    "reconstitute": 1.50,
    "syringe": 1.0,
    "needle": 1.0,
    "swab": 0.50
}

ITEMS_INFO = {
    "retatrutide": ("Retatrutide 10mg", "vial(s)"),
    "bacwater": ("Bacwater 3ml", "vial(s)"),
    "reconstitute": ("Syringe 3ml 25g (For Reconstitute)", "unit(s)"),
    "syringe": ("100cc Syringe", "unit(s)"),
    "needle": ("4mm Needle 32g", "unit(s)"),
    "swab": ("Alcohol Swab", "unit(s)")
}

def get_restart_keyboard():
    """Generates a reusable inline button to start a new order."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ Start New Order", callback_data="restart_bot_session")]
    ])

def find_qr_image():
    """Searches common Pydroid storage paths for paynow.png."""
    possible_paths = [
        "paynow.png",
        "paynow.jpg",
        "/sdcard/Download/paynow.png",
        "/sdcard/Download/paynow.jpg",
        "/storage/emulated/0/Download/paynow.png",
        "/storage/emulated/0/Download/paynow.jpg",
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None

def build_catalog_view(cart):
    """Generates catalog text and interactive keypad without hiding product catalog."""
    catalog_text = (
        "Welcome to *Protide Peptides*!\n\n"
        "📦 *Product Catalog & Live Cart*\n"
        "-----------------------------------\n"
    )

    total_cost = 0.0
    keyboard = []

    for key, (name, unit) in ITEMS_INFO.items():
        qty = cart.get(key, 0)
        item_price = PRICES[key]
        item_total = qty * item_price
        total_cost += item_total

        catalog_text += f"• *{name}* – ${item_price:.2f} | **Qty:** {qty}\n"

        keyboard.append([
            InlineKeyboardButton("➖", callback_data=f"dec_{key}"),
            InlineKeyboardButton(f"{name} ({qty})", callback_data="ignore"),
            InlineKeyboardButton("➕", callback_data=f"inc_{key}")
        ])

    catalog_text += f"\n💰 *Current Total:* ${total_cost:.2f}\n"
    catalog_text += "-----------------------------------\n"
    catalog_text += "Use the **+** and **-** buttons to add items, then press **Done / Next ➡️**."

    keyboard.append([InlineKeyboardButton("Done / Next ➡️", callback_data="checkout")])

    return catalog_text, InlineKeyboardMarkup(keyboard)

async def get_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Helper command to get the Chat ID of any group the bot is added to."""
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    await update.message.reply_text(
        f"📋 **Chat Information**\n\n"
        f"• **Type:** {chat_type}\n"
        f"• **ID:** `{chat_id}`\n\n"
        f"Add `{chat_id}` to your `ADMIN_CHAT_IDS` list in the script!",
        parse_mode="Markdown"
    )

async def payment_timeout_callback(context: ContextTypes.DEFAULT_TYPE):
    """Triggered when the 30-minute timer expires."""
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    message_id = job_data["message_id"]
    has_photo = job_data["has_photo"]
    customer = job_data["customer"]
    summary = job_data["summary"]
    user_handle_str = job_data["user_handle_str"]

    expired_text = (
        "⏰ *PAYMENT EXPIRED*\n\n"
        "The 30-minute window for this QR code has passed.\n"
        "This order has been cancelled automatically."
    )

    try:
        if has_photo:
            await context.bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=expired_text,
                parse_mode="Markdown"
            )
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=expired_text,
                parse_mode="Markdown"
            )
    except Exception as e:
        logging.error(f"Failed to invalidate payment message: {e}")

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔄 Would you like to create a new order?",
            reply_markup=get_restart_keyboard()
        )
    except Exception as e:
        logging.error(f"Failed to send restart prompt to customer: {e}")

    admin_timeout_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Payment Not Received / Expired", callback_data=f"admin_timeout_ack_{chat_id}")]
    ])

    admin_timeout_text = (
        "⏰ *ORDER TIMED OUT (30 MIN EXPIRED)* ⏰\n\n"
        f"👤 *Customer:* {customer.get('name', 'Unknown')}\n"
        f"💬 *Handle:* {user_handle_str}\n"
        f"📞 *Phone:* {customer.get('phone', 'N/A')}\n"
        f"📍 *Address:* {customer.get('address', 'N/A')}\n\n"
        f"{summary}\n"
        "❌ **Status:** The 30-minute payment window expired before receipt upload."
    )

    for admin_id in ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_timeout_text,
                reply_markup=admin_timeout_keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Failed to send timeout prompt to admin/group {admin_id}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['cart'] = {key: 0 for key in PRICES}
    context.user_data['customer'] = {}

    text, reply_markup = build_catalog_view(context.user_data['cart'])
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SHOPPING

async def start_new_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback target for the 'Start New Order' button."""
    query = update.callback_query
    await query.answer()

    context.user_data['cart'] = {key: 0 for key in PRICES}
    context.user_data['customer'] = {}

    text, reply_markup = build_catalog_view(context.user_data['cart'])
    await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SHOPPING

async def handle_catalog_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    cart = context.user_data.get('cart', {key: 0 for key in PRICES})

    if data == "ignore":
        return SHOPPING

    if data == "checkout":
        total_items = sum(cart.values())
        if total_items == 0:
            await query.answer("Your cart is empty! Add at least one item before continuing.", show_alert=True)
            return SHOPPING

        await query.edit_message_text(
            "Great! Catalog selection complete.\n\n"
            "Please enter your **Full Name** to begin delivery setup:"
        )
        return WAITING_FOR_NAME

    action, item_key = data.split("_", 1)
    if action == "inc":
        cart[item_key] = cart.get(item_key, 0) + 1
    elif action == "dec":
        if cart.get(item_key, 0) > 0:
            cart[item_key] -= 1

    context.user_data['cart'] = cart
    text, reply_markup = build_catalog_view(cart)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SHOPPING

async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['customer']['name'] = update.message.text
    await update.message.reply_text("Got it! Please enter your **Contact Number**:")
    return WAITING_FOR_PHONE

async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['customer']['phone'] = update.message.text
    await update.message.reply_text("Thank you! Now, please enter your full **Delivery Address**:")
    return WAITING_FOR_ADDRESS

async def receive_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['customer']['address'] = update.message.text

    cart = context.user_data['cart']
    customer = context.user_data['customer']
    user_handle = update.message.from_user.username
    user_handle_str = f"@{user_handle}" if user_handle else "No Username"

    summary = "🛒 *Order Summary*\n\n"
    total = 0.0

    for item_key, (name, unit) in ITEMS_INFO.items():
        qty = cart.get(item_key, 0)
        if qty > 0:
            cost = qty * PRICES[item_key]
            total += cost
            summary += f"• {name}: {qty} {unit} – ${cost:.2f}\n"

    summary += f"\n💰 *Total Amount Due:* ${total:.2f}\n"

    context.user_data['order_summary'] = summary
    context.user_data['order_total'] = total
    context.user_data['user_handle_str'] = user_handle_str

    full_details = (
        f"{summary}\n"
        "📍 *Delivery Details*\n"
        f"• **Name:** {customer['name']}\n"
        f"• **Contact:** {customer['phone']}\n"
        f"• **Address:** {customer['address']}\n"
        f"• **Estimated Delivery:** 3 to 5 working days 🚚\n"
    )

    await update.message.reply_text(full_details, parse_mode="Markdown")

    caption_text = (
        f"💳 *Payment Method: PayNow*\n\n"
        f"Please scan the QR code above to pay *${total:.2f}*.\n\n"
        f"⏳ **NOTICE:** This QR code self-destructs in **30 minutes**.\n"
        f"⚠️ **IMPORTANT:** Enter your full name (`{customer['name']}`) as the payment reference.\n\n"
        f"📷 **Next Step:** Send a photo screenshot of your payment receipt in this chat for confirmation."
    )

    image_path = find_qr_image()
    if image_path:
        with open(image_path, "rb") as photo:
            payment_msg = await context.bot.send_photo(
                chat_id=update.message.chat_id,
                photo=photo,
                caption=caption_text,
                parse_mode="Markdown"
            )
            has_photo = True
    else:
        payment_msg = await update.message.reply_text(
            f"💳 *Payment Method: PayNow*\n\n"
            f"Please transfer *${total:.2f}* via PayNow.\n\n"
            f"⏳ **NOTICE:** This request expires in **30 minutes**.\n"
            f"⚠️ **IMPORTANT:** Enter your full name (`{customer['name']}`) as the payment reference.\n\n"
            f"📷 **Next Step:** Send a photo screenshot of your payment receipt in this chat for confirmation.",
            parse_mode="Markdown"
        )
        has_photo = False

    timer_job = context.job_queue.run_once(
        payment_timeout_callback,
        when=PAYMENT_TIMEOUT_SECONDS,
        data={
            "chat_id": update.message.chat_id,
            "message_id": payment_msg.message_id,
            "has_photo": has_photo,
            "customer": customer,
            "summary": summary,
            "user_handle_str": user_handle_str
        }
    )
    context.user_data['payment_job'] = timer_job

    admin_notification = (
        "🚨 *NEW ORDER CREATED!* 🚨\n\n"
        f"👤 *Customer Name:* {customer['name']}\n"
        f"💬 *Telegram Handle:* {user_handle_str}\n"
        f"📞 *Phone:* {customer['phone']}\n"
        f"📍 *Address:* {customer['address']}\n\n"
        f"{summary}\n"
        "⏳ *Status:* Waiting for payment receipt upload (30-min limit)..."
    )

    for admin_id in ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_notification,
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Failed to send notification to admin/group {admin_id}: {e}")

    await update.message.reply_text(
        "👋 Thank you! Please send your payment screenshot here as a photo within 30 minutes.\n\n"
        "Feel free to contact @Papapepprotide for further enquiry."
    )

    return ConversationHandler.END

async def handle_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'payment_job' in context.user_data:
        context.user_data['payment_job'].schedule_removal()
        del context.user_data['payment_job']

    customer = update.message.from_user
    customer_chat_id = update.message.chat_id
    photo_file_id = update.message.photo[-1].file_id

    order_summary = context.user_data.get('order_summary', "Order summary unavailable.")
    customer_info = context.user_data.get('customer', {})
    user_handle_str = context.user_data.get('user_handle_str', f"@{customer.username or 'No Username'}")

    admin_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm Payment", callback_data=f"confirm_{customer_chat_id}"),
            InlineKeyboardButton("❌ Did Not Receive", callback_data=f"decline_{customer_chat_id}")
        ]
    ])

    base_caption = (
        "📸 *NEW PAYMENT RECEIPT UPLOADED!* 📸\n\n"
        f"👤 *Name:* {customer_info.get('name', customer.full_name)}\n"
        f"💬 *Handle:* {user_handle_str}\n"
        f"📞 *Phone:* {customer_info.get('phone', 'N/A')}\n"
        f"📍 *Address:* {customer_info.get('address', 'N/A')}\n"
        f"🆔 *Chat ID:* `{customer_chat_id}`\n\n"
        f"{order_summary}"
    )

    admin_text = f"{base_caption}\n\n👇 *Action Required:* Verify PayNow transfer and select an action below:"

    admin_messages = []
    for admin_id in ADMIN_CHAT_IDS:
        try:
            sent_msg = await context.bot.send_photo(
                chat_id=admin_id,
                photo=photo_file_id,
                caption=admin_text,
                reply_markup=admin_buttons,
                parse_mode="Markdown"
            )
            admin_messages.append({"chat_id": admin_id, "message_id": sent_msg.message_id})
        except Exception as e:
            logging.error(f"Failed to forward photo to admin/group {admin_id}: {e}")

    context.bot_data[f"receipt_{customer_chat_id}"] = {
        "messages": admin_messages,
        "base_caption": base_caption,
        "processed": False
    }

    await update.message.reply_text(
        "✅ **Payment Receipt Received!**\n\n"
        "We are verifying your transfer. You will receive an instant confirmation message here once verified.\n\n"
        "Feel free to contact @Papapepprotide for further enquiry.\n"
        "Have a great day ahead! 👋"
    )

async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    data = query.data
    admin_user = query.from_user
    admin_handle = f"@{admin_user.username}" if admin_user.username else admin_user.full_name

    if data.startswith("admin_timeout_ack_"):
        await query.answer("Acknowledged.")
        await query.edit_message_text(
            text=f"{query.message.text}\n\n❌ **MARKED AS UNPAID / TIMED OUT BY {admin_handle}**",
            reply_markup=None
        )
        return

    action, target_chat_id_str = data.split("_", 1)
    target_chat_id = int(target_chat_id_str)

    receipt_key = f"receipt_{target_chat_id}"
    receipt_data = context.bot_data.get(receipt_key)

    if not receipt_data or receipt_data.get("processed"):
        await query.answer("⚠️ Action already completed by another admin!", show_alert=True)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    receipt_data["processed"] = True
    await query.answer("Processing action...")

    admin_messages = receipt_data.get("messages", [])
    base_caption = receipt_data.get("base_caption", query.message.caption or "")

    if action == "confirm":
        status_text = f"✅ **STATUS: PAYMENT CONFIRMED BY {admin_handle}**"
        final_caption = f"{base_caption}\n\n{status_text}"

        for msg_info in admin_messages:
            try:
                await context.bot.edit_message_caption(
                    chat_id=msg_info["chat_id"],
                    message_id=msg_info["message_id"],
                    caption=final_caption,
                    reply_markup=None,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Failed to edit admin message {msg_info}: {e}")

        confirm_text = (
            "🎉 **Payment Confirmed!**\n\n"
            "Your order is now processing and will be delivered within 3 to 5 working days 🚚.\n\n"
            "Thank you for shopping with us!"
        )
        try:
            await context.bot.send_message(
                chat_id=target_chat_id,
                text=confirm_text,
                parse_mode="Markdown"
            )
            await context.bot.send_message(
                chat_id=target_chat_id,
                text="🛍️ Would you like to place another order?",
                reply_markup=get_restart_keyboard()
            )
        except Exception as e:
            logging.error(f"Failed to send confirmation message to customer {target_chat_id}: {e}")

    elif action == "decline":
        status_text = f"❌ **STATUS: PAYMENT NOT RECEIVED (DECLINED BY {admin_handle})**"
        final_caption = f"{base_caption}\n\n{status_text}"

        for msg_info in admin_messages:
            try:
                await context.bot.edit_message_caption(
                    chat_id=msg_info["chat_id"],
                    message_id=msg_info["message_id"],
                    caption=final_caption,
                    reply_markup=None,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Failed to edit admin message {msg_info}: {e}")

        decline_text = (
            "⚠️ **PAYMENT NOT RECEIVED** ⚠️\n\n"
            "We were unable to locate your payment in our system.\n"
            "Please double-check your bank transfer details or transaction reference.\n\n"
            "If you believe this is an error, please reach out directly to @Papapepprotide."
        )

        try:
            await context.bot.send_message(
                chat_id=target_chat_id,
                text=decline_text,
                parse_mode="Markdown"
            )
            await context.bot.send_message(
                chat_id=target_chat_id,
                text="🔄 Would you like to try making a new order?",
                reply_markup=get_restart_keyboard()
            )
        except Exception as e:
            logging.error(f"Failed to send decline message to customer {target_chat_id}: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'payment_job' in context.user_data:
        context.user_data['payment_job'].schedule_removal()
        del context.user_data['payment_job']
    await update.message.reply_text(
        "Order cancelled.",
        reply_markup=get_restart_keyboard()
    )
    return ConversationHandler.END

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("groupid", get_group_id))

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(start_new_order_callback, pattern="^restart_bot_session$")
        ],
        states={
            SHOPPING: [CallbackQueryHandler(handle_catalog_click)],
            WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
            WAITING_FOR_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone)],
            WAITING_FOR_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_address)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_receipt_photo))
    app.add_handler(CallbackQueryHandler(handle_admin_actions, pattern="^(confirm_|decline_|admin_timeout_ack_)"))
    app.add_handler(CallbackQueryHandler(start_new_order_callback, pattern="^restart_bot_session$"))

    print("Protide Peptides bot is running...")
    app.run_polling()
