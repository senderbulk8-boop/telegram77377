import os, re, html, time, io
import requests
import pikepdf

BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST_CHANNEL = os.environ["DEST_CHANNEL"]
FEED_URL = os.environ["FEED_URL"]
FOLLOW_LINE = os.environ.get("FOLLOW_LINE", "📢 Follow @topgkguru")
LAST_FILE = "last.txt"

# Remove any kinds of links from text
URL_RE = re.compile(r"""(?ix)\b(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)\b""")

# Detect truncated title endings like "[...]" or "..." or "…"
TRUNC_END_RE = re.compile(r"""(?ix)
(\s*\[\s*\.\.\.\s*\]\s*$)|
(\s*\[\s*…\s*\]\s*$)|
(\s*…\s*$)|
(\s*\.\.\.\s*$)
""")

def tg_send_text(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": DEST_CHANNEL,
        "text": text[:3900],
        "disable_web_page_preview": True
    }, timeout=60)
    r.raise_for_status()

def tg_send_photo_bytes(photo_bytes: bytes, caption: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    files = {"photo": ("image.jpg", photo_bytes)}
    data = {"chat_id": DEST_CHANNEL, "caption": caption[:900]}
    r = requests.post(url, data=data, files=files, timeout=180)
    r.raise_for_status()

def tg_send_document_bytes(doc_bytes: bytes, filename: str, caption: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    files = {"document": (filename, doc_bytes, "application/pdf")}
    data = {"chat_id": DEST_CHANNEL, "caption": caption[:900]}
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
    s = URL_RE.sub("", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\[\s*\]", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def normalize(s: str) -> str:
    s = TRUNC_END_RE.sub("", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def remove_prefixes(s: str) -> str:
    # remove [Photo] / [Media] prefix if exists
    return re.sub(r"^\[(?:Photo|Media)\]\s*", "", s, flags=re.I).strip()

def sanitize_pdf_remove_links(pdf_bytes: bytes) -> bytes:
    """
    Remove clickable link annotations and URI/GoTo actions.
    Does NOT remove URL text printed inside pages.
    """
    src = pikepdf.Pdf.open(io.BytesIO(pdf_bytes))

    for page in src.pages:
        annots = page.get("/Annots", None)
        if not annots:
            continue

        new_annots = []
        for a in annots:
            try:
                obj = a.get_object()
            except Exception:
                continue

            # Remove actions/dests if present
            if "/A" in obj:
                del obj["/A"]
            if "/AA" in obj:
                del obj["/AA"]
            if "/Dest" in obj:
                del obj["/Dest"]

            subtype = obj.get("/Subtype", None)

            # Drop Link annotations completely (these create clickable areas)
            if subtype == pikepdf.Name("/Link"):
                continue

            new_annots.append(a)

        if new_annots:
            page["/Annots"] = pikepdf.Array(new_annots)
        else:
            if "/Annots" in page:
                del page["/Annots"]

    out = io.BytesIO()
    src.save(out)
    return out.getvalue()

def parse_item(item_xml: str):
    def pick(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", item_xml, flags=re.S)
        return (m.group(1).strip() if m else "")

    title_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("title"))
    desc_raw = re.sub(r"<!\[CDATA\[|\]\]>", "", pick("description"))
    link = pick("link").strip()
    guid = (pick("guid").strip() or link)

    # enclosure for image/pdf
    enc_url = None
    enc_type = None
    m_enc = re.search(r'enclosure[^>]+url="([^"]+)"[^>]+type="([^"]+)"', item_xml, flags=re.I)
    if m_enc:
        enc_url = m_enc.group(1)
        enc_type = m_enc.group(2)

    title = remove_prefixes(strip_tags(title_raw))
    desc = strip_tags(desc_raw)
    desc = re.sub(r"^\[Photo\]\s*", "", desc).strip()

    # remove links from both
    title = remove_links(title)
    desc = remove_links(desc)

    # DEDUPE for your feed (title truncated with [...])
    title_is_truncated = bool(TRUNC_END_RE.search(title_raw)) or bool(TRUNC_END_RE.search(title))
    t_norm = normalize(title)

    first_line = ""
    for ln in desc.splitlines():
        if ln.strip():
            first_line = ln.strip()
            break
    f_norm = normalize(first_line)
    d_norm = normalize(desc)

    if title_is_truncated:
        combined = desc
    else:
        if t_norm and f_norm and (f_norm == t_norm or f_norm.startswith(t_norm) or t_norm.startswith(f_norm)):
            combined = desc
        elif t_norm and d_norm and (d_norm == t_norm or d_norm.startswith(t_norm)):
            combined = desc
        else:
            combined = f"{title}\n\n{desc}".strip() if title and desc else (title or desc)

    combined = re.sub(r"\n{3,}", "\n\n", combined).strip()

    return {
        "guid": guid,
        "text": combined,
        "enclosure_url": enc_url,
        "enclosure_type": enc_type
    }

def parse_all_items(xml: str):
    items = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, flags=re.S):
        items.append(parse_item(m.group(1)))
    return items

def main():
    last_guid = read_last()

    xml = requests.get(FEED_URL, timeout=90).text
    items = parse_all_items(xml)
    if not items:
        print("No items found")
        return

    # RSS is newest-first. Collect all items until we hit last_guid.
    new_items = []
    for it in items:
        if last_guid and it["guid"] == last_guid:
            break
        new_items.append(it)

    if not new_items:
        print("No new posts")
        return

    # Send oldest -> newest (so order stays correct)
    new_items.reverse()

    for it in new_items:
        out = f"🔥 New Update\n\n{it['text']}\n\n━━━━━━━━━━━━━━\n{FOLLOW_LINE}".strip()
        out = re.sub(r"\n{3,}", "\n\n", out).strip()

        ctype = (it["enclosure_type"] or "").lower()

        if it["enclosure_url"] and ctype.startswith("image/"):
            img = requests.get(it["enclosure_url"], timeout=180)
            img.raise_for_status()
            tg_send_photo_bytes(img.content, out)

        elif it["enclosure_url"] and ctype == "application/pdf":
            pdf = requests.get(it["enclosure_url"], timeout=300)
            pdf.raise_for_status()
            safe_pdf = sanitize_pdf_remove_links(pdf.content)
            tg_send_document_bytes(safe_pdf, "document.pdf", out)

        else:
            tg_send_text(out)

        time.sleep(1)  # avoid rate-limits

    # Save newest guid as last processed
    write_last(new_items[-1]["guid"])
    print("Posted", len(new_items), "items. Last:", new_items[-1]["guid"])

if __name__ == "__main__":
    main()
