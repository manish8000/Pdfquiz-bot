import os
import json
import threading
from flask import Flask
from pypdf import PdfReader
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai

# ---- API KEYS ----
TELEGRAM_BOT_TOKEN = "अपनी_TELEGRAM_BOT_TOKEN_यहाँ_डाले"
GEMINI_API_KEY = "अपनी_GEMINI_API_KEY_यहाँ_डाले"

client = genai.Client(api_key=GEMINI_API_KEY)

# Web Server Render को एक्टिव रखने के लिए
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Bot is Alive!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_web.run(host='0.0.0.0', port=port)

# Telegram Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("नमस्ते! मुझे कोई भी PDF फाइल भेजें, मैं उसमें से Quiz/MCQ तैयार कर दूंगा।")

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

        await status_msg.edit_text("🤖 AI क्विज़ तैयार कर रहा है...")

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

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )

        clean_json = response.text.strip().replace("```json", "").replace("```", "")
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
    # वेब सर्वर को बैकग्राउंड में चालू करें
    threading.Thread(target=run_flask, daemon=True).start()
    
    # टेलीग्राम बॉट चलाएं
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
