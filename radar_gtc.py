"""
Radar GTC v2 - genera radar_gtc.json con datos de Yahoo Finance
Bloomberg Global Trading Challenge 2026 (12-oct a 13-nov-2026)

Uso:
    python radar_gtc.py docs/radar_gtc.json      # datos reales
    python radar_gtc.py --demo docs/radar_gtc.json  # datos simulados (sin internet)

Para cambiar la lista de acciones, edita SEMILLA.
"""
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

VENTANA_INI = date(2026, 10, 12)
VENTANA_FIN = date(2026, 11, 13)
LIQUIDEZ_MIN_USD_MM = 20  # volumen diario promedio minimo (millones USD)
NOTICIAS_POR_EMPRESA = 5

SEMILLA = {
    "Computación cuántica": ["IONQ", "RGTI", "QBTS", "QUBT"],
    "Nuclear / uranio": ["OKLO", "SMR", "NNE", "LEU", "CCJ", "UEC"],
    "Espacio": ["RKLB", "ASTS", "LUNR", "RDW", "PL"],
    "IA infraestructura": ["CRWV", "NBIS", "IREN", "CIFR", "WULF", "APLD", "CORZ"],
    "Semiconductores": ["AMD", "MU", "SMCI", "ARM", "NVDA", "AVGO", "TSM"],
    "Cripto": ["MSTR", "COIN", "HOOD", "MARA", "RIOT", "CLSK"],
    "Software / IA": ["PLTR", "SOUN", "BBAI", "AI", "APP"],
    "eVTOL / defensa": ["JOBY", "ACHR", "KTOS", "AVAV", "RCAT"],
    "Fintech": ["SOFI", "AFRM", "UPST"],
    "EV / baterías": ["TSLA", "RIVN", "LCID", "QS", "EOSE"],
    "Tierras raras": ["MP", "USAR"],
}

DRIVERS = {
    "ACWI": "Mercado global",
    "QQQ": "Nasdaq",
    "IWM": "Small caps EE.UU.",
    "BTC-USD": "Bitcoin",
    "URA": "Uranio",
    "SMH": "Semiconductores",
}

# Empresas grandes que no estan en la lista pero cuyos resultados mueven al resto
LIDERES_EXTRA = {
    "MSFT": "Microsoft", "GOOGL": "Alphabet", "META": "Meta", "AMZN": "Amazon",
    "AAPL": "Apple", "ORCL": "Oracle", "ASML": "ASML",
}

# Descubrimiento diario: listas de Yahoo que se revisan cada dia para sumar acciones nuevas
DESCUBRIR = {
    "day_gainers": "Entre las que más suben hoy en EE.UU.",
    "most_actives": "Entre las más transadas hoy en EE.UU.",
    "small_cap_gainers": "Small cap con fuerte alza reciente",
    "aggressive_small_caps": "Small cap de alto crecimiento",
    "most_shorted_stocks": "Entre las con más apuestas a la baja (short)",
    "growth_technology_stocks": "Tecnológica de alto crecimiento",
}
MAX_NUEVAS = 20
NUEVAS = "Nuevas del día"

# ---- Lista dinamica ----
TOTAL_CON_WLS = 110          # con wls.txt: cuantas acciones de tu lista de Bloomberg se analizan
TOTAL_ACCIONES = 90          # cuantas acciones sigue el radar cada dia (sin contar equipo.txt)
NUCLEO = [                   # 25 fijas: siempre se siguen, para tener continuidad
    "IONQ", "RGTI", "OKLO", "LEU", "CCJ", "RKLB", "ASTS", "NBIS", "CRWV", "IREN",
    "NVDA", "AMD", "TSM", "MU", "MSTR", "COIN", "HOOD", "PLTR", "APP", "JOBY",
    "KTOS", "SOFI", "AFRM", "TSLA", "MP",
]
WLS_TXT = "wls.txt"          # tickers del indice WLS (solo nombres, sin datos de Bloomberg)
EQUIPO_TXT = "equipo.txt"    # tickers que el equipo quiere seguir siempre (uno por linea)
EQUIPO = "Elegidas por el equipo"
# Industria de Yahoo -> tema del radar (para las acciones nuevas)
INDUSTRIA_TEMA = [
    ("Semiconductor", "Semiconductores"), ("Software", "Software / IA"), ("Information Technology Services", "Software / IA"),
    ("Uranium", "Nuclear / uranio"), ("Aerospace", "eVTOL / defensa"), ("Auto", "EV / baterías"),
    ("Electrical Equipment", "EV / baterías"), ("Credit Services", "Fintech"), ("Capital Markets", "Cripto y mercados"),
    ("Financial Data", "Cripto y mercados"), ("Biotechnology", "Biotecnología"), ("Drug Manufacturers", "Biotecnología"),
    ("Medical", "Salud"), ("Internet", "Internet"), ("Communication Equipment", "Hardware y redes"),
    ("Computer Hardware", "Hardware y redes"), ("Solar", "Energía"), ("Oil", "Energía"), ("Utilities", "Energía"),
    ("Gold", "Minería"), ("Silver", "Minería"), ("Copper", "Minería"), ("Other Industrial Metals", "Tierras raras"),
]
SECTOR_TEMA = {"Technology": "Tecnología", "Healthcare": "Salud", "Consumer Cyclical": "Consumo",
               "Financial Services": "Finanzas", "Industrials": "Industria", "Energy": "Energía",
               "Basic Materials": "Minería", "Communication Services": "Internet", "Real Estate": "Inmobiliario",
               "Utilities": "Energía", "Consumer Defensive": "Consumo"}


def tema_por_industria(industria, sector):
    for clave, tema in INDUSTRIA_TEMA:
        if industria and clave.lower() in industria.lower():
            return tema
    return SECTOR_TEMA.get(sector or "", "Otras")


EQUIPO_BBG = {}


def leer_equipo():
    """equipo.txt: un ticker por linea; opcional ', motivo'. Lineas con # se ignoran."""
    import os
    out = {}
    if not os.path.exists(EQUIPO_TXT):
        return out
    for linea in open(EQUIPO_TXT, encoding="utf-8"):
        linea = linea.split("#")[0].strip()
        if not linea:
            continue
        partes = [x.strip() for x in linea.replace(";", ",").split(",", 1)]
        r_ = a_yahoo(partes[0])
        if not r_:
            continue
        t = r_[0]
        EQUIPO_BBG[t] = r_[1]
        out[t] = partes[1] if len(partes) > 1 and partes[1] else "Agregada por el equipo"
    return out

def leer_pedidas(dias=7):
    """pedidas.txt (lo escribe la Mesa con el boton 'Pedir analisis a fondo'): 'simbolo Yahoo | ticker BBG | fecha | quien'.
    Se analizan a fondo durante 7 dias desde que se pidieron."""
    out = {}
    if not os.path.exists("pedidas.txt"):
        return out
    lim = (datetime.now(timezone.utc) - timedelta(days=dias)).date().isoformat()
    for linea in open("pedidas.txt", encoding="utf-8"):
        p = [x.strip() for x in linea.split("#")[0].split("|")]
        if not p or not p[0]:
            continue
        f = p[2] if len(p) > 2 else ""
        if f and f[:10] < lim:
            continue
        r_ = a_yahoo(p[1]) if len(p) > 1 and " " in p[1] else None
        out[r_[0] if r_ else p[0]] = {"fecha": f[:10], "quien": p[3] if len(p) > 3 else ""}
    return out


# Bolsa Bloomberg -> (sufijo Yahoo, moneda, divisor). Divisor 100 = la bolsa cotiza en centavos (peniques, etc.)
BBG2YF = {
    "US": ("", "USD", 1), "UN": ("", "USD", 1), "UW": ("", "USD", 1), "UQ": ("", "USD", 1), "UA": ("", "USD", 1),
    "UR": ("", "USD", 1), "UP": ("", "USD", 1), "UV": ("", "USD", 1),
    "CN": (".TO", "CAD", 1), "CT": (".TO", "CAD", 1), "BZ": (".SA", "BRL", 1), "MM": (".MX", "MXN", 1), "CI": (".SN", "CLP", 1),
    "LN": (".L", "GBP", 100), "GR": (".DE", "EUR", 1), "GY": (".DE", "EUR", 1), "FP": (".PA", "EUR", 1), "NA": (".AS", "EUR", 1),
    "SM": (".MC", "EUR", 1), "IM": (".MI", "EUR", 1), "BB": (".BR", "EUR", 1), "AV": (".VI", "EUR", 1), "PL": (".LS", "EUR", 1),
    "FH": (".HE", "EUR", 1), "ID": (".IR", "EUR", 1), "SW": (".SW", "CHF", 1), "SE": (".SW", "CHF", 1), "SS": (".ST", "SEK", 1),
    "DC": (".CO", "DKK", 1), "NO": (".OL", "NOK", 1), "PW": (".WA", "PLN", 1), "HB": (".BD", "HUF", 1), "TI": (".IS", "TRY", 1),
    "IT": (".TA", "ILS", 100), "AB": (".SR", "SAR", 1), "QD": (".QA", "QAR", 1), "SJ": (".JO", "ZAR", 100),
    "JP": (".T", "JPY", 1), "JT": (".T", "JPY", 1), "KS": (".KS", "KRW", 1), "KQ": (".KQ", "KRW", 1), "TT": (".TW", "TWD", 1),
    "HK": (".HK", "HKD", 1), "C1": (".SS", "CNY", 1), "C2": (".SZ", "CNY", 1), "IN": (".NS", "INR", 1), "IS": (".NS", "INR", 1),
    "IB": (".BO", "INR", 1), "SP": (".SI", "SGD", 1), "TB": (".BK", "THB", 1), "IJ": (".JK", "IDR", 1), "PM": (".PS", "PHP", 1),
    "AU": (".AX", "AUD", 1), "NZ": (".NZ", "NZD", 1), "MK": (".KL", "MYR", 1), "CB": (".CL", "COP", 1),
    "EY": (".CA", "EGP", 1), "VN": (".VN", "VND", 1), "KK": (".KW", "KWD", 1000),
}
SUF2MON = {v[0]: (v[1], v[2]) for v in BBG2YF.values() if v[0]}


def a_yahoo(texto):
    """'000660 KS Equity' -> ('000660.KS', '000660 KS', 'KS'). None si la bolsa no se puede leer en Yahoo."""
    p = texto.upper().replace(" EQUITY", "").split()
    if not p:
        return None
    sym, ex = p[0], (p[1] if len(p) > 1 else "US")
    if ex not in BBG2YF:
        return None
    suf = BBG2YF[ex][0]
    if ex == "HK" and sym.isdigit():
        sym = sym.zfill(4)
    if ex in ("SS", "DC", "NO", "FH") and len(sym) >= 4 and sym[-1] in "AB" and not sym.isdigit():
        sym = sym[:-1] + "-" + sym[-1]          # ERICB -> ERIC-B (clases de acciones nordicas)
    sym = sym.replace("/", "-")
    bbg = f"{p[0]} {ex}" if suf else f"{p[0]} US"
    return sym + suf, bbg, ("US" if not suf else ex)


def factor_usd(t, fx):
    """Multiplicador para pasar precio/monto en moneda local a USD (incluye centavos)."""
    for suf, (mon, div) in SUF2MON.items():
        if t.endswith(suf):
            v = fx.get(mon)
            return (1.0 / (v * div)) if v else None
    return 1.0


def leer_wls():
    """wls.txt: un ticker por linea (los del indice WLS que interesan). Se priorizan al elegir las acciones del dia."""
    import os
    if not os.path.exists(WLS_TXT):
        return {}
    out = {}
    for linea in open(WLS_TXT, encoding="utf-8"):
        linea = linea.split("#")[0].strip()
        if not linea:
            continue
        r_ = a_yahoo(linea)
        if r_:
            out[r_[0]] = r_[1]     # simbolo Yahoo -> ticker Bloomberg
    return out


TASA = "^TNX"   # rendimiento del bono del Tesoro de EE.UU. a 10 anos (en %)

# Eventos macro dentro del desafio (hora de Chile). Fuentes: Fed, BEA, BLS, BCE, BoJ, BoE, Banco Central de Chile
EVENTOS_MACRO = [
    {"fecha": "2026-10-14", "hora": "09:30", "evento": "IPC (inflación) de septiembre", "tipo": "inflacion"},
    {"fecha": "2026-10-15", "hora": "09:30", "evento": "Precios al productor (PPI) de septiembre", "tipo": "inflacion"},
    {"fecha": "2026-10-27", "hora": "18:00", "evento": "Banco Central de Chile: decisión de tasas", "tipo": "banco"},
    {"fecha": "2026-10-28", "hora": "15:00", "evento": "Decisión de tasas de la Fed (FOMC)", "tipo": "fed"},
    {"fecha": "2026-10-29", "hora": "09:30", "evento": "PIB EE.UU. 3er trimestre + inflación PCE", "tipo": "inflacion"},
    {"fecha": "2026-10-29", "hora": "10:15", "evento": "Banco Central Europeo: decisión de tasas", "tipo": "banco"},
    {"fecha": "2026-10-30", "hora": "00:00", "evento": "Banco de Japón: decisión de tasas", "tipo": "banco"},
    {"fecha": "2026-11-03", "hora": "", "evento": "Elecciones de mitad de período en EE.UU.", "tipo": "politica"},
    {"fecha": "2026-11-05", "hora": "09:00", "evento": "Banco de Inglaterra: decisión de tasas", "tipo": "banco"},
    {"fecha": "2026-11-06", "hora": "10:30", "evento": "Informe de empleo de octubre", "tipo": "empleo"},
    {"fecha": "2026-11-10", "hora": "10:30", "evento": "IPC (inflación) de octubre", "tipo": "inflacion"},
    {"fecha": "2026-11-13", "hora": "10:30", "evento": "Precios al productor (PPI) de octubre", "tipo": "inflacion"},
]

RECOMENDACION = {
    "strong_buy": "Compra fuerte", "buy": "Compra", "hold": "Mantener",
    "underperform": "Bajo el mercado", "sell": "Venta", "strong_sell": "Venta fuerte",
}


def r(x, n=2):
    try:
        x = float(x)
        return None if np.isnan(x) or np.isinf(x) else round(x, n)
    except (TypeError, ValueError):
        return None


def zscore(s):
    s = pd.to_numeric(s, errors="coerce").astype(float)
    sd = s.std()
    return ((s - s.mean()) / sd).fillna(0) if sd and not np.isnan(sd) else s * 0


def rsi(serie, n=14):
    d = serie.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ------------------------------------------------------------ descarga
def descargar(tickers):
    import yfinance as yf
    for intento in range(4):
        df = yf.download(tickers, period="3y", interval="1d", auto_adjust=True,
                         progress=False, threads=True)
        if not df.empty and df["Close"].notna().sum().gt(60).sum() > len(tickers) * 0.5:
            return df
        print(f"  Yahoo respondio incompleto, reintento {intento + 1}...")
        time.sleep(20 * (intento + 1))
    raise SystemExit("Yahoo no entrego precios suficientes. Se mantiene la version anterior.")


