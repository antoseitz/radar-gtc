"""
Radar GTC v2 - genera radar_gtc.json con datos de Yahoo Finance
Bloomberg Global Trading Challenge 2026 (12-oct a 13-nov-2026)

Uso:
    python radar_gtc.py docs/radar_gtc.json      # datos reales
    python radar_gtc.py --demo docs/radar_gtc.json  # datos simulados (sin internet)

Para cambiar la lista de acciones, edita SEMILLA.
"""
import json
import sys
import time
from datetime import date, datetime, timezone

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
TOTAL_ACCIONES = 70          # cuantas acciones sigue el radar cada dia (sin contar equipo.txt)
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
        t = partes[0].upper().replace(" US EQUITY", "").replace(" EQUITY", "").split()[0]
        out[t] = partes[1] if len(partes) > 1 and partes[1] else "Agregada por el equipo"
    return out

def leer_wls():
    """wls.txt: un ticker por linea (los del indice WLS que interesan). Se priorizan al elegir las acciones del dia."""
    import os
    if not os.path.exists(WLS_TXT):
        return set()
    out = set()
    for linea in open(WLS_TXT, encoding="utf-8"):
        linea = linea.split("#")[0].strip().upper()
        if not linea:
            continue
        p = linea.replace(" EQUITY", "").split()
        if len(p) > 1 and p[1] not in ("US", "UN", "UW", "UQ", "UA", "UR", "UP", "UV"):
            continue  # por ahora solo acciones de EE.UU. (Yahoo y horario de Chile)
        out.add(p[0].replace("/", "-"))
    return out


TASA = "^TNX"   # rendimiento del bono del Tesoro de EE.UU. a 10 anos (en %)

# Eventos macro dentro del desafio (fuentes: federalreserve.gov y bls.gov)
EVENTOS_MACRO = [
    {"fecha": "2026-10-14", "evento": "IPC (inflación) de septiembre", "tipo": "inflacion"},
    {"fecha": "2026-10-15", "evento": "Precios al productor (PPI) de septiembre", "tipo": "inflacion"},
    {"fecha": "2026-10-28", "evento": "Decisión de tasas de la Fed (FOMC)", "tipo": "fed"},
    {"fecha": "2026-11-06", "evento": "Informe de empleo de octubre", "tipo": "empleo"},
    {"fecha": "2026-11-10", "evento": "IPC (inflación) de octubre", "tipo": "inflacion"},
    {"fecha": "2026-11-13", "evento": "Precios al productor (PPI) de octubre", "tipo": "inflacion"},
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
                         progress=False, threads=False)
        if not df.empty and df["Close"].notna().sum().gt(60).sum() > len(tickers) * 0.7:
            return df
        print(f"  Yahoo respondio incompleto, reintento {intento + 1}...")
        time.sleep(20 * (intento + 1))
    raise SystemExit("Yahoo no entrego precios suficientes. Se mantiene la version anterior.")


def _rss(url, fuente_def):
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
        if len(out) >= NOTICIAS_POR_EMPRESA:
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


def preseleccion(close, volu, pool, forzadas, total, preferidas=frozenset()):
    """Elige las acciones del dia: forzadas + las de mejor pre-puntaje (volatilidad, momentum, liquidez)."""
    ret = close.pct_change(fill_method=None)
    filas = {}
    for t in pool:
        if t not in close or close[t].notna().sum() < 60:
            continue
        s = close[t].dropna()
        liq = float((close[t] * volu[t]).tail(20).mean() / 1e6) if t in volu else 0
        if liq < LIQUIDEZ_MIN_USD_MM or s.iloc[-1] < 3:
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
    lista_wls = leer_wls()                     # para marcar cuales estan en tu lista
    wls = lista_wls if modo_wls else set()     # solo en la pagina "Mi lista" manda la seleccion
    motivos, origen = {}, {}
    if wls and not es_demo:
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
    if wls:
        pool = [t for t in temas if t in wls or t in NUCLEO or t in equipo]
        total = max(TOTAL_ACCIONES, TOTAL_CON_WLS)
    else:
        pool = list(temas)
        total = TOTAL_ACCIONES
    todos = pool + [d for d in list(DRIVERS) + list(LIDERES_EXTRA) + [TASA] if d not in pool]

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

    forzadas = list(dict.fromkeys([t for t in NUCLEO if t in temas] + list(equipo)))
    tickers = preseleccion(close, volu, pool, forzadas, total, frozenset(wls))
    for t in tickers:
        origen[t] = "equipo" if t in equipo else "nucleo" if t in NUCLEO else "wls" if t in wls else "base" if t in sum(SEMILLA.values(), []) else "nueva"
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
    m["liq"] = (close[tickers] * volu[tickers]).tail(20).mean() / 1e6
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


def main():
    es_demo = "--demo" in sys.argv
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
