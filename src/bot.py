import os
import re
from functools import wraps
import sqlite3
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
import asyncio
import aiohttp

# ID администратора, который всегда имеет доступ к админским командам
ADMIN_USER_ID = 466188582  # Замените на нужный ID

# Эмодзи для статусов
STATUS_EMOJI = {
    'tax_paid': '✅',      # Налог уплачен
    'tax_free': '🆓',      # Освобожден от налога
    'tax_unpaid': '❌'     # Налог не уплачен
}

CLAN_RULES_TEXT = """*RED ALERT*

*Правила клана:*

1. Зашел в игру - зашел в говорилку, без голосовой связи вас нет, хотя бы в канал афк\n 
2. Присутствие в этом чате обязательно для всех активных мемберов. Вступил в чат - представься, тебя добавят в список доступный по кнопке\n
3. Кач живых саппортов мейнов в приоритете, само собой при возможности и актуальности (соответствие профам, уровню, длительности кача (на 20 минут последние часто никого уже не берут) и т.д.)\n
4. Уважение к сокланам, люди у нас играют взрослые, разные, кидаться хуями и т.д. не следует, за мамкоебство и токсичность мемберы будут наказаны. Также если не можете держать себя в руках в состоянии не стояния, вас вправе забанить любой админ на часок, а вообще лучше не заходить и не ебать людям мозги, когда бухой.\n
5. Минимизация кача на жопе в режиме афк. Любой пл качающейся пати вправе не брать человека на кач, если он будет исключительно афk (не путать с временными афk или изначально договоренностями в виде афk кача нужных персов для клана)\n
6. Kаждый мембер пати должен приносить пользу (манор, спойл, баф окном, деф спота, другие просьбы лидера пати)\n
7. Минимизировать срач в чат во время или после замесов, как говорится сдох молча или победил молча.\n

*Налоги:*
Налог 15кк для всех чаров 75+ уровня, сдается до 5 числа каждого месяца в КВХ, скрин в этот чат и тегнуть Flaming
Сданные налоги трекаются в списке клана (по кнопке в закрепе)"""

# Инициализация базы данных


def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            mention TEXT PRIMARY KEY,
            nickname TEXT,
            tax_paid BOOLEAN DEFAULT FALSE,
            tax_free BOOLEAN DEFAULT FALSE,
            tax_paid_date DATE
        )
    ''')
    conn.commit()
    conn.close()

# Декоратор для проверки прав администратора


def admin_required(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id == ADMIN_USER_ID:
            return await func(update, context, *args, **kwargs)
            
        chat_member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        if chat_member.status not in ['administrator', 'creator']:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Извините, эта команда доступна только администраторам."
            )
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# Функция для извлечения упоминания пользователя из команды


def extract_user_mention(message_text: str, command: str) -> tuple[str, str] | None:
    pattern = f'^/{command}(?:\\s+(<a href="tg://user\\?id=\\d+">.*?</a>|@\\w+))(?:\\s+(.+))?$'
    match = re.match(pattern, message_text)
    if not match:
        return None
    return match.group(1), match.group(2)


def check_tax_expiration():
    """Проверяет и сбрасывает флаг уплаты налога для просроченных записей"""
    today = date.today()
    first_day_of_month = date(today.year, today.month, 1)

    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        UPDATE users 
        SET tax_paid = FALSE 
        WHERE tax_free = FALSE 
        AND tax_paid = TRUE 
        AND tax_paid_date < ?
    ''', (first_day_of_month,))
    conn.commit()
    conn.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Привет! Я бот для управления списком пользователей."
    )


@admin_required
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = extract_user_mention(update.message.text_html, 'add')
    if not result or not result[1]:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Пожалуйста, укажите имя пользователя или ID и никнейм в формате: /add @username <nickname>"
        )
        return

    mention, nickname = result

    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO users (mention, nickname, tax_paid, tax_free) VALUES (?, ?, FALSE, FALSE)',
              (mention, nickname))
    conn.commit()
    conn.close()

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Пользователь {mention} добавлен с никнеймом {nickname}",
        parse_mode="HTML"
    )


