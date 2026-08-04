import os
import json
import threading
from flask import Flask
from pypdf import PdfReader
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI

# Environment Variables से Keys लेना
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROK_API_KEY = os.environ.get("GROK_API_KEY")

# Grok (xAI) Client Setup
client = OpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1",
)

# Koyeb Health Check Server (Flask)
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Bot is Running Live with Grok on Koyeb!"

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    app_web.run(host='0.0.0.0', port=port)

# Telegram Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("नमस्ते! मुझे कोई भी PDF फाइल भेजें, मैं Grok AI की मदद से उसमें से Quiz/MCQ तैयार कर दूंगा।")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document.file_name.lower().endswith('.pdf'):
        await update.message.reply_text("कृपया केवल PDF फाइल ही भेजें।")
        return

    status_msg = await update.message.reply_text("📄 PDF प्रोसेस हो रही है...")
    file = await context.bot.get_file(document.file_id)
    file_path = f"temp_{document.file_id}.pdf"
    await file.download_to_drive(file_path)

    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages[:5]:
            text += page.extract_text() or ""

        if not text.strip():
            await status_msg.edit_text("PDF से टेक्स्ट नहीं पढ़ा जा सका।")
            os.remove(file_path)
            return

        await status_msg.edit_text("🤖 Grok AI क्विज़ तैयार कर रहा है...")

        prompt = f"""
        Extract 3 multiple choice questions from the following text.
        Return ONLY a JSON array of objects with no markdown formatting.
        Format example:
        [
            {{
                "question": "सवाल यहाँ होगा?",
                "options": ["Option A", "Option B", "Option C", "Option D"],
                "correct_option_id": 0
            }}
        ]

        Text:
        {text[:3000]}
        """

        # Grok AI API Call
        response = client.chat.completions.create(
            model="grok-beta",
            messages=[
                {"role": "system", "content": "You are a helpful quiz generator. Always respond in pure JSON array format."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )

        response_text = response.choices[0].message.content
        clean_json = response_text.strip().replace("```json", "").replace("```", "")
        quiz_data = json.loads(clean_json)

        await status_msg.edit_text("✅ क्विज़ तैयार है!")

        for item in quiz_data:
            await context.bot.send_poll(
                chat_id=update.effective_chat.id,
                question=item["question"],
                options=item["options"],
                type="quiz",
                correct_option_id=int(item["correct_option_id"]),
                is_anonymous=False
            )

    except Exception as e:
        await update.message.reply_text(f"कोई गड़बड़ हुई: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

def main():
    # Flask Server बैकग्राउंड में चालू करें
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Telegram Bot Start करें
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("Bot is running with Grok...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