def _rss(url, fuente_def, maximo=None):
    """Lee un feed RSS (Yahoo Finance o Google News) sin librerias extra."""
    import urllib.request
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (radar-gtc)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        root = ET.fromstring(resp.read())
    out = []
    for item in root.iter("item"):
        titulo = (item.findtext("title") or "").strip()
        url_n = (item.findtext("link") or "").strip()
        src = item.find("source")
        fuente = (src.text if src is not None and src.text else fuente_def)
        if fuente_def == "Google News" and " - " in titulo:  # Google agrega " - Medio" al titulo
            titulo, fuente = titulo.rsplit(" - ", 1)
        fecha = ""
        try:
            fecha = parsedate_to_datetime(item.findtext("pubDate")).isoformat()[:16]
        except Exception:
            pass
        if titulo and url_n:
            out.append({"titulo": titulo, "fuente": fuente, "url": url_n, "fecha": fecha})
        if len(out) >= (maximo or NOTICIAS_POR_EMPRESA):
            break
    return out


def leer_noticias(tk, t=None, nombre=None):
    """Prueba varias fuentes hasta conseguir noticias."""
    import urllib.parse
    out = _noticias_yf(tk)
    if not out:
        try:
            import yfinance as yf
            out = _noticias_items(yf.Search(t, news_count=NOTICIAS_POR_EMPRESA).news or [])
        except Exception:
            out = []
    if not out and t:
        try:
            out = _rss(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={t}&region=US&lang=en-US",
                       "Yahoo Finance")
        except Exception:
            out = []
    if not out and t:
        try:
            q = urllib.parse.quote(f'"{nombre or t}" {t} stock')
            out = _rss(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en", "Google News")
        except Exception:
            out = []
    return out


def _noticias_yf(tk):
    try:
        return _noticias_items(tk.news or [])
    except Exception:
        return []


def _noticias_items(items):
    out = []
    for it in items:
        c = it.get("content") if isinstance(it, dict) else None
        if c:  # formato nuevo de yfinance
            titulo = c.get("title")
            fuente = (c.get("provider") or {}).get("displayName")
            url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
            fecha = c.get("pubDate") or c.get("displayTime")
        else:  # formato antiguo
            titulo = it.get("title")
            fuente = it.get("publisher")
            url = it.get("link")
            ts = it.get("providerPublishTime")
            fecha = datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None
        if titulo and url:
            out.append({"titulo": titulo, "fuente": fuente, "url": url,
                        "fecha": (fecha or "")[:16]})
        if len(out) >= NOTICIAS_POR_EMPRESA:
            break
    return out


def info_de(tickers):
    import yfinance as yf
    filas = {}
    for i, t in enumerate(tickers, 1):
        print(f"  {i}/{len(tickers)} {t}        ", end="\r")
        f = {}
        time.sleep(0.4)  # evita que Yahoo corte por exceso de consultas
        try:
            tk = yf.Ticker(t)
            inf = tk.info or {}
            mc = inf.get("marketCap")
            sp = inf.get("shortPercentOfFloat")
            desc = (inf.get("longBusinessSummary") or "").split(". ")[0]
            f = {
                "nombre": inf.get("shortName") or inf.get("longName"),
                "pais": inf.get("country"),
                "bolsa": inf.get("exchange"),   # NMS/NGM/NCM = Nasdaq, NYQ = NYSE, ASE, PCX...
                "sector": inf.get("sector"),
                "industria": inf.get("industry"),
                "desc": (desc[:260] + "…") if len(desc) > 260 else (desc + "." if desc else None),
                "web": inf.get("website"),
                "mcap": round(mc / 1e6) if mc else None,
                "short": round(sp * 100, 1) if sp else None,
                "target": r(inf.get("targetMeanPrice")),
                "nAnalistas": inf.get("numberOfAnalystOpinions"),
                "reco": RECOMENDACION.get(inf.get("recommendationKey")),
            }
            cal = tk.calendar
            fechas = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if fechas:
                f["earn"] = pd.to_datetime(fechas[0]).date().isoformat()
        except Exception as e:
            print(f"\n  aviso: {t} sin datos ({e.__class__.__name__})")
        try:
            f["noticias"] = leer_noticias(yf.Ticker(t), t, f.get("nombre"))
        except Exception:
            f["noticias"] = []
        filas[t] = f
    print()
    con = sum(1 for v in filas.values() if v.get("noticias"))
    print(f"Noticias: {con} de {len(filas)} empresas con noticias")
    return filas


def demo(tickers, temas):
    rng = np.random.default_rng(11)
    n = 756
    idx = pd.bdate_range(end=datetime(2026, 10, 9), periods=n)
    fac = {k: rng.normal(0, 0.022, n) for k in set(temas.values())}
    mkt = rng.normal(0.0006, 0.009, n)
    close, vol, info = {}, {}, {}
    sectores = ["Technology", "Industrials", "Energy", "Financial Services", "Consumer Cyclical", "Basic Materials"]
    for t in tickers:
        if t == TASA:
            close[t] = 4.2 + np.cumsum(rng.normal(0, 0.04, n)) * 0.3 - mkt.cumsum() * 3
            vol[t] = np.zeros(n)
            continue
        if t.endswith("=X"):      # tipo de cambio de ejemplo (unidades por USD)
            close[t] = np.full(n, {"KRW": 1400, "JPY": 150, "TWD": 32, "CNY": 7.2, "INR": 84, "HKD": 7.8, "GBP": 0.78,
                                   "EUR": 0.92, "SEK": 10.5, "ZAR": 18, "CHF": 0.88, "BRL": 5.4}.get(t[:3], 1.0))
            vol[t] = np.zeros(n)
            continue
        if t in DRIVERS or t in LIDERES_EXTRA:
            rr = mkt * (1.0 if t == "ACWI" else 1.6) + rng.normal(0, 0.007, n)
        else:
            rr = mkt * 1.4 + fac[temas[t]] * rng.uniform(0.8, 1.8) + rng.normal(0, 0.028, n)
            d = int(rng.integers(-6, 45))
            p = float(rng.uniform(5, 300))
            info[t] = {"nombre": f"Ejemplo {t}", "pais": "United States", "bolsa": ["NMS", "NYQ"][int(rng.integers(0, 2))],
                       "sector": sectores[hash(temas[t]) % len(sectores)],
                       "industria": f"Industria de ejemplo ({temas[t]})",
                       "desc": f"Empresa de ejemplo del tema {temas[t]}. Los datos reales llegan con la próxima actualización.",
                       "mcap": int(rng.integers(800, 60000)),
                       "short": round(float(rng.uniform(2, 28)), 1),
                       "target": None, "nAnalistas": int(rng.integers(3, 25)),
                       "reco": ["Compra fuerte", "Compra", "Mantener"][int(rng.integers(0, 3))],
                       "earn": (date(2026, 10, 12) + pd.Timedelta(days=d)).isoformat(),
                       "noticias": [{"titulo": f"Titular de ejemplo {k + 1} sobre {t}", "fuente": "Ejemplo",
                                     "url": "https://finance.yahoo.com/", "fecha": "2026-10-10T12:00"}
                                    for k in range(3)]}
            info[t]["_p0"] = p
        close[t] = float(rng.uniform(5, 300)) * np.exp(np.cumsum(rr))
        vol[t] = rng.integers(500_000, 30_000_000, n)
    for t in info:
        info[t]["target"] = round(close[t][-1] * float(rng.uniform(0.8, 1.5)), 2)
        info[t].pop("_p0", None)
    return pd.DataFrame(close, index=idx), pd.DataFrame(vol, index=idx), info


# ------------------------------------------------------------ señales
def senales(a):
    s = []
    if a.get("origen") == "equipo":
        s.append(("info", f"En la lista del equipo: {a.get('motivo') or 'agregada a mano'}"))
    elif a.get("motivo"):
        s.append(("info", f"Nueva del día: {a['motivo']}"))
    if a["enVentana"] and a["diasEarn"] is not None:
        s.append(("info", f"Reporta resultados en {a['diasEarn']} días ({a['earn'][8:]}/{a['earn'][5:7]})"))
    if a["sma20"] is not None and a["sma50"] is not None:
        if a["sma20"] > 0 and a["sma50"] > 0:
            s.append(("good", "Tendencia alcista: sobre sus medias de 20 y 50 días"))
        elif a["sma20"] < 0 and a["sma50"] < 0:
            s.append(("bad", "Tendencia bajista: bajo sus medias de 20 y 50 días"))
    if a["rsi"] is not None:
        if a["rsi"] >= 70:
            s.append(("warn", f"Sobrecomprada (RSI {a['rsi']:.0f}): subió rápido, riesgo de corrección"))
        elif a["rsi"] <= 30:
            s.append(("info", f"Sobrevendida (RSI {a['rsi']:.0f}): cayó fuerte, posible rebote"))
    if a["volRatio"] is not None and a["volRatio"] >= 1.8:
        s.append(("info", f"Volumen inusual: {a['volRatio']:.1f}x su promedio esta semana"))
    if a["short"] is not None and a["short"] >= 20:
        s.append(("warn", f"Short interest alto ({a['short']:.0f}%): puede dispararse o seguir cayendo"))
    if a["dist52"] is not None and a["dist52"] >= -5:
        s.append(("good", "Cerca de su máximo de 12 meses"))
    elif a["dist52"] is not None and a["dist52"] <= -50:
        s.append(("bad", f"{abs(a['dist52']):.0f}% bajo su máximo de 12 meses"))
    if a["upside"] is not None and a["upside"] >= 30:
        s.append(("good", f"Analistas ven {a['upside']:.0f}% de potencial al precio objetivo"))
    elif a["upside"] is not None and a["upside"] <= -10:
        s.append(("warn", f"Ya supera el precio objetivo de analistas ({a['upside']:.0f}%)"))
    if a.get("corrTasa") is not None and abs(a["corrTasa"]) >= 0.25 and a.get("sensTasa") is not None:
        if a["sensTasa"] < 0:
            s.append(("warn", f"Sensible a tasas: si la tasa a 10 años sube 0,10 pp, suele caer {abs(a['sensTasa']):.1f}%"))
        else:
            s.append(("info", f"Sube cuando suben las tasas: +{a['sensTasa']:.1f}% por cada 0,10 pp"))
    k = a.get("kronos")
    if k and k.get("mov") is not None and k["mov"] >= 15:
        s.append(("info", f"Kronos espera mucho movimiento: ±{k['mov']:.0f}% en {k['dias']} días"))
    if a["liq"] is not None and a["liq"] < LIQUIDEZ_MIN_USD_MM:
        s.append(("bad", "Poca liquidez: el precio puede saltar mucho"))
    return [{"tipo": t, "texto": x} for t, x in s]


def correr_kronos(ohlc, close, orden, es_demo):
    """Pronostico de escenarios con Kronos. Se activa con RADAR_KRONOS=1."""
    import os
    if es_demo:
        rng = np.random.default_rng(5)
        out = {}
        for t in orden:
            p = float(close[t].iloc[-1]); vol = float(close[t].pct_change().tail(20).std() or .03)
            paths = p * np.exp(np.cumsum(rng.normal(0, vol, (20, 10)), axis=1))
            from kronos_gtc import resumir
            out[t] = resumir(paths, list(pd.bdate_range(close.index[-1] + pd.Timedelta(days=1), periods=10)), p)
        return out
    if os.environ.get("RADAR_KRONOS", "0") != "1" or ohlc is None:
        return {}
    try:
        from kronos_gtc import pronosticar_todas
    except Exception as e:
        print(f"Kronos no disponible ({e}).")
        return {}
    print("Corriendo Kronos (puede tardar 5-10 minutos)...")
    porticker = {}
    for t in orden:
        try:
            df = pd.DataFrame({"open": ohlc["Open"][t], "high": ohlc["High"][t], "low": ohlc["Low"][t],
                               "close": ohlc["Close"][t], "volume": ohlc["Volume"][t]}).dropna()
            if len(df) > 60:
                porticker[t] = df
        except KeyError:
            pass
    return pronosticar_todas(porticker, [t for t in orden if t in porticker])


def historial_reportes(tickers, es_demo=False, indice=None):
    """Fechas de reportes pasados (hasta 3 años) y el próximo, por ticker."""
    pasados, proximos = {}, {}
    if es_demo:
        rng = np.random.default_rng(3)
        for t in tickers:
            base = pd.Timestamp("2023-11-01") + pd.Timedelta(days=int(rng.integers(0, 60)))
            fechas = [base + pd.DateOffset(months=3 * k) for k in range(12)]
            pasados[t] = [f.date() for f in fechas if f < pd.Timestamp("2026-10-01")]
            proximos[t] = (pasados[t][-1] + pd.DateOffset(months=3)).date().isoformat()
        return pasados, proximos
    import yfinance as yf
    hoy = pd.Timestamp.now().normalize()
    for i, t in enumerate(tickers, 1):
        print(f"  reportes {i}/{len(tickers)} {t}      ", end="\r")
        time.sleep(0.3)
        try:
            ed = yf.Ticker(t).get_earnings_dates(limit=16)
            if ed is None or ed.empty:
                continue
            fechas = sorted({pd.Timestamp(x).tz_localize(None).normalize() for x in ed.index})
            pasados[t] = [f.date() for f in fechas if hoy - pd.Timedelta(days=1100) <= f < hoy]
            futuras = [f for f in fechas if f >= hoy]
            if futuras:
                proximos[t] = futuras[0].date().isoformat()
        except Exception:
            pass
    print()
    print(f"Historial de reportes: {len(pasados)} de {len(tickers)} empresas")
    return pasados, proximos


def contagio(close, pasados, proximos, lideres, seguidores, nombres, hoy):
    """Cuando un lider reporta, que acciones se mueven con el (mismo dia y 3 dias despues)."""
    idx = close.index
    mkt = close["ACWI"]
    diaria = close.pct_change(fill_method=None).tail(250)

    def ret(serie, a, b):
        return serie.iloc[b] / serie.iloc[a] - 1

    salida = []
    for L in lideres:
        if L not in close or L not in pasados:
            continue
        ventanas = []
        for d in pasados[L]:
            i = idx.searchsorted(pd.Timestamp(d))
            if 1 <= i and i + 4 < len(idx):
                ventanas.append(i)
        if len(ventanas) < 8:
            continue
        rL = np.array([ret(close[L], i - 1, i + 1) - ret(mkt, i - 1, i + 1) for i in ventanas])
        if np.std(rL) == 0 or np.isnan(rL).any():
            continue
        segs = []
        for F in seguidores:
            if F == L or F not in close:
                continue
            sync = np.array([ret(close[F], i - 1, i + 1) - ret(mkt, i - 1, i + 1) for i in ventanas])
            lag = np.array([ret(close[F], i + 1, i + 4) - ret(mkt, i + 1, i + 4) for i in ventanas])
            ok = ~(np.isnan(sync) | np.isnan(lag))
            if ok.sum() < 8 or np.std(sync[ok]) == 0:
                continue
            a, b, c = rL[ok], sync[ok], lag[ok]
            corr = float(np.corrcoef(a, b)[0, 1])
            mismo = float(np.mean(np.sign(a) == np.sign(b)))
            cd = diaria[L].corr(diaria[F])
            # filtro contra casualidades: relacion fuerte en reportes Y correlacion diaria normal
            if corr < 0.5 or mismo < 0.7 or not (cd >= 0.25):
                continue
            segs.append({"t": F, "corr": round(corr, 2), "mismo": round(mismo * 100),
                         "n": int(ok.sum()), "corrDia": round(float(cd), 2),
                         "beta": round(float(np.sum(a * b) / np.sum(a * a)), 2),
                         "mag": round(float(np.mean(np.abs(b))) * 100, 1),
                         "sigue": round(float(np.mean(c * np.sign(a))) * 100, 1)})
        if not segs:
            continue
        segs.sort(key=lambda x: -(x["corr"] * x["mismo"]))
        segs = segs[:5]
        item = {"t": L, "nombre": nombres.get(L, L), "eventos": len(ventanas),
                "movL": round(float(np.mean(np.abs(rL))) * 100, 1),
                "proximo": proximos.get(L), "seguidores": segs}
        if item["proximo"]:
            item["dias"] = (date.fromisoformat(item["proximo"]) - hoy).days
        # reporte reciente (ultimos 5 dias habiles): como reacciono y quien falta por moverse
        ult = [d for d in pasados[L] if idx.searchsorted(pd.Timestamp(d)) >= len(idx) - 5]
        if ult:
            i = idx.searchsorted(pd.Timestamp(ult[-1]))
            fin = len(idx) - 1
            rnow = ret(close[L], max(i - 1, 0), fin) - ret(mkt, max(i - 1, 0), fin)
            item["reciente"] = {
                "fecha": ult[-1].isoformat(), "reaccion": round(float(rnow) * 100, 1),
                "seguidores": [{"t": s_["t"], "esperado": round(s_["beta"] * rnow * 100, 1),
                                "real": round(float(ret(close[s_["t"]], max(i - 1, 0), fin)
                                                    - ret(mkt, max(i - 1, 0), fin)) * 100, 1)}
                               for s_ in segs]}
        salida.append(item)
    salida.sort(key=lambda x: (x.get("dias") is None or x.get("dias", 999) < 0, x.get("dias", 999)))
    print(f"Contagio: {len(salida)} lideres con seguidores claros")
    return salida


def cuadrante(r1m, r3m):
    if r1m is None or r3m is None:
        return None
    if r1m >= 0 and r3m >= 0:
        return "Líder"
    if r1m >= 0:
        return "Recuperándose"
    if r3m >= 0:
        return "Perdiendo fuerza"
    return "Rezagada"


# ------------------------------------------------------------ calculo
def descubrir(ya, maximo=MAX_NUEVAS):
    """Busca en las listas de Yahoo acciones liquidas y movidas que no estan en la SEMILLA."""
    import yfinance as yf
    cand = {}
    for clave, motivo in DESCUBRIR.items():
        try:
            res = yf.screen(clave, count=100)
            quotes = res.get("quotes", []) if isinstance(res, dict) else []
        except Exception as e:
            print(f"  aviso: lista {clave} no disponible ({e.__class__.__name__})")
            continue
        for q in quotes:
            t = q.get("symbol")
            if not t or t in ya or any(c in t for c in ".^=-"):
                continue
            if q.get("quoteType") not in (None, "EQUITY"):
                continue
            px = q.get("regularMarketPrice") or 0
            mc = q.get("marketCap") or 0
            vol = q.get("averageDailyVolume3Month") or q.get("regularMarketVolume") or 0
            if px < 3 or mc < 1e9 or px * vol < LIQUIDEZ_MIN_USD_MM * 1e6:
                continue
            c = cand.setdefault(t, {"motivos": [], "chg": q.get("regularMarketChangePercent") or 0,
                                    "nombre": q.get("shortName") or q.get("longName")})
            c["motivos"].append(motivo)
        time.sleep(0.5)
    # prioriza las que aparecen en mas listas y luego las que mas se mueven hoy
    orden = sorted(cand.items(), key=lambda kv: (-len(kv[1]["motivos"]), -abs(kv[1]["chg"])))[:maximo]
    print(f"Descubrimiento: {len(cand)} candidatas, se suman {len(orden)}")
    return {t: " · ".join(dict.fromkeys(v["motivos"])) for t, v in orden}


def preseleccion(close, volu, pool, forzadas, total, preferidas=frozenset(), fac=None):
    """Elige las acciones del dia: forzadas + las de mejor pre-puntaje (volatilidad, momentum, liquidez)."""
    ret = close.pct_change(fill_method=None)
    filas = {}
    for t in pool:
        if t not in close or close[t].notna().sum() < 60:
            continue
        s = close[t].dropna()
        f_ = (fac or {}).get(t, 1.0)
        if f_ is None:
            continue      # no hay tipo de cambio: no se puede medir en USD
        liq = float((close[t] * volu[t]).tail(20).mean() / 1e6) * f_ if t in volu else 0
        if liq < LIQUIDEZ_MIN_USD_MM or s.iloc[-1] * f_ < 1:
            continue
        vol20 = float(ret[t].tail(20).std() * np.sqrt(252) * 100)
        r1m = float((s.iloc[-1] / s.iloc[-22] - 1) * 100) if len(s) > 22 else 0
        r1s = float((s.iloc[-1] / s.iloc[-6] - 1) * 100) if len(s) > 6 else 0
        filas[t] = {"vol": vol20, "r1m": r1m, "r1s": r1s, "liq": liq}
    df = pd.DataFrame(filas).T
    if df.empty:
        return list(forzadas)
    df["pre"] = 0.5 * zscore(df["vol"]) + 0.3 * zscore(df["r1m"].abs()) + 0.2 * zscore(df["r1s"].abs())
    df["pre"] += [0.6 if t in preferidas else 0 for t in df.index]   # bonus: estan en el WLS
    elegidas = [t for t in forzadas if t in close and close[t].notna().sum() >= 60]
    for t in df.sort_values("pre", ascending=False).index:
        if len(elegidas) >= total + len([x for x in forzadas if x not in NUCLEO]):
            break
        if t not in elegidas:
            elegidas.append(t)
    return elegidas


def construir(es_demo=False, modo_wls=False):
    temas = {t: tema for tema, ts in SEMILLA.items() for t in ts}
    equipo = leer_equipo()
    lista_wls = leer_wls()                     # simbolo Yahoo -> ticker Bloomberg (todas las bolsas del WLS)
    wls = lista_wls                            # ambas paginas incluyen las acciones del WLS de todos los paises
    motivos, origen = {}, {}
    if wls and modo_wls and not es_demo:
        cands = {}   # con wls.txt el radar sigue SOLO tus acciones de Bloomberg (+ fijas + equipo)
        print("wls.txt encontrado: se omiten las listas de Yahoo")
    elif es_demo:
        cands = {f"NUEV{k}": DESCUBRIR[list(DESCUBRIR)[k % len(DESCUBRIR)]] for k in range(1, 9)}
    else:
        try:
            cands = descubrir(set(temas) | set(equipo), maximo=150)
        except Exception as e:
            print(f"Descubrimiento omitido ({e.__class__.__name__}: {e})")
            cands = {}
    for t, mtv in cands.items():
        temas.setdefault(t, NUEVAS); motivos[t] = mtv
    for t in sorted(wls):
        if t not in temas:
            temas[t] = NUEVAS
            motivos[t] = "Está en el índice WLS y reporta durante el desafío"
    if wls:
        print(f"wls.txt: {len(wls)} acciones del indice WLS")
    for t, mtv in equipo.items():
        temas[t] = EQUIPO if t not in temas or temas[t] == NUEVAS else temas[t]
        motivos[t] = mtv
    if wls and modo_wls:
        pool = [t for t in temas if t in wls or t in NUCLEO or t in equipo]
        total = max(TOTAL_ACCIONES, TOTAL_CON_WLS)
    else:
        pool = list(temas)
        total = TOTAL_ACCIONES
    monedas = sorted({SUF2MON[s_][0] for t in pool for s_ in SUF2MON if t.endswith(s_)})
    fx_t = [f"{mon}=X" for mon in monedas]
    todos = pool + [d for d in list(DRIVERS) + list(LIDERES_EXTRA) + [TASA] + fx_t if d not in pool]

    print(f"Descargando precios de {len(pool)} candidatas...")
    ohlc = None
    if es_demo:
        close, volu, info_demo = demo(todos, temas)
    else:
        ohlc = descargar(todos)
        # Bitcoin cotiza sabado y domingo: esos dias crean filas donde las acciones
        # quedan "planas" (0%). Solo se dejan los dias en que la bolsa abrio.
        acc = [c for c in ohlc["Close"].columns if not str(c).endswith("-USD")]
        dias_bolsa = ohlc["Close"][acc].notna().mean(axis=1) > 0.5
        ohlc = ohlc[dias_bolsa]
        close, volu = ohlc["Close"], ohlc["Volume"]

    fx = {mon: float(close[f"{mon}=X"].dropna().iloc[-1]) for mon in monedas
          if f"{mon}=X" in close and close[f"{mon}=X"].notna().any()}
    fac = {t: factor_usd(t, fx) for t in pool}
    if monedas:
        print(f"Monedas: {', '.join(f'{k} {v:.4g}' for k, v in fx.items())}")
    forzadas = list(dict.fromkeys([t for t in NUCLEO if t in temas] + list(equipo)))
    tickers = preseleccion(close, volu, pool, forzadas, total, frozenset(wls), fac)
    for t in tickers:
        origen[t] = "equipo" if t in equipo else "nucleo" if t in NUCLEO else "wls" if t in wls else "base" if t in sum(SEMILLA.values(), []) else "nueva"
    def bbg_de(t):
        if t in wls:
            return wls[t]
        if t in EQUIPO_BBG:
            return EQUIPO_BBG[t]
        for suf in SUF2MON:
            if t.endswith(suf):
                return t
        return f"{t.replace('-', '/')} US"
    print(f"Lista del dia: {len(tickers)} acciones ({sum(1 for t in tickers if origen[t]=='nueva')} nuevas)")

    if es_demo:
        info = {t: info_demo.get(t, {}) for t in tickers}
    else:
        print("Descargando datos y noticias de cada empresa (2-3 minutos)...")
        info = info_de(tickers)
    # tema para las nuevas segun su industria en Yahoo
    for t in tickers:
        if temas.get(t) == NUEVAS:
            temas[t] = tema_por_industria(info.get(t, {}).get("industria"), info.get(t, {}).get("sector")) if not es_demo else "Tecnología"

    tickers = [t for t in tickers if t in close and close[t].notna().sum() > 60]
    close = close.ffill()
    ret = close.pct_change(fill_method=None)
    ult = close.iloc[-1]
    hoy = close.index[-1].date()

    def var(t, n):
        s = close[t].dropna()
        return (s.iloc[-1] / s.iloc[-1 - n] - 1) * 100 if len(s) > n else np.nan

    m = pd.DataFrame(index=tickers)
    m["tema"] = [temas[t] for t in tickers]
    for col, n in [("r1d", 1), ("r1s", 5), ("r1m", 21), ("r3m", 63), ("r6m", 126)]:
        m[col] = [var(t, n) for t in tickers]
    m["vol20"] = ret[tickers].tail(20).std() * np.sqrt(252) * 100
    m["dd3m"] = (ult / close.tail(63).max() - 1)[tickers] * 100
    m["dist52"] = (ult / close.tail(252).max() - 1)[tickers] * 100
    m["sma20"] = (ult / close.tail(20).mean() - 1)[tickers] * 100
    m["sma50"] = (ult / close.tail(50).mean() - 1)[tickers] * 100
    m["rsi"] = [rsi(close[t].dropna()).iloc[-1] for t in tickers]
    m["volRatio"] = (volu[tickers].tail(5).mean() / volu[tickers].tail(50).mean())
    m["liq"] = (close[tickers] * volu[tickers]).tail(20).mean() / 1e6 * pd.Series({t: (fac.get(t) or 1.0) for t in tickers})
    rm = ret["ACWI"]
    m["beta"] = [ret[t].tail(120).cov(rm.tail(120)) / rm.tail(120).var() for t in tickers]
    m["relMkt1m"] = m["r1m"] - var("ACWI", 21)
    m["short"] = [info.get(t, {}).get("short") for t in tickers]
    m["earn"] = [info.get(t, {}).get("earn") for t in tickers]

    def en_ventana(d):
        return isinstance(d, str) and VENTANA_INI.isoformat() <= d <= VENTANA_FIN.isoformat()
    m["enVentana"] = m["earn"].apply(en_ventana)
    liquida = m["liq"] >= LIQUIDEZ_MIN_USD_MM
    m["puntaje"] = (0.35 * zscore(m["vol20"]) + 0.25 * zscore(m["r1m"])
                    + 0.15 * zscore(m["short"]) + 0.10 * zscore(m["beta"])
                    + 1.0 * m["enVentana"].astype(float) - 2.0 * (~liquida).astype(float))
    m = m.sort_values("puntaje", ascending=False)

    # correlaciones y grupos finos
    corr = ret[tickers].tail(90).corr()
    try:
        from scipy.cluster.hierarchy import fcluster, linkage, leaves_list
        from scipy.spatial.distance import squareform
        d = np.array((1 - corr.fillna(0)).clip(lower=0).values, dtype=float, copy=True)
        np.fill_diagonal(d, 0)
        d = (d + d.T) / 2
        Z = linkage(squareform(d, checks=False), method="average")
        grupos = pd.Series(fcluster(Z, t=0.42, criterion="distance"), index=tickers)
        orden = [tickers[i] for i in leaves_list(Z)]
    except ImportError:
        grupos = pd.Series(pd.factorize(m.loc[tickers, "tema"])[0] + 1, index=tickers)
        orden = sorted(tickers, key=lambda t: grupos[t])
    tam = grupos.value_counts()
    grupos = grupos.map({g: i + 1 for i, g in enumerate(tam.index)})

    kronos = correr_kronos(ohlc, close, list(m.index), es_demo)

    print("Calculando efecto contagio por resultados...")
    lideres = list(m.index) + [t for t in LIDERES_EXTRA if t in close]
    pasados, proximos = historial_reportes(lideres, es_demo)
    for t in m.index:  # el proximo reporte del radar ya viene de Yahoo info
        if isinstance(m.loc[t, "earn"], str):
            proximos[t] = m.loc[t, "earn"]
    nombres = {t: (info.get(t, {}).get("nombre") or t) for t in m.index}
    nombres.update(LIDERES_EXTRA)
    mapa = contagio(close, pasados, proximos, lideres, list(m.index), nombres, hoy)

    acciones = []
    for rank, t in enumerate(m.index, 1):
        row = m.loc[t]
        inf = info.get(t, {})
        betas, cors = {}, {}
        for dn in DRIVERS:
            if dn in ret:
                rd, rt = ret[dn].tail(90), ret[t].tail(90)
                betas[dn] = r(rt.cov(rd) / rd.var())
                cors[dn] = r(rt.corr(rd))
        principal = max(cors, key=lambda k: abs(cors[k] or 0))
        sensTasa = corrTasa = None
        if TASA in close:
            dt = close[TASA].diff().tail(250)
            rt = ret[t].tail(250)
            ok = dt.notna() & rt.notna()
            if ok.sum() > 100 and dt[ok].var() > 0:
                sensTasa = r(rt[ok].cov(dt[ok]) / dt[ok].var() * 0.10 * 100, 1)  # % por +0,10 pp
                corrTasa = r(rt[ok].corr(dt[ok]))
        earn = row["earn"] if isinstance(row["earn"], str) else None
        target = inf.get("target")
        a = {
            "t": t, "rank": rank, "nombre": inf.get("nombre") or t, "tema": row["tema"],
            "tkBBG": bbg_de(t), "bolsaBBG": bbg_de(t).split()[-1],
            "pais": inf.get("pais"), "bolsa": inf.get("bolsa"), "sector": inf.get("sector"), "industria": inf.get("industria"),
            "desc": inf.get("desc"), "web": inf.get("web"), "mcap": inf.get("mcap"),
            "precio": r(ult[t]), "r1d": r(row["r1d"], 1), "r1s": r(row["r1s"], 1),
            "r1m": r(row["r1m"], 1), "r3m": r(row["r3m"], 1), "r6m": r(row["r6m"], 1),
            "relMkt1m": r(row["relMkt1m"], 1),
            "vol20": r(row["vol20"], 0), "dd3m": r(row["dd3m"], 1), "dist52": r(row["dist52"], 1),
            "sma20": r(row["sma20"], 1), "sma50": r(row["sma50"], 1), "rsi": r(row["rsi"], 0),
            "volRatio": r(row["volRatio"], 1), "liq": r(row["liq"], 1), "beta": r(row["beta"]),
            "short": r(row["short"], 1), "earn": earn, "enVentana": bool(row["enVentana"]),
            "diasEarn": (date.fromisoformat(earn) - hoy).days if earn else None,
            "target": target, "upside": r((target / ult[t] - 1) * 100, 0) if target else None,
            "reco": inf.get("reco"), "nAnalistas": inf.get("nAnalistas"),
            "puntaje": r(row["puntaje"]), "grupo": int(grupos[t]),
            "driver": principal, "driverCorr": cors[principal], "betas": betas,
            "sensTasa": sensTasa, "corrTasa": corrTasa,
            "momentum": cuadrante(r(row["r1m"], 1), r(row["r3m"], 1)),
            "hist": [r(x) for x in close[t].tail(60).tolist()],
            "noticias": inf.get("noticias") or [],
            "motivo": motivos.get(t) if origen.get(t) in ("nueva", "equipo") else None,
            "origen": origen.get(t, "base"),
            "enWLS": (t in lista_wls) if lista_wls else None,
            "kronos": kronos.get(t),
        }
        a["senales"] = senales(a)
        acciones.append(a)

    lista_g = []
    for g in sorted(grupos.unique()):
        ts = [t for t in orden if grupos[t] == g]
        sub = corr.loc[ts, ts].values
        intra = sub[np.triu_indices(len(ts), 1)].mean() if len(ts) > 1 else None
        lista_g.append({"g": int(g), "tickers": ts, "corr": r(intra),
                        "temas": sorted(set(temas[t] for t in ts))})

    mercado = []
    for dn, desc in DRIVERS.items():
        if dn in close:
            mercado.append({"t": dn, "nombre": desc, "precio": r(ult[dn]),
                            "r1d": r(var(dn, 1), 1), "r1s": r(var(dn, 5), 1), "r1m": r(var(dn, 21), 1),
                            "hist": [r(x) for x in close[dn].tail(60).tolist()]})
    if TASA in close and close[TASA].notna().sum() > 30:
        tz = close[TASA]
        bp = lambda n: r((tz.iloc[-1] - tz.iloc[-1 - n]) * 100, 0)
        mercado.append({"t": "10Y", "nombre": "Tasa 10 años EE.UU.", "tipo": "tasa",
                        "precio": r(tz.iloc[-1], 2), "r1d": bp(1), "r1s": bp(5), "r1m": bp(21),
                        "hist": [r(x, 3) for x in tz.tail(60).tolist()]})

    return {
        "version": 2,
        "generado": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "ultimoCierre": hoy.isoformat(),
        "demo": es_demo,
        "fuente": "Datos de ejemplo simulados" if es_demo else "Yahoo Finance",
        "ventana": {"ini": VENTANA_INI.isoformat(), "fin": VENTANA_FIN.isoformat()},
        "liqMin": LIQUIDEZ_MIN_USD_MM,
        "nBase": sum(1 for t in tickers if origen.get(t) == "nucleo"),
        "nNuevas": sum(1 for t in tickers if origen.get(t) == "nueva"),
        "nEquipo": sum(1 for t in tickers if origen.get(t) == "equipo"),
        "nDinamicas": sum(1 for t in tickers if origen.get(t) in ("base", "nueva")),
        "nWLS": sum(1 for t in tickers if origen.get(t) == "wls"),
        "nListaWLS": len(wls),
        "kronos": bool(kronos),
        "contagio": mapa,
        "macro": EVENTOS_MACRO,
        "drivers": DRIVERS,
        "mercado": mercado,
        "fechas": [d.strftime("%Y-%m-%d") for d in close.index[-60:]],
        "acciones": acciones,
        "grupos": lista_g,
        "corr": {"tickers": orden, "m": [[r(corr.loc[a, b]) for b in orden] for a in orden]},
    }


# ---------------- UNIVERSO: todas las acciones del WLS (datos livianos, solo precios) ----------------
UNIVERSO_TXT = "universo.txt"


def leer_universo():
    """universo.txt (+ wls.txt + equipo.txt): simbolo Yahoo -> (ticker Bloomberg, nombre)."""
    out = {}
    for f in (UNIVERSO_TXT, WLS_TXT, EQUIPO_TXT):
        if not os.path.exists(f):
            continue
        for linea in open(f, encoding="utf-8"):
            linea = linea.split("#")[0].strip()
            if not linea:
                continue
            tk, _, nom = linea.partition("|")
            r_ = a_yahoo(tk.split(",")[0].strip())
            if r_ and r_[0] not in out:
                out[r_[0]] = (r_[1], nom.strip() or None)
    return out


_OPENS = []   # precios de apertura de la ultima descarga grande (para estudiar cuanto duran las olas)


def _bajar(tickers, periodo, lote=200, hilos=8, reintentar=True):
    """Descarga en lotes chicos y con pausas (Yahoo limita si se le piden miles de acciones de golpe).
    Devuelve (close, volume) con una columna por ticker. Reintenta una vez las que no llegaron."""
    import yfinance as yf
    cls, vols = [], []
    for i in range(0, len(tickers), lote):
        parte = tickers[i:i + lote]
        df = pd.DataFrame()
        for intento in range(2):
            try:
                df = yf.download(parte, period=periodo, interval="1d", auto_adjust=True, progress=False,
                                 threads=hilos, group_by="column")
                break
            except Exception as e:
                print(f"  lote {i}: {e.__class__.__name__}")
                time.sleep(30)
        time.sleep(4)
        if df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            cls.append(df["Close"]); vols.append(df["Volume"])
            if "Open" in df.columns.get_level_values(0):
                _OPENS.append(df["Open"])
        else:
            cls.append(df[["Close"]].rename(columns={"Close": parte[0]}))
            vols.append(df[["Volume"]].rename(columns={"Volume": parte[0]}))
    close = pd.concat(cls, axis=1) if cls else pd.DataFrame()
    volu = pd.concat(vols, axis=1) if vols else pd.DataFrame()
    close = close.loc[:, ~close.columns.duplicated()] if not close.empty else close
    volu = volu.loc[:, ~volu.columns.duplicated()] if not volu.empty else volu
    faltan = [t for t in tickers if t not in close or close[t].notna().sum() == 0]
    if reintentar and faltan and len(faltan) < len(tickers):
        print(f"  {len(faltan)} sin datos: reintento en 45 s, mas despacio...")
        time.sleep(45)
        c2, v2 = _bajar(faltan, periodo, lote=100, hilos=4, reintentar=False)
        if not c2.empty:
            close = pd.concat([close.drop(columns=[c for c in c2.columns if c in close]), c2], axis=1)
            volu = pd.concat([volu.drop(columns=[c for c in v2.columns if c in volu]), v2], axis=1)
    return close, volu


UCOLS = ["t", "bbg", "nombre", "bolsa", "precio", "r1d", "r1s", "r1m", "r3m", "vol20", "liq", "rsi", "dist52", "momentum", "fecha",
         "r1y", "vol90", "beta", "pxusd", "corr", "volprop", "vavg20", "volx", "volx5"]


def construir_universo(solo=None):
    U = leer_universo()
    if not U:
        return None
    ts = [t for t in U if t in solo] if solo else list(U)
    _OPENS.clear()
    print(f"Universo WLS: descargando {len(ts)} acciones...")
    close, volu = _bajar(ts + ["ACWI"], "1y")
    betas, corrs, mktvol = {}, {}, None
    if "ACWI" in close:   # beta contra el mercado global, ultimos ~120 dias (calculo vectorizado)
        rets = close.ffill(limit=2).pct_change(fill_method=None).tail(120)
        m_ = rets["ACWI"]
        ok = rets.notna() & m_.notna().values[:, None]
        rc, mc = rets.where(ok), pd.DataFrame(np.repeat(m_.values[:, None], rets.shape[1], 1), index=rets.index, columns=rets.columns).where(ok)
        n_ = ok.sum()
        cov = ((rc - rc.mean()) * (mc - mc.mean())).sum() / (n_ - 1)
        var_m = mc.var()
        b_ = (cov / var_m).where(n_ > 40)
        betas = {k: float(v) for k, v in b_.items() if pd.notna(v)}
        c_ = (cov / (rc.std() * mc.std())).where(n_ > 40)
        corrs = {k: float(v) for k, v in c_.items() if pd.notna(v)}
        mktvol = float(m_.dropna().tail(63).std() * np.sqrt(252) * 100)
    monedas = sorted({SUF2MON[s_][0] for t in ts for s_ in SUF2MON if t.endswith(s_)})
    fxc, _ = _bajar([f"{m}=X" for m in monedas], "5d")
    fx = {m: float(fxc[f"{m}=X"].dropna().iloc[-1]) for m in monedas if f"{m}=X" in fxc and fxc[f"{m}=X"].notna().any()}
    filas = []
    for t in ts:
        if t not in close:
            continue
        s_ = close[t].dropna()
        if len(s_) < 2:
            continue
        v_ = volu[t].reindex(s_.index).fillna(0) if t in volu else None
        px = float(s_.iloc[-1])
        var = lambda n: (px / float(s_.iloc[-1 - n]) - 1) * 100 if len(s_) > n else None
        rt = s_.pct_change().tail(20)
        fac = factor_usd(t, fx)
        liq = float((s_ * v_).tail(20).mean()) * fac / 1e6 if (v_ is not None and fac) else None
        r1m, r3m = var(21), var(63)
        try:
            rs = float(rsi(s_).iloc[-1]) if len(s_) > 20 else None
        except Exception:
            rs = None
        bbg, nom = U[t]
        r1y = (px / float(s_.iloc[0]) - 1) * 100 if len(s_) > 200 else None
        va20 = float(v_.iloc[-21:-1].mean()) if v_ is not None and len(v_) > 21 else None
        va20 = va20 if va20 and va20 > 0 else None
        rt90 = s_.pct_change().tail(63)
        beta = betas.get(t)
        filas.append([t, bbg, nom, bbg.split()[-1], r(px), r(var(1), 1), r(var(5), 1), r(r1m, 1), r(r3m, 1),
                      r(float(rt.std()) * np.sqrt(252) * 100, 0) if len(rt) > 5 else None, r(liq, 1), r(rs, 0),
                      r((px / float(s_.max()) - 1) * 100, 1), cuadrante(r(r1m, 1), r(r3m, 1)) if r1m is not None and r3m is not None else None,
                      s_.index[-1].date().isoformat(),
                      r(r1y, 1), r(float(rt90.std()) * np.sqrt(252) * 100, 0) if len(rt90) > 20 else None, r(beta, 2),
                      r(px * fac, 2) if fac else None,
                      r(corrs.get(t), 2),
                      r(float(rt90.std()) * np.sqrt(252) * 100 * np.sqrt(max(0.0, 1 - corrs[t] ** 2)), 0) if t in corrs and len(rt90) > 20 else None,
                      r(va20, 0), r(float(v_.iloc[-1]) / va20, 1) if va20 else None,
                      r(float(v_.iloc[-5:].mean()) / float(v_.iloc[-25:-5].mean()), 1) if v_ is not None and len(v_) > 25 and float(v_.iloc[-25:-5].mean()) > 0 else None])
    print(f"Universo WLS: {len(filas)} de {len(ts)} con precios")
    ola_stats, ola_t, ola_s = {}, {}, {}
    try:
        if _OPENS:
            opens = pd.concat(_OPENS, axis=1)
            opens = opens.loc[:, ~opens.columns.duplicated()]
            ola_stats, ola_t, ola_s = estudio_olas(close, volu, opens, ts)
            print(f"Estudio de olas: {sum(v['n'] for v in ola_stats.values())} olas en el ultimo ano")
    except Exception as e:
        print(f"Estudio de olas omitido: {e}")
    _OPENS.clear()
    return {"olaStats": ola_stats, "olaTicker": ola_t, "olaStatsSem": ola_s, "generado": datetime.now(timezone.utc).isoformat(timespec="minutes"), "n": len(ts),
            "completo": datetime.now(timezone.utc).isoformat(timespec="minutes"), "mktvol": r(mktvol, 1),
            "indice": "ACWI (aprox. del WLS)",
            "cols": UCOLS, "filas": filas}


ASIA = (".T", ".KS", ".KQ", ".TW", ".TWO", ".HK", ".SS", ".SZ", ".NS", ".BO", ".JK", ".BK", ".SI", ".KL", ".PS", ".AX", ".NZ", ".VN")
AMERICA = (".TO", ".SA", ".MX", ".SN", ".CL")


def _abierta_ahora(t, h):
    """Region del ticker con la bolsa abierta (o recien cerrada) a la hora UTC h."""
    suf = "." + t.rsplit(".", 1)[1] if "." in t else ""
    if suf in ASIA:
        return h >= 23 or h < 10
    if suf == "" or suf in AMERICA:
        return 13 <= h < 23
    return 6 <= h < 18          # Europa, Medio Oriente y Africa


def _region(t):
    suf = "." + t.rsplit(".", 1)[1] if "." in t else ""
    return "Asia" if suf in ASIA else "América" if (suf == "" or suf in AMERICA) else "Europa y otros"


def estudio_olas(close, volu, opens, tickers):
    """Que paso despues de cada 'ola' del ultimo ano (dia >= +3% con volumen >= 1,5x):
    comprando en la apertura siguiente y vendiendo al cierre del dia 1, 2, 3, 4, 5, 7 o 10."""
    H = (1, 2, 3, 4, 5, 7, 10)
    HM = max(H)
    por_reg, por_t, base, por_reg_s = {}, {}, {}, {}
    for t in tickers:
        if t not in close or t not in opens or t not in volu:
            continue
        c = close[t].dropna()
        if len(c) < 60:
            continue
        o = opens[t].reindex(c.index).values.astype(float)
        v = volu[t].reindex(c.index).fillna(0).values.astype(float)
        cv = c.values.astype(float)
        r1 = np.r_[np.nan, cv[1:] / cv[:-1] - 1]
        va = pd.Series(v).rolling(20).mean().shift(1).values
        # linea base: lo mismo para cualquier dia (para ver si la ola agrega algo)
        idx_all = np.arange(20, len(cv) - HM)
        ent_all = o[idx_all + 1]
        okb = ent_all > 0
        if okb.any():
            B = np.column_stack([np.clip(cv[idx_all[okb] + h] / ent_all[okb] - 1, -0.5, 1.0) for h in H])
            sb = base.setdefault(_region(t), [np.zeros(len(H)), 0])
            sb[0] += B.sum(axis=0); sb[1] += len(B)
        # olas de la semana: +8% en 5 sesiones con volumen de la semana >= 1,3x (solo el primer dia de cada racha)
        r5 = np.r_[[np.nan] * 5, cv[5:] / cv[:-5] - 1]
        v5 = pd.Series(v).rolling(5).mean().values
        vb = pd.Series(v).rolling(20).mean().shift(5).values
        es = (r5 >= 0.08) & (vb > 0) & (v5 / np.where(vb > 0, vb, np.nan) >= 1.3)
        evs = np.where(es & ~np.r_[False, es[:-1]])[0]
        evs = evs[evs + HM < len(cv)]
        fs = []
        for i in evs:
            ent = o[i + 1]
            if ent > 0:
                fs.append(np.clip([ent / cv[i] - 1] + [cv[i + h] / ent - 1 for h in H], -0.5, 1.0))
        if fs:
            por_reg_s.setdefault(_region(t), []).append(np.array(fs))
        ev = np.where((r1 >= 0.03) & (va > 0) & (v / np.where(va > 0, va, np.nan) >= 1.5))[0]
        ev = ev[ev + HM < len(cv)]
        if not len(ev):
            continue
        filas = []
        for i in ev:
            ent = o[i + 1]
            if not (ent > 0):
                continue
            gap = ent / cv[i] - 1
            fw = [cv[i + h] / ent - 1 for h in H]
            vals = np.clip([gap] + fw, -0.5, 1.0)
            filas.append(vals)
        if not filas:
            continue
        A = np.array(filas)
        por_reg.setdefault(_region(t), []).append(A)
        if len(A) >= 3:
            por_t[t] = [len(A), r(A[:, 1].mean() * 100, 1), r(A[:, 3].mean() * 100, 1), r((A[:, 3] > 0).mean() * 100, 0)]
    def resumen(dic):
        out = {}
        for reg, lst in dic.items():
            A = np.vstack(lst)
            med = A.mean(axis=0) * 100
            sd = A.std(axis=0) * 100
            b_ = base.get(reg)
            bm = (b_[0] / b_[1] * 100) if b_ and b_[1] else np.zeros(len(H))
            o_ = {"n": int(len(A)), "gap": r(med[0], 2), "dias": list(H)}
            for k, h in enumerate(H):
                o_[f"d{h}"] = r(med[k + 1], 2)
                o_[f"base{h}"] = r(bm[k], 2)
                o_[f"pos{h}"] = r((A[:, k + 1] > 0).mean() * 100, 0)
                o_[f"sd{h}"] = r(sd[k + 1], 2)
            o_["pico"] = H[int(np.argmax(med[1:] - bm))]
            out[reg] = o_
        return out
    stats = resumen(por_reg)
    stats_s = resumen(por_reg_s)
    return stats, por_t, stats_s


def ruido_redes(previo=None):
    """Menciones en redes de acciones de EE.UU. (solo EE.UU.: las fuentes publicas gratuitas no cubren Asia ni Europa).
    - ApeWisdom (apewisdom.io): cuenta menciones en Reddit (r/wallstreetbets, r/stocks, etc.) en las ultimas 24 h.
    - StockTwits (stocktwits.com): lista de simbolos en tendencia.
    Si una fuente no responde, se mantiene lo ultimo que se tenia."""
    import urllib.request
    prev = (previo or {}).get("redes") or {}
    if prev and _edad_min(prev.get("hora") or "") < 55:
        return prev
    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (radar-gtc)", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r_:
            return json.loads(r_.read().decode("utf-8"))
    tk, fuentes = {}, []
    try:
        for pag in (1, 2):
            j = get(f"https://apewisdom.io/api/v1.0/filter/all-stocks/page/{pag}")
            for x in j.get("results", []):
                sym = str(x.get("ticker", "")).upper().replace(".", "-")
                if sym:
                    tk[sym] = {"m": int(x.get("mentions") or 0), "m24": int(x.get("mentions_24h_ago") or 0),
                               "rank": int(x.get("rank") or 999)}
        fuentes.append("Reddit vía ApeWisdom")
    except Exception as e:
        print(f"ApeWisdom no disponible: {e}")
    try:
        j = get("https://api.stocktwits.com/api/2/trending/symbols.json")
        for i, x in enumerate(j.get("symbols", [])):
            sym = str(x.get("symbol", "")).upper().replace(".", "-")
            if sym:
                tk.setdefault(sym, {"m": 0, "m24": 0, "rank": 999})["st"] = i + 1
        fuentes.append("StockTwits")
    except Exception as e:
        print(f"StockTwits no disponible: {e}")
    if not tk:
        return prev
    print(f"Redes: {len(tk)} acciones de EE.UU. con menciones ({', '.join(fuentes)})")
    return {"hora": datetime.now(timezone.utc).isoformat(timespec="minutes"), "fuentes": fuentes, "tickers": tk}


def tendencias(u, previo=None, n=20):
    """Acciones del WLS 'en ola': suben fuerte en su ultima sesion con volumen inusual (aunque su bolsa ya cerro).
    Para cada una se buscan titulares que expliquen el movimiento."""
    if not u or not u.get("filas"):
        return u
    import yfinance as yf
    ix = {c: i for i, c in enumerate(u["cols"])}
    g = lambda f, c: f[ix[c]] if c in ix else None
    cand = []
    for f in u["filas"]:
        r1d, vx, px, lq = g(f, "r1d"), g(f, "volx"), g(f, "pxusd"), g(f, "liq")
        if r1d is None or r1d < 3 or (px is not None and px < 5) or (lq is not None and lq < 2):
            continue
        vx = vx or 1.0
        if vx < 1.5:
            continue
        cand.append((r1d * min(vx, 6) ** 0.5 + 0.2 * (g(f, "r1s") or 0), f))
    cand.sort(key=lambda x: -x[0])
    viejos = {d["t"]: d for d in (previo or {}).get("tendencia", [])}
    out = []
    for sc, f in cand[:n]:
        t = f[0]
        d = {"t": t, "puntos": r(sc, 1)}
        v = viejos.get(t)
        if v and v.get("noticias") and _edad_min(v.get("hora") or "") < 360:
            d["noticias"], d["hora"] = v["noticias"], v["hora"]
        else:
            try:
                d["noticias"] = (leer_noticias(yf.Ticker(t), t, g(f, "nombre")) or [])[:3]
            except Exception:
                d["noticias"] = []
            d["hora"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
        out.append(d)
    u["tendencia"] = out
    # olas de la semana
    cs = []
    for f in u["filas"]:
        r1s, v5, px, lq, r1d = g(f, "r1s"), g(f, "volx5"), g(f, "pxusd"), g(f, "liq"), g(f, "r1d")
        if r1s is None or r1s < 8 or (v5 or 0) < 1.3 or (r1d is not None and r1d < -2) or (px is not None and px < 5) or (lq is not None and lq < 2):
            continue
        cs.append((r1s * min(v5, 4) ** 0.5, f))
    cs.sort(key=lambda x: -x[0])
    viejos_s = {d["t"]: d for d in (previo or {}).get("tendenciaSemana", [])}
    sem = []
    for sc, f in cs[:n]:
        t = f[0]
        d = {"t": t, "puntos": r(sc, 1)}
        v = viejos_s.get(t) or viejos.get(t) or next((x for x in out if x["t"] == t), None)
        if v and v.get("noticias") and _edad_min(v.get("hora") or "") < 360:
            d["noticias"], d["hora"] = v["noticias"], v["hora"]
        else:
            try:
                d["noticias"] = (leer_noticias(yf.Ticker(t), t, g(f, "nombre")) or [])[:3]
            except Exception:
                d["noticias"] = []
            d["hora"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
        sem.append(d)
    u["tendenciaSemana"] = sem
    try:
        u["redes"] = ruido_redes(previo or u)
    except Exception as e:
        print(f"Redes omitidas: {e}")
    for k in ("olaStats", "olaTicker", "olaStatsSem"):
        if not u.get(k) and (previo or {}).get(k):
            u[k] = previo[k]
    print(f"Tendencias: {len(out)} acciones en ola")
    return u


def unir_universo(nuevo, previo):
    """Si Yahoo no entrego algunas acciones (limite de descargas), se mantienen sus datos anteriores
    en vez de que desaparezcan de la pagina. Se completan en la proxima descarga."""
    if not nuevo or not nuevo.get("filas"):
        return previo
    if not previo or not previo.get("filas"):
        return nuevo
    hay = {f[0] for f in nuevo["filas"]}
    ix_p = {c: i for i, c in enumerate(previo.get("cols", []))}
    viejas = []
    for f in previo["filas"]:
        if f[0] in hay:
            continue
        viejas.append([f[ix_p[c]] if c in ix_p and ix_p[c] < len(f) else None for c in nuevo["cols"]])
    if viejas:
        print(f"Universo: {len(viejas)} acciones sin datos nuevos de Yahoo; se mantienen las anteriores")
    nuevo["filas"] += viejas
    nuevo["sinActualizar"] = len(viejas)
    return nuevo


def rellenar_universo(u, maximo=700):
    """Descarga las acciones de universo.txt que faltan en la pagina (por limites de Yahoo), de a 700 por vez."""
    try:
        todos = leer_universo() or {}
        if not u or not u.get("filas") or not todos:
            return u
        hay = {f[0] for f in u["filas"]}
        pedidas = leer_pedidas()
        faltan = sorted([t for t in todos if t not in hay], key=lambda t: t not in pedidas)   # primero las pedidas
        if len(faltan) < 20 or _edad_min(u.get("relleno") or "") < 50:
            return u
        print(f"Universo: faltan {len(faltan)} acciones; se descargan {min(len(faltan), maximo)}")
        time.sleep(20)
        parte = construir_universo(solo=set(faltan[:maximo]))
        if parte and parte.get("filas"):
            ix_p = {c: i for i, c in enumerate(parte["cols"])}
            u["filas"] += [[f[ix_p[c]] if c in ix_p else None for c in u["cols"]] for f in parte["filas"]]
            print(f"Universo: +{len(parte['filas'])} acciones (total {len(u['filas'])} de {len(todos)})")
        u["relleno"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    except Exception as e:
        print(f"Relleno del universo fallo ({e.__class__.__name__}: {e})")
    return u


def rapido_universo(u):
    if not u or not u.get("filas"):
        return u
    ix = {c: i for i, c in enumerate(u["cols"])}
    h = datetime.now(timezone.utc).hour
    ts = [f[0] for f in u["filas"] if _abierta_ahora(f[0], h)]
    if not ts:
        return u
    print(f"Universo rapido: {len(ts)} acciones con su bolsa abierta")
    close, volq = _bajar(ts, "7d", lote=250, reintentar=False)
    n = 0
    for f in u["filas"]:
        t = f[0]
        if t not in close:
            continue
        s_ = close[t].dropna()
        if len(s_) < 2:
            continue
        f[ix["precio"]] = r(float(s_.iloc[-1]))
        f[ix["r1d"]] = r((float(s_.iloc[-1]) / float(s_.iloc[-2]) - 1) * 100, 1)
        f[ix["fecha"]] = s_.index[-1].date().isoformat()
        if "volx" in ix and f[ix["vavg20"]] and t in volq:
            vv = volq[t].reindex(s_.index).dropna()
            if len(vv):
                f[ix["volx"]] = r(float(vv.iloc[-1]) / f[ix["vavg20"]], 1)
        n += 1
    u["generado"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    u["rapido"] = u["generado"]
    print(f"Universo WLS rapido: {n} precios")
    return u


# ---------------- CANDIDATAS para la Mesa de decisiones (mesa.html) ----------------

def resultados_trimestrales(tk):
    """Ultimos 5 trimestres: [fecha, ventas, utilidad neta] en millones de la moneda del reporte."""
    try:
        q = tk.quarterly_income_stmt
        if q is None or q.empty:
            return None
        fila = lambda *nombres: next((q.loc[n] for n in nombres if n in q.index), None)
        ven = fila("Total Revenue", "Operating Revenue")
        uti = fila("Net Income", "Net Income Common Stockholders")
        out = []
        for c in sorted(q.columns)[-5:]:
            v = ven.get(c) if ven is not None else None
            u = uti.get(c) if uti is not None else None
            out.append([pd.Timestamp(c).date().isoformat(), r(v / 1e6, 1) if v is not None and pd.notna(v) else None,
                        r(u / 1e6, 1) if u is not None and pd.notna(u) else None])
        return out
    except Exception:
        return None


def sensibilidades(close, ts):
    """Para cada accion (en dolares): como se mueve con el WLS (ACWI), con el miedo (VIX) y con el dolar (DXY).
    Usa retornos semanales de 1 ano (las bolsas de Asia y EE.UU. cierran a distinta hora, asi se evita el desfase)."""
    out = {}
    c = close.ffill(limit=3)
    sem = c.resample("W-FRI").last()
    ref = {k: sem[k].pct_change(fill_method=None) for k in ("ACWI", "^VIX", "DX-Y.NYB") if k in sem}
    for t in ts:
        if t not in c or c[t].notna().sum() < 60:
            continue
        mon = next((SUF2MON[s_] for s_ in SUF2MON if t.endswith(s_)), None)
        px = c[t]
        if mon and f"{mon[0]}=X" in c:
            px = px / (c[f"{mon[0]}=X"] * mon[1])   # precio en dolares
        rs = px.resample("W-FRI").last().pct_change(fill_method=None)
        o = {"mon": mon[0] if mon else "USD"}
        for k, nom in (("ACWI", "Wls"), ("^VIX", "Vix"), ("DX-Y.NYB", "Dxy")):
            if k not in ref:
                continue
            j = pd.concat([rs, ref[k]], axis=1).dropna()
            if len(j) < 20 or j.iloc[:, 1].std() == 0:
                continue
            cv = np.cov(j.iloc[:, 0], j.iloc[:, 1])
            o["beta" + nom] = r(cv[0, 1] / cv[1, 1], 2)
            o["corr" + nom] = r(j.iloc[:, 0].corr(j.iloc[:, 1]), 2)
        # grafico: accion en dolares vs ACWI (aprox. del WLS), ambos en base 100, ultimos ~6 meses
        if "ACWI" in c:
            j = pd.concat([px, c["ACWI"]], axis=1).dropna().tail(125)
            if len(j) > 20:
                o["vs"] = [[r(a / j.iloc[0, 0] * 100, 1) for a in j.iloc[:, 0]], [r(b / j.iloc[0, 1] * 100, 1) for b in j.iloc[:, 1]]]
                o["vsIni"] = j.index[0].date().isoformat()
        out[t] = o
    return out


def pre_olas(uni, n=25):
    """Acciones que todavia NO subieron fuerte pero muestran senales que suelen venir antes de una ola:
    cerca de su maximo de 52 semanas, volumen creciendo, tendencia de fondo positiva y volatilidad 'apretada'."""
    ix = {c: i for i, c in enumerate(uni["cols"])}
    g = lambda f, c: f[ix[c]] if c in ix and ix[c] < len(f) else None
    out = []
    for f in uni["filas"]:
        liq, px = g(f, "liq") or 0, g(f, "pxusd") or 0
        r1d, r1s, r1m, r3m = g(f, "r1d"), g(f, "r1s"), g(f, "r1m"), g(f, "r3m")
        if liq < 2 or px < 5 or r1d is None or r1s is None:
            continue
        if r1d >= 3 or r1s >= 8:          # ya esta en ola: eso lo cubren las otras listas
            continue
        pts, sen = 0.0, []
        d52, vx, vx5, rs, v20, v90 = g(f, "dist52"), g(f, "volx"), g(f, "volx5"), g(f, "rsi"), g(f, "vol20"), g(f, "vol90")
        if d52 is not None and d52 >= -8:
            pts += 1 + (0.5 if d52 >= -3 else 0)
            sen.append(f"a {abs(d52):.0f}% de su máximo de 52 semanas" if d52 < -0.5 else "en su máximo de 52 semanas")
        if vx5 is not None and vx5 >= 1.3:
            pts += 1
            sen.append(f"volumen de la semana {vx5:.1f}× lo normal sin haber subido fuerte (alguien está comprando)")
        if vx is not None and vx >= 1.5 and 0 < r1d < 3:
            pts += 1
            sen.append(f"hoy {vx:.1f}× su volumen con alza moderada ({r1d:+.1f}%)")
        if (r1m or 0) > 0 and (r3m or 0) > 0:
            pts += 1
            sen.append(f"tendencia de fondo positiva (mes {r1m:+.0f}%, 3 meses {r3m:+.0f}%)")
        if rs is not None:
            if 50 <= rs <= 68:
                pts += 0.5
                sen.append(f"RSI {rs:.0f}: con fuerza pero sin estar sobrecomprada")
            elif rs >= 75:
                pts -= 1
        if v20 and v90 and v20 < 0.75 * v90:
            pts += 0.5
            sen.append("se está moviendo menos que de costumbre (suele venir antes de un salto)")
        if pts >= 3:
            out.append((pts, f[0], sen))
    out.sort(key=lambda x: -x[0])
    return {t: {"pts": round(p_, 1), "senales": sen} for p_, t, sen in out[:n]}


def construir_candidatas(uni, previo=None, maximo=140):
    """Elige ~90 acciones para analizar a fondo: olas de hoy y de la semana, las mejores por factores de precio
    y la cartera actual. Para cada una trae analistas, resultados, noticias, grafico de 6 meses y relacionadas."""
    import yfinance as yf
    if not uni or not uni.get("filas"):
        return previo
    ix = {c: i for i, c in enumerate(uni["cols"])}
    g = lambda f, c: f[ix[c]] if c in ix and ix[c] < len(f) else None
    filas = {f[0]: f for f in uni["filas"]}
    origen = {}
    for d in uni.get("tendencia", []):
        origen.setdefault(d["t"], set()).add("ola-hoy")
    for d in uni.get("tendenciaSemana", []):
        origen.setdefault(d["t"], set()).add("ola-semana")
    # mejores por factores de precio (momentum 1 ano - 1 mes, volatilidad 90d, beta), liquidas y >= US$5
    ok = [f for f in uni["filas"] if (g(f, "liq") or 0) >= 2 and (g(f, "pxusd") or 0) >= 5
          and g(f, "r1y") is not None and g(f, "r1m") is not None and g(f, "vol90") is not None]
    if ok:
        def z(vals):
            v = np.array([x if x is not None else np.nan for x in vals], float)
            m, sd = np.nanmean(v), np.nanstd(v) or 1
            return np.clip(np.nan_to_num((v - m) / sd), -3, 3)
        pre = (0.25 * z([g(f, "r1y") - g(f, "r1m") for f in ok]) + 0.20 * z([g(f, "vol90") for f in ok])
               + 0.15 * z([g(f, "beta") for f in ok]))
        for k in np.argsort(-pre)[:40]:
            origen.setdefault(ok[k][0], set()).add("factores")
    try:
        pre = pre_olas(uni)
    except Exception as e:
        print(f"  pre-olas fallo ({e})")
        pre = {}
    for t in pre:
        origen.setdefault(t, set()).add("pre-ola")
    for t in leer_equipo():
        origen.setdefault(t, set()).add("cartera")
    pedidas = leer_pedidas()
    for t in pedidas:
        origen.setdefault(t, set()).add("pedida")
    # memoria: las que estuvieron en ola en los ultimos 7 dias siguen analizandose (para poder seguirlas despues de comprar)
    hoy_iso = datetime.now(timezone.utc).date().isoformat()
    lim = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    memoria = {t: f for t, f in ((previo or {}).get("memoria") or {}).items() if f >= lim}
    for t, o_ in origen.items():
        if o_ & {"ola-hoy", "ola-semana"}:
            memoria[t] = hoy_iso
    for t, f in memoria.items():
        if t not in origen or not (origen[t] & {"ola-hoy", "ola-semana"}):
            origen.setdefault(t, set()).add("reciente")
    prio = lambda t: (0 if origen[t] & {"cartera", "pedida"} else 1 if origen[t] & {"ola-hoy", "ola-semana"} else 2 if origen[t] & {"pre-ola", "reciente"} else 3)
    ts = sorted([t for t in origen if t in filas], key=prio)[:maximo]
    viejos = {d["t"]: d for d in (previo or {}).get("items", [])}
    noticias_ola = {d["t"]: d for d in uni.get("tendencia", []) + uni.get("tendenciaSemana", [])}
    print(f"Candidatas: {len(ts)} acciones")
    # grafico de 6 meses y relacionadas (correlacion de 90 dias entre las candidatas)
    monedas = sorted({SUF2MON[s_][0] for t in ts for s_ in SUF2MON if t.endswith(s_)})
    refs = ["ACWI", "^VIX", "DX-Y.NYB"] + [f"{m}=X" for m in monedas]
    close, _ = _bajar(ts + refs, "1y", lote=100, reintentar=False)
    sens = sensibilidades(close, ts) if not close.empty else {}
    close = close[[c for c in close.columns if c in ts]] if not close.empty else close
    rets = close.ffill(limit=2).pct_change(fill_method=None).tail(90) if not close.empty else pd.DataFrame()
    corr = rets.corr(min_periods=40) if not rets.empty else pd.DataFrame()
    items = []
    for t in ts:
        f, v = filas[t], viejos.get(t) or {}
        it = {"t": t, "bbg": g(f, "bbg"), "nombre": g(f, "nombre"), "origen": sorted(origen[t])}
        # analistas y resultados: se reutilizan 12 horas
        if v.get("info") and (v["info"].get("nombre") or v["info"].get("reco")) and _edad_min(v.get("infoHora") or "") < 720:
            it["info"], it["infoHora"] = v["info"], v["infoHora"]
        else:
            inf = {}
            try:
                time.sleep(0.4)
                tk = yf.Ticker(t)
                x = {}
                for intento in range(2):
                    try:
                        x = tk.info or {}
                    except Exception as e:
                        print(f"  {t}: info fallo ({e.__class__.__name__}), reintento")
                    if x.get("shortName") or x.get("longName") or x.get("recommendationKey"):
                        break
                    time.sleep(3)
                pxa = x.get("currentPrice") or x.get("regularMarketPrice")
                tgt = x.get("targetMeanPrice")
                ets = x.get("earningsTimestamp") or x.get("earningsTimestampStart")
                inf = {"nombre": x.get("shortName") or x.get("longName"), "sector": x.get("sector"), "industria": x.get("industry"),
                       "pais": x.get("country"), "desc": ((x.get("longBusinessSummary") or "").split(". ")[0])[:240] or None,
                       "reco": x.get("recommendationKey"), "recoMedia": r(x.get("recommendationMean"), 2),
                       "nAnalistas": x.get("numberOfAnalystOpinions"), "target": r(tgt),
                       "upside": r((tgt / pxa - 1) * 100, 1) if tgt and pxa else None,
                       "ventas": r((x.get("revenueGrowth") or 0) * 100, 1) if x.get("revenueGrowth") is not None else None,
                       "utilidad": r((x.get("earningsGrowth") or 0) * 100, 1) if x.get("earningsGrowth") is not None else None,
                       "margen": r((x.get("profitMargins") or 0) * 100, 1) if x.get("profitMargins") is not None else None,
                       "pe": r(x.get("trailingPE"), 1), "peFwd": r(x.get("forwardPE"), 1),
                       "earn": datetime.fromtimestamp(ets, timezone.utc).date().isoformat() if ets else None,
                       "mon": x.get("financialCurrency") or x.get("currency"), "mcap": x.get("marketCap"),
                       "trim": resultados_trimestrales(tk)}
            except Exception as e:
                print(f"  {t}: sin info ({e.__class__.__name__})")
            it["info"], it["infoHora"] = inf, datetime.now(timezone.utc).isoformat(timespec="minutes")
        # noticias: de la ola si ya las hay, si no se buscan (6 horas)
        nz = noticias_ola.get(t)
        if nz and nz.get("noticias"):
            it["noticias"] = nz["noticias"]
        elif v.get("noticias") is not None and _edad_min(v.get("notHora") or "") < 360:
            it["noticias"], it["notHora"] = v["noticias"], v.get("notHora")
        else:
            try:
                it["noticias"] = (leer_noticias(yf.Ticker(t), t, it["nombre"]) or [])[:4]
            except Exception:
                it["noticias"] = []
            it["notHora"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
        if t in close:
            h = close[t].dropna().tail(120)
            it["hist"] = [r(x, 4) for x in h.tolist()]
            it["histIni"] = h.index[0].date().isoformat() if len(h) else None
        if t in sens:
            it["sens"] = sens[t]
        if t in corr:
            c = corr[t].drop(labels=[t], errors="ignore").dropna().sort_values(ascending=False)
            it["rel"] = [[k, r(float(val), 2)] for k, val in c.head(3).items() if val >= 0.4]
        if "reciente" in origen[t]:
            it["olaFecha"] = memoria.get(t)
        if t in pedidas:
            it["pedida"] = pedidas[t]
        if t in pre:
            it["preola"] = pre[t]
        items.append(it)
    lim_h = (datetime.now(timezone.utc) - timedelta(days=21)).date().isoformat()
    hist = {t: h for t, h in ((previo or {}).get("historial") or {}).items() if (h.get("f") or "") >= lim_h}
    ahora_iso = datetime.now(timezone.utc).isoformat(timespec="minutes")
    for t in ts:
        tipos = origen[t] & {"pre-ola", "ola-hoy", "ola-semana"}
        if not tipos:
            continue
        tipo = "pre-ola" if "pre-ola" in tipos else "ola"
        h = hist.get(t)
        if not h or (h.get("tipo") != tipo and tipo == "ola" and h.get("tipo") == "pre-ola" and not h.get("fOla")):
            px_ = g(filas[t], "precio")
            if not h:
                hist[t] = {"f": ahora_iso, "px": px_, "tipo": tipo}
            else:
                h["fOla"], h["pxOla"] = ahora_iso, px_     # la pre-ola se convirtio en ola: se anota
    for t, h in hist.items():
        if t in filas:
            h["pxHoy"] = g(filas[t], "precio")
    return {"generado": ahora_iso, "items": items, "memoria": memoria, "historial": hist}



# ---------------- PANORAMA DEL MERCADO (para la Mesa de decisiones) ----------------
PANORAMA = {
    # indices
    "^GSPC": ("S&P 500", "indice"), "^IXIC": ("Nasdaq", "indice"), "^DJI": ("Dow Jones", "indice"),
    "^RUT": ("Russell 2000 (small caps)", "indice"), "ACWI": ("Mundo (ACWI ≈ WLS)", "indice"),
    "^STOXX50E": ("Euro Stoxx 50", "indice"), "^GDAXI": ("DAX Alemania", "indice"), "^FTSE": ("FTSE 100 Londres", "indice"),
    "^N225": ("Nikkei Japón", "indice"), "^KS11": ("KOSPI Corea", "indice"), "^TWII": ("Taiwán", "indice"),
    "^HSI": ("Hang Seng", "indice"), "000001.SS": ("Shanghai", "indice"), "^NSEI": ("Nifty India", "indice"),
    "^BVSP": ("Bovespa Brasil", "indice"), "^IPSA": ("IPSA Chile", "indice"),
    # riesgo y tasas
    "^VIX": ("VIX (índice del miedo)", "riesgo"), "^TNX": ("Tasa 10 años EE.UU.", "tasa"),
    # divisas (DXY: dolar contra 6 monedas; X=X: cuantas unidades locales por 1 dolar)
    "DX-Y.NYB": ("Dólar global (DXY)", "divisa"), "CLP=X": ("USD/CLP (peso chileno)", "divisa"),
    "EURUSD=X": ("EUR/USD (euro)", "divisa"), "JPY=X": ("USD/JPY (yen)", "divisa"), "KRW=X": ("USD/KRW (won)", "divisa"),
    "TWD=X": ("USD/TWD (dólar taiwanés)", "divisa"), "CNY=X": ("USD/CNY (yuan)", "divisa"), "INR=X": ("USD/INR (rupia)", "divisa"),
    "GBPUSD=X": ("GBP/USD (libra)", "divisa"), "BRL=X": ("USD/BRL (real)", "divisa"),
    # materias primas y cripto
    "CL=F": ("Petróleo WTI", "materia"), "GC=F": ("Oro", "materia"), "HG=F": ("Cobre", "materia"), "BTC-USD": ("Bitcoin", "materia"),
    # sectores de EE.UU. (ETF)
    "XLK": ("Tecnología", "sector"), "SMH": ("Semiconductores", "sector"), "XLF": ("Bancos y financieras", "sector"),
    "XLE": ("Energía", "sector"), "XLV": ("Salud", "sector"), "XLY": ("Consumo discrecional", "sector"),
    "XLP": ("Consumo básico", "sector"), "XLI": ("Industria", "sector"), "XLB": ("Materiales", "sector"),
    "XLU": ("Servicios básicos", "sector"), "XLRE": ("Inmobiliario", "sector"), "XLC": ("Comunicaciones", "sector"),
    # gigantes que mueven al Nasdaq y al S&P
    "NVDA": ("Nvidia", "gigante"), "MSFT": ("Microsoft", "gigante"), "AAPL": ("Apple", "gigante"), "AMZN": ("Amazon", "gigante"),
    "GOOGL": ("Alphabet (Google)", "gigante"), "META": ("Meta", "gigante"), "AVGO": ("Broadcom", "gigante"), "TSLA": ("Tesla", "gigante"),
}
INTRADIA = ["^IXIC", "^GSPC", "^VIX", "DX-Y.NYB", "^TNX"]
NOTICIAS_GENERALES = [
    ("stock market today", "en"), ("Nasdaq S&P 500 stocks why", "en"), ("Federal Reserve rates markets", "en"),
    ("dollar currency markets", "en"), ("Wall Street hoy bolsas", "es"),
]
TEMAS_NOTICIAS = {
    "Fed y tasas": r"\b(fed|fomc|powell|rate cut|rate hike|interest rate|tasas?|bond yield|treasur)",
    "Inflación": r"(inflation|cpi|pce|ppi|inflaci)",
    "Empleo": r"(jobs report|payroll|unemployment|jobless|empleo)",
    "Resultados de empresas": r"(earnings|results|quarter|guidance|revenue|beats|misses|resultados)",
    "IA y chips": r"(\bai\b|artificial intelligence|nvidia|chip|semiconductor|data center|openai)",
    "Petróleo y energía": r"(oil|crude|opec|petr[oó]leo|energy)",
    "China y comercio": r"(china|tariff|trade war|arancel|beijing|xi jinping)",
    "Dólar y divisas": r"(dollar|currency|yen|euro\b|d[oó]lar|forex)",
    "Elecciones y política": r"(election|midterm|congress|senate|white house|trump|elecci)",
    "Cripto": r"(bitcoin|crypto|ether)",
}


def _serie_info(c, t):
    s_ = c[t].dropna() if t in c else pd.Series(dtype=float)
    if len(s_) < 2:
        return None
    v = lambda n: r((float(s_.iloc[-1]) / float(s_.iloc[-1 - n]) - 1) * 100, 2) if len(s_) > n else None
    nom, grp = PANORAMA[t]
    o = {"t": t, "nombre": nom, "grupo": grp, "precio": r(float(s_.iloc[-1]), 4), "fecha": s_.index[-1].date().isoformat(),
         "r1d": v(1), "r1s": v(5), "r1m": v(21), "r3m": v(63), "r1y": v(250)}
    if grp == "tasa":   # la tasa se mide en puntos base
        bp = lambda n: r((float(s_.iloc[-1]) - float(s_.iloc[-1 - n])) * 100, 0) if len(s_) > n else None
        o.update({"r1d": bp(1), "r1s": bp(5), "r1m": bp(21), "r3m": bp(63), "r1y": bp(250)})
    return o


def _noticias_generales(yf):
    import urllib.parse
    import re
    items = []
    for q, idioma in NOTICIAS_GENERALES:
        loc = "hl=es-419&gl=CL&ceid=CL:es-419" if idioma == "es" else "hl=en-US&gl=US&ceid=US:en"
        try:
            items += [dict(x, idioma=idioma) for x in _rss(f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}+when:1d&{loc}", "Google News", 15)]
        except Exception:
            pass
    for t in ("^GSPC", "^IXIC"):
        try:
            items += [dict(x, idioma="en") for x in _noticias_yf(yf.Ticker(t))]
        except Exception:
            pass
    vistos, out = set(), []
    for x in sorted(items, key=lambda x: x.get("fecha") or "", reverse=True):
        k = re.sub(r"[^a-z0-9]", "", x["titulo"].lower())[:50]
        if k in vistos:
            continue
        vistos.add(k)
        x["temas"] = [tm for tm, rx in TEMAS_NOTICIAS.items() if re.search(rx, x["titulo"], re.I)]
        out.append(x)
    return out[:40]


def _yahoo_trending():
    import urllib.request
    try:
        req = urllib.request.Request("https://query1.finance.yahoo.com/v1/finance/trending/US?count=25",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            j = json.loads(resp.read())
        return [q["symbol"] for q in j["finance"]["result"][0]["quotes"] if q.get("symbol")]
    except Exception as e:
        print(f"  trending no disponible ({e.__class__.__name__})")
        return []


def noticias_recientes(yf, t, nombre=None, horas=48):
    """Titulares de las ultimas ~48 h de una accion (Yahoo, luego Google News del dia)."""
    import urllib.parse
    lim = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()[:16]
    out = []
    try:
        out = [x for x in (leer_noticias(yf.Ticker(t), t, nombre) or []) if (x.get("fecha") or "") >= lim]
    except Exception:
        out = []
    if not out:
        try:
            q = urllib.parse.quote(f'{nombre or t} {t} stock')
            out = _rss(f"https://news.google.com/rss/search?q={q}+when:2d&hl=en-US&gl=US&ceid=US:en", "Google News", 3)
        except Exception:
            out = []
    return out[:3]


def _acciones_tendencia(yf, uni, previo):
    """Acciones en tendencia en Yahoo (EE.UU.) + las que mas suben, caen y se transan hoy, con su noticia."""
    listas = {"trending": _yahoo_trending()}
    datos = {}
    for clave, nom in (("day_gainers", "suben"), ("day_losers", "caen"), ("most_actives", "activas")):
        try:
            res = yf.screen(clave, count=25)
            qs = res.get("quotes", []) if isinstance(res, dict) else []
        except Exception as e:
            print(f"  lista {clave} no disponible ({e.__class__.__name__})")
            qs = []
        listas[nom] = []
        for q in qs:
            t = q.get("symbol")
            if not t:
                continue
            listas[nom].append(t)
            datos[t] = {"nombre": q.get("shortName") or q.get("longName"), "precio": r(q.get("regularMarketPrice")),
                        "r1d": r(q.get("regularMarketChangePercent"), 2), "mcap": q.get("marketCap"),
                        "volx": r((q.get("regularMarketVolume") or 0) / q["averageDailyVolume3Month"], 1) if q.get("averageDailyVolume3Month") else None}
        time.sleep(0.5)
    falta = [t for t in listas["trending"] if t not in datos]
    if falta:
        c, v = _bajar(falta, "3mo", lote=50, reintentar=False)
        for t in falta:
            if t in c and c[t].dropna().size >= 2:
                s_ = c[t].dropna()
                vv = v[t].dropna() if t in v else pd.Series(dtype=float)
                datos[t] = {"precio": r(float(s_.iloc[-1])), "r1d": r((float(s_.iloc[-1]) / float(s_.iloc[-2]) - 1) * 100, 2),
                            "volx": r(float(vv.iloc[-1]) / float(vv.iloc[-21:-1].mean()), 1) if len(vv) > 21 and vv.iloc[-21:-1].mean() > 0 else None}
    filas = {f[0]: f for f in (uni or {}).get("filas", [])}
    ix = {c_: i for i, c_ in enumerate((uni or {}).get("cols", []))}
    viejas = (previo or {}).get("notTk", {})
    notTk = {}
    usadas = list(dict.fromkeys(listas["trending"][:20] + listas.get("suben", [])[:12] + listas.get("caen", [])[:12] + listas.get("activas", [])[:10]))
    for t in usadas:
        vj = viejas.get(t)
        if vj and _edad_min(vj.get("h") or "") < 90:
            notTk[t] = vj
            continue
        time.sleep(0.3)
        notTk[t] = {"n": noticias_recientes(yf, t, (datos.get(t) or {}).get("nombre")), "h": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    out = {}
    for nom, lst in listas.items():
        fl = []
        for t in lst[:25]:
            d = dict(datos.get(t) or {})
            f = filas.get(t)
            if f is not None:
                d["enWLS"] = True
                d["bbg"] = f[ix["bbg"]] if "bbg" in ix else None
                d["nombre"] = d.get("nombre") or (f[ix["nombre"]] if "nombre" in ix else None)
            d["t"] = t
            d["noticias"] = (notTk.get(t) or {}).get("n", [])
            fl.append(d)
        out[nom] = fl
    return out, notTk


def _resultados_grandes(yf, uni, previo, maximo_nuevas=10):
    """Fechas de resultados de las empresas mas grandes y transadas del WLS (y lideres que mueven al mercado)."""
    filas = (uni or {}).get("filas", [])
    ix = {c_: i for i, c_ in enumerate((uni or {}).get("cols", []))}
    tops = []
    if filas and "liq" in ix:
        tops = [f[0] for f in sorted(filas, key=lambda f: -(f[ix["liq"]] or 0))[:70]]
    tops = list(dict.fromkeys(tops + list(LIDERES_EXTRA)))
    viejos = {d["t"]: d for d in (previo or {}).get("grandes", [])}
    out, nuevas = [], 0
    for t in tops:
        v = viejos.get(t)
        if v and _edad_min(v.get("h") or "") < 1440:
            out.append(v)
            continue
        if nuevas >= maximo_nuevas:
            if v:
                out.append(v)
            continue
        nuevas += 1
        try:
            time.sleep(0.4)
            x = yf.Ticker(t).info or {}
            ets = x.get("earningsTimestamp") or x.get("earningsTimestampStart")
            out.append({"t": t, "nombre": x.get("shortName") or x.get("longName"), "sector": x.get("sector"), "industria": x.get("industry"),
                        "mcap": x.get("marketCap"), "earn": datetime.fromtimestamp(ets, timezone.utc).date().isoformat() if ets else None,
                        "enWLS": t not in LIDERES_EXTRA or any(f[0] == t for f in filas),
                        "h": datetime.now(timezone.utc).isoformat(timespec="minutes")})
        except Exception:
            if v:
                out.append(v)
    return out


def leer_cartera_txt():
    """cartera.txt (lo escribe la Mesa al guardar posiciones) + equipo.txt: simbolos Yahoo de lo que tienen comprado."""
    out = {}
    if os.path.exists("cartera.txt"):
        for linea in open("cartera.txt", encoding="utf-8"):
            linea = linea.split("#")[0].strip()
            r_ = a_yahoo(linea.split("|")[0].strip()) if linea else None
            if r_:
                out[r_[0]] = r_[1]
    if not out:
        for t in leer_equipo():
            out[t] = EQUIPO_BBG.get(t, t)
    return out


def intradia_cartera():
    """Precio cada 5 min de la ultima sesion de cada accion de la cartera (Corea, Taiwan, EE.UU., etc.)."""
    import yfinance as yf
    cart = leer_cartera_txt()
    if not cart:
        return {}
    ts = list(cart)
    df = yf.download(ts, period="5d", interval="5m", progress=False, auto_adjust=True, group_by="column", threads=True)
    if df is None or df.empty:
        return {}
    cl = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": ts[0]})
    out = {}
    for t in ts:
        if t not in cl:
            continue
        s_ = cl[t].dropna()
        if s_.empty:
            continue
        loc = s_.index.tz_convert(_tz_bolsa(t)) if s_.index.tz is not None else s_.index
        dias = sorted(set(loc.date))
        dia = dias[-1]
        hoy = s_[[d == dia for d in loc.date]]
        antes = s_[[d < dia for d in loc.date]]
        out[t] = {"bbg": cart[t], "dia": dia.isoformat(),
                  "h": [x.tz_convert("UTC").isoformat()[:16] if x.tzinfo else x.isoformat()[:16] for x in hoy.index],
                  "v": [r(float(x), 4) for x in hoy.values],
                  "prev": r(float(antes.iloc[-1]), 4) if len(antes) else None}
    return out


def _tz_bolsa(t):
    for suf, tz in ((".KS", "Asia/Seoul"), (".KQ", "Asia/Seoul"), (".T", "Asia/Tokyo"), (".TW", "Asia/Taipei"), (".TWO", "Asia/Taipei"),
                    (".HK", "Asia/Hong_Kong"), (".SS", "Asia/Shanghai"), (".SZ", "Asia/Shanghai"), (".NS", "Asia/Kolkata"), (".BO", "Asia/Kolkata"),
                    (".L", "Europe/London"), (".DE", "Europe/Berlin"), (".PA", "Europe/Paris"), (".AS", "Europe/Amsterdam"), (".SW", "Europe/Zurich"),
                    (".ST", "Europe/Stockholm"), (".VI", "Europe/Vienna"), (".BR", "Europe/Brussels"), (".JO", "Africa/Johannesburg"),
                    (".SA", "America/Sao_Paulo"), (".MX", "America/Mexico_City"), (".SN", "America/Santiago"), (".TO", "America/Toronto"), (".AX", "Australia/Sydney")):
        if t.endswith(suf):
            return tz
    return "America/New_York"


def construir_panorama(uni=None, previo=None):
    """mercado.json: indices, VIX, dolar y monedas, sectores, gigantes, intradia de hoy, noticias y acciones en tendencia."""
    import yfinance as yf
    ts = list(PANORAMA)
    c, _ = _bajar(ts, "2y", lote=100, reintentar=False)
    if c.empty:
        return previo
    series = [o for o in (_serie_info(c, t) for t in ts) if o]
    cc = c.ffill(limit=4).tail(400)
    hist = {"fechas": [d.date().isoformat() for d in cc.index],
            "s": {t: [r(x, 4) for x in cc[t].tolist()] for t in ts if t in cc and cc[t].notna().sum() > 30}}
    intradia = None
    try:
        di = yf.download(INTRADIA, period="5d", interval="5m", progress=False, auto_adjust=True, group_by="column", threads=True)
        ci = di["Close"] if "Close" in di else di
        base = ci["^IXIC"].dropna()
        if len(base):
            dia = (base.index.tz_convert("America/New_York") if base.index.tz is not None else base.index)[-1].date()
            ny = ci.index.tz_convert("America/New_York") if ci.index.tz is not None else ci.index
            ci = ci[[(x.date() == dia) and (9.5 <= x.hour + x.minute / 60 <= 16) for x in ny]].ffill()
            # cierre de la sesion anterior para medir el % del dia
            prev = {t: (c[t].dropna()[c[t].dropna().index.date < dia].iloc[-1] if t in c and (c[t].dropna().index.date < dia).any() else None) for t in INTRADIA}
            intradia = {"dia": dia.isoformat(), "horas": [x.tz_convert("UTC").isoformat()[:16] if x.tzinfo else x.isoformat()[:16] for x in ci.index],
                        "s": {t: [r(x, 4) for x in ci[t].tolist()] for t in INTRADIA if t in ci},
                        "prev": {t: r(float(v), 4) for t, v in prev.items() if v is not None}}
    except Exception as e:
        print(f"  intradia no disponible ({e.__class__.__name__})")
    p = previo or {}
    if _edad_min(p.get("notHora") or "") >= 25:
        noticias, not_hora = _noticias_generales(yf), datetime.now(timezone.utc).isoformat(timespec="minutes")
    else:
        noticias, not_hora = p.get("noticias", []), p.get("notHora")
    if _edad_min(p.get("tendHora") or "") >= 25:
        try:
            tend, notTk = _acciones_tendencia(yf, uni, p)
        except Exception as e:
            print(f"  acciones en tendencia fallo ({e.__class__.__name__}: {e})")
            tend, notTk = p.get("tendencia", {}), p.get("notTk", {})
        tend_hora = datetime.now(timezone.utc).isoformat(timespec="minutes")
    else:
        tend, notTk, tend_hora = p.get("tendencia", {}), p.get("notTk", {}), p.get("tendHora")
    try:
        grandes = _resultados_grandes(yf, uni, p)
    except Exception as e:
        print(f"  resultados de grandes fallo ({e.__class__.__name__})")
        grandes = p.get("grandes", [])
    try:
        cartera = intradia_cartera()
    except Exception as e:
        print(f"  intradia de la cartera fallo ({e.__class__.__name__}: {e})")
        cartera = {}
    print(f"Panorama: {len(cartera)} de la cartera, {len(series)} series, {len(noticias)} noticias, {sum(len(v) for v in tend.values())} en tendencia, {len(grandes)} grandes")
    return {"generado": datetime.now(timezone.utc).isoformat(timespec="minutes"), "series": series, "hist": hist,
            "intradia": intradia or p.get("intradia"), "noticias": noticias, "notHora": not_hora,
            "tendencia": tend, "notTk": notTk, "tendHora": tend_hora, "grandes": grandes, "macro": EVENTOS_MACRO,
            "cartera": cartera or p.get("cartera") or {}}


# ---------------- MODO AUTOMATICO (GitHub cada 15 minutos) ----------------
FUTUROS = {"ES=F": "S&P 500 (futuro)", "NQ=F": "Nasdaq 100 (futuro)", "NKD=F": "Nikkei 225 (futuro CME)",
           "CL=F": "Petróleo WTI", "GC=F": "Oro", "BTC-USD": "Bitcoin (opera 24/7)"}
TEMAS_MERCADO = {"EE.UU.": "Wall Street stock futures", "Corea": "KOSPI Korea stocks", "Taiwán": "Taiwan stocks TAIEX",
                 "Japón": "Nikkei Japan stocks", "China / Hong Kong": "China stocks Hang Seng", "India": "India Sensex Nifty stocks",
                 "Europa": "European stocks STOXX", "Chips / IA": "semiconductor stocks"}
ARCHIVOS = {"general": "docs/radar_gtc.json", "wls": "docs/radar_wls.json"}


def _bajar_json(url):
    import urllib.request
    try:
        req = urllib.request.Request(url + f"?t={int(time.time())}", headers={"User-Agent": "radar-gtc", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=30) as r_:
            return json.loads(r_.read().decode("utf-8").replace("NaN", "null"))
    except Exception as e:
        print(f"  No pude leer {url}: {e}")
        return None


def _guardar(datos, out):
    texto = json.dumps(datos, ensure_ascii=False, separators=(",", ":"), default=str)
    texto = texto.replace(":NaN", ":null").replace(":-Infinity", ":null").replace(":Infinity", ":null")
    texto = texto.replace(",NaN", ",null").replace("[NaN", "[null")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(texto)


def _edad_min(iso):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60
    except Exception:
        return 1e9


def noticias_mercado():
    import urllib.parse
    out = []
    for region, q in TEMAS_MERCADO.items():
        try:
            items = _rss(f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}+when:1d&hl=en-US&gl=US&ceid=US:en", "Google News")
        except Exception:
            items = []
        out.append({"region": region, "items": items[:4]})
    return out


# ETF de cada pais (cotiza en EE.UU.): su movimiento de hoy anticipa como abrira esa bolsa
PROXY_ETF = {"KS": "EWY", "KQ": "EWY", "JP": "EWJ", "JT": "EWJ", "TT": "EWT", "HK": "EWH", "C1": "MCHI", "C2": "MCHI",
             "CH": "MCHI", "IN": "INDA", "IS": "INDA", "IB": "INDA", "NA": "EWN", "LN": "EWU", "GR": "EWG", "GY": "EWG",
             "FP": "EWQ", "SW": "EWL", "SE": "EWL", "AU": "EWA", "CN": "EWC", "CT": "EWC", "MK": "EWM", "SJ": "EZA",
             "SM": "EWP", "IM": "EWI", "SS": "EWD", "BZ": "EWZ", "MM": "EWW", "CI": "ECH", "IJ": "EIDO", "TB": "THD",
             "PM": "EPHE", "SP": "EWS", "TI": "TUR", "AB": "KSA", "PW": "EPOL", "IT": "EIS", "DC": "EDEN", "NO": "ENOR",
             "FH": "EFNL", "AV": "EWO", "BB": "EWK", "ID": "EIRL", "VN": "VNM", "NZ": "ENZL", "QD": "QAT", "US": "ES=F"}


def proxies_hoy(close=None):
    """% de hoy de cada ETF pais (y del futuro del S&P 500 para EE.UU.)."""
    ts = sorted(set(PROXY_ETF.values()))
    if close is None:
        close, _ = _bajar(ts, "7d", lote=100, reintentar=False)
    out = {}
    for t in ts:
        if t in close and close[t].dropna().size >= 2:
            s_ = close[t].dropna()
            out[t] = r((float(s_.iloc[-1]) / float(s_.iloc[-2]) - 1) * 100, 2)
    return out


def solo_futuros():
    import yfinance as yf
    cl = yf.download(list(FUTUROS), period="7d", interval="1d", auto_adjust=True, progress=False, threads=True)["Close"]
    fut = []
    for t, nom in FUTUROS.items():
        if t in cl and cl[t].dropna().size >= 2:
            s_ = cl[t].dropna()
            fut.append({"t": t, "nombre": nom, "precio": r(float(s_.iloc[-1])), "r1d": r((float(s_.iloc[-1]) / float(s_.iloc[-2]) - 1) * 100, 2)})
    return fut


def rapido(datos, con_noticias):
    """Actualiza solo precios (y noticias) sobre el ultimo calculo completo: tarda 1-3 minutos."""
    import yfinance as yf
    acc = [a["t"] for a in datos["acciones"]]
    mer = [m["t"] for m in datos.get("mercado", []) if m.get("tipo") != "tasa"]
    todos = list(dict.fromkeys(acc + mer + list(FUTUROS) + sorted(set(PROXY_ETF.values()))))
    df = yf.download(todos, period="7d", interval="1d", auto_adjust=True, progress=False, threads=True)
    cl = df["Close"] if not df.empty else None
    def ult2(t):
        if cl is None or t not in cl:
            return None, None
        s_ = cl[t].dropna()
        if len(s_) < 2:
            return None, None
        return float(s_.iloc[-1]), (float(s_.iloc[-1]) / float(s_.iloc[-2]) - 1) * 100
    n = 0
    for a in datos["acciones"]:
        px, ch = ult2(a["t"])
        if px is None:
            continue
        a["precio"], a["r1d"] = r(px), r(ch, 1)
        if a.get("target"):
            a["upside"] = r((a["target"] / px - 1) * 100, 0)
        if a.get("hist"):
            a["hist"][-1] = r(px)
        n += 1
    for m in datos.get("mercado", []):
        px, ch = ult2(m["t"])
        if px is not None and m.get("tipo") != "tasa":
            m["precio"], m["r1d"] = r(px), r(ch, 1)
    fut = []
    for t, nom in FUTUROS.items():
        px, ch = ult2(t)
        if px is not None:
            fut.append({"t": t, "nombre": nom, "precio": r(px), "r1d": r(ch, 2)})
    datos["futuros"] = fut
    try:
        datos["proxies"] = proxies_hoy(cl) or datos.get("proxies", {})
    except Exception:
        pass
    print(f"Precios rapidos: {n} de {len(acc)} acciones")
    if con_noticias:
        print("Actualizando noticias...")
        for a in datos["acciones"]:
            try:
                nv = leer_noticias(yf.Ticker(a["t"]), a["t"], a.get("nombre"))
                if nv:
                    a["noticias"] = nv
            except Exception:
                pass
        datos["noticiasMercado"] = noticias_mercado()
        datos["noticiasHora"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    for a in datos["acciones"]:
        try:
            a["senales"] = senales(a)
        except Exception:
            pass
    datos["generado"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    datos["tipoAct"] = "rapida"
    return datos


def auto():
    """Decide que hacer en cada ejecucion de GitHub (cada 15 min)."""
    sitio = os.environ.get("SITIO", "").rstrip("/") + "/"
    manual = os.environ.get("MANUAL") == "true"
    # MODO=rapido: precios, noticias y panorama (cada 15 min, termina en pocos minutos)
    # MODO=completo: analisis completo, universo y candidatas (cada hora, puede tardar)
    modo_run = os.environ.get("MODO", "")
    ahora = datetime.now(timezone.utc)
    habil = ahora.weekday() < 5 or (ahora.weekday() == 6 and ahora.hour >= 22)  # lunes a viernes (+ domingo noche: abre Asia)
    previos = {k: _bajar_json(sitio + os.path.basename(v)) for k, v in ARCHIVOS.items()}
    uni_prev = _bajar_json(sitio + "universo.json")
    cand_prev = _bajar_json(sitio + "candidatos.json")
    cand = cand_prev
    gen = previos.get("general")
    edad_full = _edad_min((gen or {}).get("completo") or (gen or {}).get("ultimoCompleto") or "") if gen else 1e9
    edad_act = _edad_min((gen or {}).get("generado") or "") if gen else 1e9
    edad_not = _edad_min((gen or {}).get("noticiasHora") or (gen or {}).get("completo") or "") if gen else 1e9
    publicar = True
    uni = uni_prev
    if modo_run == "completo" and not manual and gen is not None and not (habil and edad_full >= 40):
        print("Modo completo: todavia no corresponde (lo hace la proxima hora)")
        publicar = False
    elif modo_run != "rapido" and (manual or gen is None or (habil and edad_full >= 55)):
        print("== Actualizacion COMPLETA ==")
        for modo, out in ARCHIVOS.items():
            try:
                if modo == "wls" and not leer_wls():
                    continue
                d = construir(False, modo == "wls")
                d["modo"] = modo
                d["completo"] = d["generado"]
                d["tipoAct"] = "completa"
                try:
                    d["futuros"] = solo_futuros()
                except Exception:
                    d["futuros"] = []
                try:
                    d["proxies"] = proxies_hoy()
                except Exception:
                    d["proxies"] = {}
                d["noticiasMercado"] = noticias_mercado()
                d["noticiasHora"] = d["generado"]
                _guardar(d, out)
                print(f"Listo {out}")
            except (SystemExit, Exception) as e:
                print(f"{modo}: {e.__class__.__name__}: {e}")
                if previos.get(modo):
                    _guardar(previos[modo], out)
                elif modo == "general":
                    raise
        # el universo completo va al final, para no gastar el limite de Yahoo antes del radar
        try:
            if manual or _edad_min((uni_prev or {}).get("completo") or "") >= 360:
                time.sleep(30)
                uni = unir_universo(construir_universo(), uni_prev) or uni_prev
            elif habil:
                uni = rapido_universo(uni_prev)
            uni = tendencias(uni, uni_prev)
        except Exception as e:
            print(f"Universo WLS fallo ({e.__class__.__name__}: {e}); se mantiene el anterior")
        uni = rellenar_universo(uni)
    elif habil or edad_act >= 55 or edad_not >= 55:
        noticias = (not habil) and edad_not >= 55
        print(f"== Actualizacion RAPIDA (precios{' + noticias' if noticias else ''}) ==")
        if habil and _edad_min((uni_prev or {}).get("rapido") or (uni_prev or {}).get("generado") or "") >= 25:
            try:
                uni = tendencias(rapido_universo(uni_prev), uni_prev)
            except Exception as e:
                print(f"Universo rapido fallo: {e}")
        for modo, out in ARCHIVOS.items():
            d = previos.get(modo)
            if not d:
                continue
            try:
                d = rapido(d, noticias)
            except Exception as e:
                print(f"{modo}: rapida fallo ({e}); se mantiene la anterior")
            _guardar(d, out)
    else:
        print("Fin de semana: no hay nada nuevo que publicar todavia")
        publicar = False
    if modo_run != "rapido" and publicar and uni and (habil or manual or not cand_prev) and (manual or _edad_min((cand_prev or {}).get("generado") or "") >= 40):
        try:
            cand = construir_candidatas(uni, cand_prev) or cand_prev
        except Exception as e:
            print(f"Candidatas fallo ({e.__class__.__name__}: {e}); se mantienen las anteriores")
    pan_prev = _bajar_json(sitio + "mercado.json")   # se baja al final: el modo completo republica el mas nuevo
    pan = pan_prev
    if modo_run != "completo" and publicar and _edad_min((pan_prev or {}).get("generado") or "") >= 10:
        try:
            pan = construir_panorama(uni, pan_prev) or pan_prev
        except Exception as e:
            print(f"Panorama fallo ({e.__class__.__name__}: {e}); se mantiene el anterior")
    if publicar and pan:
        _guardar(pan, "docs/mercado.json")
    if publicar and uni:
        _guardar(uni, "docs/universo.json")
    if publicar and cand:
        _guardar(cand, "docs/candidatos.json")
    salida = os.environ.get("GITHUB_OUTPUT")
    if salida:
        with open(salida, "a") as f:
            f.write(f"publicar={'si' if publicar else 'no'}\n")


def main():
    es_demo = "--demo" in sys.argv
    if "--auto" in sys.argv:
        return auto()
    modo_wls = "--wls" in sys.argv
    if modo_wls and not leer_wls():
        raise SystemExit("--wls: no hay wls.txt con acciones; se omite la pagina Mi lista")
    datos = construir(es_demo, modo_wls)
    datos["modo"] = "wls" if modo_wls else "general"
    rutas = [a for a in sys.argv[1:] if a.endswith(".json")]
    out = rutas[0] if rutas else "radar_gtc.json"
    texto = json.dumps(datos, ensure_ascii=False, separators=(",", ":"), default=str)
    texto = texto.replace(":NaN", ":null").replace(":-Infinity", ":null").replace(":Infinity", ":null")
    texto = texto.replace(",NaN", ",null").replace("[NaN", "[null")
    with open(out, "w", encoding="utf-8") as f:
        f.write(texto)
    print(f"Listo: {out} ({len(datos['acciones'])} acciones)")
    try:
        from google.colab import files  # solo existe en Colab
        files.download(out)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
