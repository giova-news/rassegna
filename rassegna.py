import os, glob, json, datetime, asyncio, feedparser, trafilatura, anthropic, edge_tts
from email.utils import format_datetime

FEEDS = {
  "es": ["https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
         "https://www.lavanguardia.com/rss/home.xml",
         "https://www.clarin.com/rss/lo-ultimo/",
         "https://www.lanacion.com.ar/arc/outboundfeeds/rss/?outputType=xml",
         "https://www.infobae.com/arc/outboundfeeds/rss/",
         "https://www.latercera.com/arc/outboundfeeds/rss/?outputType=xml",
         "https://www.eltiempo.com/rss/colombia.xml"],
  "fr": ["https://www.20minutes.fr/feeds/rss-une.xml",
         "https://www.ouest-france.fr/rss/une",
         "https://www.francetvinfo.fr/titres.rss",
         "https://www.francetvinfo.fr/societe.rss",
         "https://www.liberation.fr/arc/outboundfeeds/rss/?outputType=xml",
         "https://www.lemonde.fr/societe/rss_full.xml"],
  "en": ["https://www.theguardian.com/uk-news/rss",
         "https://www.theguardian.com/us-news/rss",
         "https://feeds.bbci.co.uk/news/uk/rss.xml",
         "https://feeds.npr.org/1003/rss.xml",
         "https://feeds.npr.org/1014/rss.xml"],
  "de": ["https://www.tagesschau.de/index~rss2.xml",
         "https://rss.dw.com/xml/rss-de-all",
         "https://www.spiegel.de/schlagzeilen/index.rss"],
}
VOCI = {"es": "es-ES-ElviraNeural", "fr": "fr-FR-DeniseNeural",
        "en": "en-GB-RyanNeural", "de": "de-DE-KatjaNeural",
        "it": "it-IT-DiegoNeural"}
MODELLO = "claude-sonnet-5-5"
BASE_URL = os.environ.get("BASE_URL", "https://giova-news.github.io/rassegna")
OUT = "docs"
STORICO = "storico.json"
claude = anthropic.Anthropic()

def solo_testo(r):
    return "".join(b.text for b in r.content if b.type == "text")