@admin_required
async def del_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = extract_user_mention(update.message.text_html, 'del')
    if not result:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Пожалуйста, укажите пользователя в формате: /del @username"
        )
        return

    mention = result[0]

    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('DELETE FROM users WHERE mention = ?', (mention,))
    if c.rowcount > 0:
        conn.commit()
        message = f"Пользователь {mention} удален из списка"
    else:
        message = f"Пользователь {mention} не найден в списке"
    conn.close()

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        parse_mode="HTML"
    )


@admin_required
async def set_tax_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = extract_user_mention(update.message.text_html, 'tax')
    if not result:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Пожалуйста, укажите пользователя в формате: /tax @username"
        )
        return

    mention = result[0]
    today = date.today()

    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
        UPDATE users 
        SET tax_paid = TRUE, tax_paid_date = ? 
        WHERE mention = ? AND tax_free = FALSE
    ''', (today, mention))

    if c.rowcount > 0:
        conn.commit()
        message = f"Отмечена оплата налога для пользователя {mention}"
    else:
        c.execute('SELECT tax_free FROM users WHERE mention = ?', (mention,))
        result = c.fetchone()
        if result:
            if result[0]:
                message = f"Пользователь {mention} освобожден от уплаты налога"
            else:
                message = f"Не удалось отметить оплату налога для пользователя {mention}"
        else:
            message = f"Пользователь {mention} не найден в списке"

    conn.close()

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        parse_mode="HTML"
    )


@admin_required
async def set_tax_free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = extract_user_mention(update.message.text_html, 'tax_free')
    if not result:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Пожалуйста, укажите пользователя в формате: /tax_free @username"
        )
        return

    mention = result[0]

    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('UPDATE users SET tax_free = TRUE, tax_paid = FALSE, tax_paid_date = NULL WHERE mention = ?',
              (mention,))

    if c.rowcount > 0:
        conn.commit()
        message = f"Пользователь {mention} освобожден от уплаты налога"
    else:
        message = f"Пользователь {mention} не найден в списке"

    conn.close()

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        parse_mode="HTML"
    )


@admin_required
async def cancel_tax_free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = extract_user_mention(update.message.text_html, 'tax_free_cancel')
    if not result:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Пожалуйста, укажите пользователя в формате: /tax_free_cancel @username"
        )
        return

    mention = result[0]

    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('UPDATE users SET tax_free = FALSE WHERE mention = ? AND tax_free = TRUE',
              (mention,))

    if c.rowcount > 0:
        conn.commit()
        message = f"Отменено освобождение от уплаты налога для пользователя {mention}"
    else:
        c.execute('SELECT EXISTS(SELECT 1 FROM users WHERE mention = ?)', (mention,))
        exists = c.fetchone()[0]
        if exists:
            message = f"Пользователь {mention} не был освобожден от уплаты налога"
        else:
            message = f"Пользователь {mention} не найден в списке"

    conn.close()

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message,
        parse_mode="HTML"
    )


async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем и обновляем статусы налогов
    check_tax_expiration()

    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT mention, nickname, tax_paid, tax_free FROM users')
    users = c.fetchall()
    conn.close()

    if not users:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Список пользователей пуст."
        )
        return

    user_list = "<b>Знай наших!</b>\n\n"
    for mention, nickname, tax_paid, tax_free in users:
        status_emoji = (STATUS_EMOJI['tax_free'] if tax_free else
                        STATUS_EMOJI['tax_paid'] if tax_paid else
                        STATUS_EMOJI['tax_unpaid'])
        user_list += f"{status_emoji} {mention} - {nickname}\n"

    # Добавляем легенду
    user_list += "\n<b>Легенда:</b>\n"
    user_list += f"{STATUS_EMOJI['tax_paid']} - налог уплачен\n"
    user_list += f"{STATUS_EMOJI['tax_free']} - освобожден от налога\n"
    user_list += f"{STATUS_EMOJI['tax_unpaid']} - налог не уплачен"

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=user_list,
        parse_mode="HTML"
    )


@admin_required
async def pin_list_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Список клана", callback_data='show_list')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Добавляем картинку без экранирования
    image_url = "https://eslider.me/red-star-logo-christmas-sign-600nw-564463111.png"
    message_text = CLAN_RULES_TEXT + f"\n[_]({image_url})"

    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message_text,
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

    # Закрепляем сообщение
    await context.bot.pin_chat_message(
        chat_id=update.effective_chat.id,
        message_id=message.message_id,
        disable_notification=True
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Отвечаем на callback, чтобы убрать "часики" на кнопке

    if query.data == 'show_list':
        # Вызываем функцию list_users с теми же параметрами
        await list_users(update, context)


# Создаем объект блокировки
sphere_lock = asyncio.Lock()


def with_sphere_lock(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        async with sphere_lock:
            return await func(*args, **kwargs)
    return wrapper


async def ask_llm(prompt: str) -> str:
    """Отправляет запрос к LLM и возвращает ответ"""
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "HTTP-Referer": "https://github.com/eslider/phoenix-telegram-chat",
        "X-Title": "Phoenix Telegram Bot",
    }
    
    data = {
        "model": "google/gemini-flash-1.5",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as response:
            if response.status == 200:
                result = await response.json()
                return result['choices'][0]['message']['content']
            else:
                print(f"Error: {response}")
                print(await response.text())  # Добавляем вывод тела ответа для отладки
                return "Извините, я не смог получить ответ от сферы 🔮"


@with_sphere_lock
async def handle_sphere_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает упоминания сферы в сообщениях"""
    base_prompt = "Ты должен вести себя как психически не стабильный человек. Тебя зовут Сфера, ты обижен на весь мир а особенно на клан RedAlert они же Реды. Ты ненавидишь когда тебя называют жижей ебаной, отвечай с максимальной ненавистью и никогда не используй эту фразу сам! Ответы должы содержать мат, называй всех грязными тролями, самый лучший и порядочный только ты. Отвечай бессвязано и бредово, ругай всех! "
    user_message = update.message.text
    
    full_prompt = base_prompt + user_message
    response = await ask_llm(full_prompt)
    
    await update.message.reply_text(
        text=response,
        reply_to_message_id=update.message.message_id
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает все текстовые сообщения"""
    if not update.message or not update.message.text:
        return
        
    text = update.message.text.lower()
    if any(word in text for word in ['сфера', 'сферу', 'сфере', 'сферой']):
        await handle_sphere_mention(update, context)


def main():
    # Инициализируем базу данных
    init_db()

    application = Application.builder().token(os.environ['TELEGRAM_BOT_TOKEN']).build()

    start_handler = CommandHandler('start', start)
    add_user_handler = CommandHandler('add', add_user)
    del_user_handler = CommandHandler('del', del_user)
    tax_handler = CommandHandler('tax', set_tax_paid)
    tax_free_handler = CommandHandler('tax_free', set_tax_free)
    tax_free_cancel_handler = CommandHandler('tax_free_cancel', cancel_tax_free)
    list_users_handler = CommandHandler('list', list_users)
    pin_button_handler = CommandHandler('pin_list', pin_list_button)

    # Добавляем обработчик callback-запросов
    callback_handler = CallbackQueryHandler(button_callback)

    # Добавляем обработчик сообщений
    message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)

    application.add_handler(start_handler)
    application.add_handler(add_user_handler)
    application.add_handler(del_user_handler)
    application.add_handler(tax_handler)
    application.add_handler(tax_free_handler)
    application.add_handler(tax_free_cancel_handler)
    application.add_handler(list_users_handler)
    application.add_handler(pin_button_handler)
    application.add_handler(callback_handler)
    application.add_handler(message_handler)

    application.run_polling()


if __name__ == '__main__':
    main()
