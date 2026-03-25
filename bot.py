import os, re, html, time, io
import requests
import pikepdf

BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNELS = os.environ["DEST_CHANNEL"]  # comma-separated: @ch1,@ch2 or -100...
FEED_URL = os.environ["FEED_URL"]
FOLLOW_LINE = os.environ.get("FOLLOW_LINE", "📢 Follow @topgkguru")
LAST_FILE = "last.txt"

# Targeted link removal regex
# This only targets the specific links provided by the user
TARGETED_LINKS_RE = re.compile(r"""(?ix)\b(https?://t\.me/ShikshaVibhag\S*|https?://whatsapp\.com/channel\S*|https?://govtexamtak\.in\S*)\b""")

# Detect truncated title endings like "[...]" or "..." or "…"
TRUNC_END_RE = re.compile(r"""(?ix)
(\s*\[\s*\.\.\.\s*\]\s*$)|
(\s*\[\s*…\s*\]\s*$)|
(\s*…\s*$)|
(\s*\.\.\.\s*$)
""")

def tg_send_text(text: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": channel,
        "text": text[:3900],
        "disable_web_page_preview": True
    }, timeout=60)
    r.raise_for_status()

def tg_send_photo_bytes(photo_bytes: bytes, caption: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {"photo": ("image.jpg", photo_bytes)}
    data = {"chat_id": channel, "caption": caption[:900]}
    r = requests.post(url, data=data, files=files, timeout=180)
    r.raise_for_status()

def tg_send_document_bytes(doc_bytes: bytes, filename: str, caption: str, channel: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    files = {"document": (filename, doc_bytes, "application/pdf")}
    data = {"chat_id": channel, "caption": caption[:900]}
    r = requests.post(url, data=data, files=files, timeout=300)
    r.raise_for_status()

def read_last():
    if os.path.exists(LAST_FILE):
        return open(LAST_FILE, "r", encoding="utf-8").read().strip()
    return ""

def write_last(val: str):
    open(LAST_FILE, "w", encoding="utf-8").write(val)

def strip_tags(s: str) -> str:
    s = html.unescape(s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<.*?>", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def remove_links(s: str) -> str:
    # Only removes the specific requested links
    s = TARGETED_LINKS_RE.sub("", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[\s*\]", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def sanitize_pdf_remove_links(pdf_bytes: bytes) -> bytes:
    try:
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                if "/Annots" in page:
                    del page["/Annots"]
            out = io.BytesIO()
            pdf.save(out)
            return out.getvalue()
    except:
        return pdf_bytes

def main():
    channels = [c.strip() for c in DEST_CHANNELS.split(",") if c.strip()]
    
    # Fetch RSS feed logic (assumed based on context)
    r = requests.get(FEED_URL, timeout=60)
    # items = ... (parsing logic usually goes here)
    
    # Placeholder for logic to filter items
    new_items = [] 
    # for it in items:
    #     # SKIP ADS
    #     if "#ADS" in it['text'].upper():
    #         continue
    #     ...
