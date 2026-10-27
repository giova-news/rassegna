import os, json, datetime, feedparser, trafilatura, anthropic
from openai import OpenAI
from email.utils import format_datetime

FEEDS = {
  "es": ["https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
         "https://www.lavanguardia.com/rss/home.xml",
         "https://www.clarin.com/rss/lo-ultimo/"],
  "fr": ["https://www.lemonde.fr/rss/une.xml",
         "https://www.liberation.fr/arc/outboundfeeds/rss/?outputType=xml"],
  "en": ["https://www.theguardian.com/uk/rss",
         "https://feeds.npr.org/1014/rss.xml"],
  "de": ["https://www.nachrichtenleicht.de/nachrichtenleicht-nachrichten-100.rss",
         "https://www.spiegel.de/schlagzeilen/index.rss"],
}
VOCI = {"es": "nova", "fr": "shimmer", "en": "alloy", "de": "onyx", "it": "echo"}
BASE_URL = os.environ.get("BASE_URL", "https://giova-news.github.io/rassegna")
OUT = "docs"
claude = anthropic.Anthropic()
oai = OpenAI()

def raccogli():
    items = []
    for lang, urls in FEEDS.items():
        for u in urls:
            for e in feedparser.parse(u).entries[:15]:
                items.append({"lang": lang, "title": e.title, "link": e.link,
                              "summary": e.get("summary", "")[:300]})
    return items

def carica_voti():
    try:
        return json.load(open("feedback.json"))[-30:]
    except Exception:
        return []

def scegli(items, voti):
    prompt = f"""Sei il curatore di una rassegna stampa personale per Giovanni, italiano,
appassionato di economia. Scegli 3 articoli, in lingue diverse, tra quelli sotto.
Preferisci: politica interna, economia, questioni sociali, retroscena, notizie poco
coperte dalla stampa italiana. Evita i grandi temi internazionali.
Voti passati di Giovanni (impara i suoi gusti): {json.dumps(voti, ensure_ascii=False)}
Articoli: {json.dumps(items, ensure_ascii=False)}
Rispondi SOLO con JSON: [{{"link":..., "lang":..., "title":..., "pitch_it": "una frase in italiano"}}]"""
    r = claude.messages.create(model="claude-sonnet-5-5", max_tokens=1500,
                               messages=[{"role": "user", "content": prompt}])
    t = r.content[0].text
    return json.loads(t[t.find("["):t.rfind("]") + 1])

def testo_articolo(a):
    html = trafilatura.fetch_url(a["link"])
    testo = trafilatura.extract(html) if html else None
    if a["lang"] == "de":
        istr = "Riscrivi questo articolo in tedesco semplicissimo (livello A2): frasi brevi, parole comuni, massimo 250 parole."
    elif not testo or len(testo) < 800:
        istr = "Scrivi un riassunto approfondito (400 parole) nella lingua originale dell'articolo."
    else:
        return testo[:4000]
    r = claude.messages.create(model="claude-sonnet-5-5", max_tokens=1500,
        messages=[{"role": "user", "content": f"{istr}\n\nTitolo: {a['title']}\n\n{testo or a['title']}"}])
    return r.content[0].text

def voce(testo, lang, path):
    speed = 0.85 if lang == "de" else 1.0
    with oai.audio.speech.with_streaming_response.create(
            model="tts-1", voice=VOCI[lang], input=testo[:4000], speed=speed) as r:
        r.stream_to_file(path)

def main():
    os.makedirs(OUT, exist_ok=True)
    oggi = datetime.date.today().isoformat()
    scelti = scegli(raccogli(), carica_voti())
    episodi = []
    intro = "Buongiorno Giovanni. Ecco le proposte di oggi. " + " ".join(
        f"Numero {i+1}: {a['pitch_it']}" for i, a in enumerate(scelti))
    voce(intro, "it", f"{OUT}/{oggi}-0.mp3")
    episodi.append((f"{oggi} – Le proposte di oggi", f"{oggi}-0.mp3"))
    for i, a in enumerate(scelti, 1):
        voce(a["title"] + ". " + testo_articolo(a), a["lang"], f"{OUT}/{oggi}-{i}.mp3")
        episodi.append((f"{oggi} – {i}. [{a['lang'].upper()}] {a['title']}", f"{oggi}-{i}.mp3"))
    json.dump(scelti, open(f"{OUT}/{oggi}.json", "w"), ensure_ascii=False)
    scrivi_feed(episodi)

def scrivi_feed(nuovi):
    db = "episodi.json"
    tutti = json.load(open(db)) if os.path.exists(db) else []
    ora = datetime.datetime.now(datetime.timezone.utc)
    for k, (t, f) in enumerate(nuovi):
        tutti.insert(k, {"title": t, "file": f,
                         "date": format_datetime(ora - datetime.timedelta(minutes=k))})
    tutti = tutti[:40]
    json.dump(tutti, open(db, "w"), ensure_ascii=False)
    items = "".join(f"<item><title>{e['title']}</title><guid>{e['file']}</guid>"
        f"<pubDate>{e['date']}</pubDate><enclosure url='{BASE_URL}/{e['file']}' type='audio/mpeg'/></item>"
        for e in tutti)
    xml = ("<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel>"
           f"<title>Rassegna poliglotta</title><link>{BASE_URL}</link>"
           f"<description>Rassegna personale</description>{items}</channel></rss>")
    open(f"{OUT}/feed.xml", "w").write(xml)

if __name__ == "__main__":
    main()
