import os
import re
import asyncio
import logging
import sqlite3
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
from telegram import Update, Poll
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    PollAnswerHandler,
    ContextTypes,
    filters
)

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ==================== CONFIGURATION ====================
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"  # BotFather se mila token yahan daalein
CREATOR_ID = 123456789                       # Apni Numeric Telegram ID yahan daalein

# Global Data Stores
active_polls = {}
scores = {}

# ==================== DATABASE SETUP ====================
def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY
        )
    ''')
    conn.commit()
    conn.close()

def add_chat(chat_id: int):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO chats (chat_id) VALUES (?)', (chat_id,))
    conn.commit()
    conn.close()

def get_all_chats():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM chats')
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

init_db()

# ==================== PARSER FUNCTIONS ====================
def parse_quiz_text(text: str):
    quizzes = []
    blocks = re.split(r'\n(?=Q\d*:|Question\d*:|Q:)', text, flags=re.IGNORECASE)
    
    for block in blocks:
        if not block.strip():
            continue
            
        q_match = re.search(r'(?:Q\d*:|Question\d*:|Q:)?\s*(.*?)(?=\n[A-D]\))', block, re.DOTALL | re.IGNORECASE)
        if not q_match:
            continue
        question = q_match.group(1).strip()
        
        options = re.findall(r'[A-D]\)\s*(.*)', block)
        ans_match = re.search(r'(?:Answer|Ans|Correct):\s*([A-D])', block, re.IGNORECASE)
        
        if question and len(options) >= 2 and ans_match:
            ans_char = ans_match.group(1).upper()
            correct_id = ord(ans_char) - ord('A')
            
            if correct_id < len(options):
                quizzes.append({
                    "question": question[:300],
                    "options": [opt[:100] for opt in options[:10]],
                    "correct_id": correct_id
                })
    return quizzes

def extract_from_pdf(file_path: str):
    reader = PdfReader(file_path)
    full_text = "".join([page.extract_text() or "" for page in reader.pages])
    return parse_quiz_text(full_text)

def extract_from_html(file_path: str):
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    return parse_quiz_text(soup.get_text(separator='\n'))

# ==================== BOT HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    add_chat(chat_id)
    
    msg = (
        "👋 **Welcome to Premium Quiz Bot!**\n\n"
        "• Anyone can use this bot in private chat or groups for FREE.\n"
        "• Upload any **PDF** or **HTML** file to start the quiz automatically.\n\n"
        "📌 **File Format Example:**\n"
        "Q1: What is the capital of India?\n"
        "A) Mumbai\n"
        "B) Delhi\n"
        "C) Kolkata\n"
        "D) Chennai\n"
        "Answer: B\n\n"
        "📊 Type `/score` anytime to view the leaderboard."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    add_chat(chat_id)
    
    doc = update.message.document
    file_name = doc.file_name.lower()
    
    if not (file_name.endswith('.pdf') or file_name.endswith('.html') or file_name.endswith('.htm')):
        await update.message.reply_text("❌ Kripya sirf PDF ya HTML file hi upload karein.")
        return

    status_msg = await update.message.reply_text("⏳ File process ho rahi hai, kripya intezar karein...")
    
    telegram_file = await context.bot.get_file(doc.file_id)
    local_path = f"temp_{doc.file_id}_{file_name}"
    await telegram_file.download_to_drive(local_path)
    
    try:
        if file_name.endswith('.pdf'):
            quizzes = extract_from_pdf(local_path)
        else:
            quizzes = extract_from_html(local_path)
            
        if not quizzes:
            await status_msg.edit_text("❌ Question parse nahi ho paye. Kripya formatting check karein.")
            return

        scores[chat_id] = {}
        await status_msg.edit_text(f"✅ Total {len(quizzes)} Quizzes mil gaye! Quiz 5 seconds me start ho rahi hai...")
        await asyncio.sleep(5)

        QUESTION_TIMER = 15  # Har question ke liye seconds (Default: 15 seconds)
        
        for idx, item in enumerate(quizzes, start=1):
            poll_message = await context.bot.send_poll(
                chat_id=chat_id,
                question=f"[{idx}/{len(quizzes)}] {item['question']}",
                options=item["options"],
                type=Poll.QUIZ,
                correct_option_id=item["correct_id"],
                is_anonymous=False,
                open_period=QUESTION_TIMER
            )
            
            active_polls[poll_message.poll.id] = {
                "correct_id": item["correct_id"],
                "chat_id": chat_id
            }
            
            await asyncio.sleep(QUESTION_TIMER + 2)
            
        await context.bot.send_message(
            chat_id=chat_id, 
            text="🎉 **Quiz Khatam Ho Gayi Hai!**\nLeaderboard dekhne ke liye `/score` type karein.",
            parse_mode="Markdown"
        )
            
    except Exception as e:
        logging.error(f"Error processing file: {e}")
        await status_msg.edit_text("❌ File processing me koi unexpected error aayi.")
    finally:
        if os.path.exists(local_path):
            os.remove(local_path)

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_id = answer.poll_id
    
    if poll_id not in active_polls:
        return
        
    poll_data = active_polls[poll_id]
    user = answer.user
    user_id = user.id
    user_name = user.full_name
    chat_id = poll_data["chat_id"]
    
    selected_option = answer.option_ids[0] if answer.option_ids else None
    
    if selected_option == poll_data["correct_id"]:
        if chat_id not in scores:
            scores[chat_id] = {}
        if user_id not in scores[chat_id]:
            scores[chat_id][user_id] = {"name": user_name, "score": 0}
            
        scores[chat_id][user_id]["score"] += 1

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id not in scores or not scores[chat_id]:
        await update.message.reply_text("📊 Abhi tak kisi ne koi sahi answer nahi diya hai.")
        return
        
    sorted_scores = sorted(scores[chat_id].values(), key=lambda x: x["score"], reverse=True)
    
    lb_text = "🏆 **QUIZ LEADERBOARD** 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, user_data in enumerate(sorted_scores):
        rank = medals[i] if i < 3 else f"#{i+1}"
        lb_text += f"{rank} **{user_data['name']}** — {user_data['score']} Points\n"
        
    await update.message.reply_text(lb_text, parse_mode="Markdown")

# ==================== CREATOR ONLY BROADCAST ====================

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != CREATOR_ID:
        await update.message.reply_text("❌ Sirf Bot Creator hi broadcast kar sakta hai!")
        return
        
    if not context.args:
        await update.message.reply_text("⚠️ Message missing!\nUsage: `/broadcast Aapka message yahan`", parse_mode="Markdown")
        return

    message_to_send = " ".join(context.args)
    all_chats = get_all_chats()
    
    success = 0
    failed = 0

    await update.message.reply_text(f"📢 Broadcast start ho raha hai... Target: {len(all_chats)} chats")

    for cid in all_chats:
        try:
            await context.bot.send_message(chat_id=cid, text=f"📢 **Announcement:**\n\n{message_to_send}", parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.1)  # Rate limiting control
        except Exception:
            failed += 1

    await update.message.reply_text(f"✅ Broadcast Complete!\n\nSuccess: {success}\nFailed/Blocked: {failed}")

# ==================== MAIN EXECUTION ====================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("score", show_leaderboard))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(PollAnswerHandler(handle_poll_answer))

    print("🚀 Quiz Bot successfully start ho gaya hai...")
    app.run_polling()

if __name__ == "__main__":
    main()
  