def leggi_json(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default

def raccogli(gia_usati):
    items = []
    for lang, urls in FEEDS.items():
        for u in urls:
            entries = feedparser.parse(u).entries[:15]
            print(f"{len(entries):3d} articoli da {u}")
            for e in entries:
                if e.link in gia_usati or e.title in gia_usati:
                    continue
                items.append({"lang": lang, "title": e.title, "link": e.link,
                              "summary": e.get("summary", "")[:300]})
    return items

def candidati(items, voti):
    prompt = f"""Sei il curatore di una rassegna stampa personale per Giovanni, italiano,
che ascolta gli articoli in lingua originale per capire meglio i diversi paesi.
Ordina per interesse i 10 articoli migliori tra quelli sotto, in lingue diverse.
Cerca soprattutto: societa', costume, politica interna, sport, cultura, retroscena,
notizie poco coperte dalla stampa italiana, tutto cio' che aiuta a capire come vive
e cosa discute un paese. L'economia va bene solo ogni tanto, non deve dominare.
Per l'inglese alterna Regno Unito e Stati Uniti; per lo spagnolo alterna Spagna e
America Latina. Evita i grandi temi internazionali.
Voti passati di Giovanni (impara i suoi gusti): {json.dumps(voti, ensure_ascii=False)}
Articoli: {json.dumps(items, ensure_ascii=False)}
Rispondi SOLO con JSON: [{{"link":..., "lang":..., "title":..., "pitch_it": "una frase in italiano"}}]"""
    r = claude.messages.create(model=MODELLO, max_tokens=4000,
                               messages=[{"role": "user", "content": prompt}])
    t = solo_testo(r)
    return json.loads(t[t.find("["):t.rfind("]") + 1])

def scarica(link):
    try:
        html = trafilatura.fetch_url(link)
        return trafilatura.extract(html) if html else None
    except Exception:
        return None

def prepara(a):
    """Restituisce il testo da leggere, oppure None se l'articolo non e' leggibile."""
    testo = scarica(a["link"])
    if not testo or len(testo) < 600:
        print(f"Scartato (testo non disponibile): {a['title']}")
        return None
    if a["lang"] != "de":
        return testo[:8000]
    r = claude.messages.create(model=MODELLO, max_tokens=4000,
        messages=[{"role": "user", "content":
            "Riscrivi questo articolo in tedesco semplicissimo (livello A2): frasi brevi, "
            "parole comuni, massimo 250 parole. Rispondi solo con il testo tedesco, "
            f"senza commenti.\n\nTitolo: {a['title']}\n\n{testo[:8000]}"}])
    return solo_testo(r)

def voce(testo, lang, path):
    rate = "-20%" if lang == "de" else "+0%"
    asyncio.run(edge_tts.Communicate(testo, VOCI[lang], rate=rate).save(path))

def main():
    os.makedirs(OUT, exist_ok=True)
    oggi = datetime.date.today().isoformat()
    storico = leggi_json(STORICO, [])
    for f in glob.glob(f"{OUT}/????-??-??.json"):   # include anche i giorni gia' passati
        storico += [x.get("link") for x in leggi_json(f, [])] + [x.get("title") for x in leggi_json(f, [])]
    scelti, lingue = [], set()
    for a in candidati(raccogli(set(storico)), leggi_json("feedback.json", [])[-30:]):
        if len(scelti) == 3:
            break
        if a["lang"] in lingue or a["link"] in storico:
            continue
        testo = prepara(a)
        if testo:
            a["testo"] = testo
            scelti.append(a)
            lingue.add(a["lang"])
    episodi = []
    intro = "Buongiorno Giovanni. Ecco le proposte di oggi. " + " ".join(
        f"Numero {i+1}: {a['pitch_it']}" for i, a in enumerate(scelti))
    voce(intro, "it", f"{OUT}/{oggi}-0.mp3")
    episodi.append((f"{oggi} – Le proposte di oggi", f"{oggi}-0.mp3"))
    for i, a in enumerate(scelti, 1):
        voce(a["title"] + ". " + a["testo"], a["lang"], f"{OUT}/{oggi}-{i}.mp3")
        episodi.append((f"{oggi} – {i}. [{a['lang'].upper()}] {a['title']}", f"{oggi}-{i}.mp3"))
    storico = (storico + [a["link"] for a in scelti] + [a["title"] for a in scelti])[-600:]
    json.dump(storico, open(STORICO, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump([{k: v for k, v in a.items() if k != "testo"} for a in scelti],
              open(f"{OUT}/{oggi}.json", "w", encoding="utf-8"), ensure_ascii=False)
    scrivi_feed(episodi)

def scrivi_feed(nuovi):
    db = "episodi.json"
    tutti = leggi_json(db, [])
    ora = datetime.datetime.now(datetime.timezone.utc)
    for k, (t, f) in enumerate(nuovi):
        tutti.insert(k, {"title": t, "file": f,
                         "date": format_datetime(ora - datetime.timedelta(minutes=k))})
    tutti = tutti[:40]
    json.dump(tutti, open(db, "w", encoding="utf-8"), ensure_ascii=False)
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    items = "".join(f"<item><title>{esc(e['title'])}</title><guid>{e['file']}</guid>"
        f"<pubDate>{e['date']}</pubDate><enclosure url='{BASE_URL}/{e['file']}' type='audio/mpeg'/></item>"
        for e in tutti)
    xml = ("<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel>"
           f"<title>Rassegna poliglotta</title><link>{BASE_URL}</link>"
           f"<description>Rassegna personale</description>{items}</channel></rss>")
    open(f"{OUT}/feed.xml", "w", encoding="utf-8").write(xml)

if __name__ == "__main__":
    main()
