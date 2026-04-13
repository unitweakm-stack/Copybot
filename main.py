import os
import io
import re
import json
import asyncio
import urllib.parse
import urllib.request

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, MessageHandler, ContextTypes, filters

OCR_API_URL = "https://api.ocr.space/parse/image"
DEFAULT_LANG = os.getenv("DEFAULT_LANG", "tur").strip().lower() or "tur"


def clean_text(s: str) -> str:
    s = s.replace("\r\n", "\n").strip()
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def ocr_space_request(image_bytes: bytes, filename: str) -> str:
    api_key = os.getenv("OCR_SPACE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OCR_SPACE_API_KEY yo‘q. Env/Secrets ga qo‘ying.")

    boundary = "----WEAKOCRBOUNDARY7MA4YWxkTrZu0gW"
    fields = {
        "apikey": api_key,
        "language": DEFAULT_LANG,
        "isOverlayRequired": "false",
        "OCREngine": os.getenv("OCR_ENGINE", "2"),
        "scale": os.getenv("OCR_SCALE", "true"),
        "detectOrientation": os.getenv("OCR_DETECT_ORIENTATION", "true"),
    }

    body = io.BytesIO()
    for k, v in fields.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        body.write(str(v).encode())
        body.write(b"\r\n")

    body.write(f"--{boundary}\r\n".encode())
    body.write(
        (
            f'Content-Disposition: form-data; name="file"; filename="{urllib.parse.quote(filename)}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
    )
    body.write(image_bytes)
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())

    data = body.getvalue()
    req = urllib.request.Request(OCR_API_URL, data=data, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Content-Length", str(len(data)))

    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    payload = json.loads(raw)

    if payload.get("IsErroredOnProcessing"):
        msg = payload.get("ErrorMessage") or payload.get("ErrorDetails") or "OCR.Space xato"
        if isinstance(msg, list):
            msg = "; ".join(str(x) for x in msg)
        raise RuntimeError(str(msg))

    parsed = payload.get("ParsedResults") or []
    if not parsed:
        return ""

    return (parsed[0].get("ParsedText") or "").strip()


async def ocr_bytes_async(image_bytes: bytes, filename: str) -> str:
    return await asyncio.to_thread(ocr_space_request, image_bytes, filename)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(action=ChatAction.TYPING)

    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    content = await tg_file.download_as_bytearray()

    try:
        text = clean_text(await ocr_bytes_async(bytes(content), "photo.jpg"))
    except Exception as e:
        await update.message.reply_text(f"OCR xato: {e}")
        return

    if not text:
        await update.message.reply_text("Matn topilmadi. Rasm tiniqroq bo‘lsin.")
        return

    safe = html_escape(text)

    if len(safe) > 3800:
        safe = safe[:3800] + "\n...(qisqartirildi)"

    await update.message.reply_text(f"<pre>{safe}</pre>", parse_mode="HTML")


def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN yo‘q. Env/Secrets ga BOT_TOKEN qo‘ying.")

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()