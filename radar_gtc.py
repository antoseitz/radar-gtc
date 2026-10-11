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
        df = yf.download(tickers, period="1y", interval="1d", auto_adjust=True,
                         progress=False, threads=False)
        if not df.empty and df["Close"].notna().sum().gt(60).sum() > len(tickers) * 0.7:
            return df["Close"], df["Volume"]
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
    n = 252
    idx = pd.bdate_range(end=datetime(2026, 10, 9), periods=n)
    fac = {k: rng.normal(0, 0.022, n) for k in set(temas.values())}
    mkt = rng.normal(0.0006, 0.009, n)
    close, vol, info = {}, {}, {}
    sectores = ["Technology", "Industrials", "Energy", "Financial Services", "Consumer Cyclical", "Basic Materials"]
    for t in tickers:
        if t in DRIVERS:
            rr = mkt * (1.0 if t == "ACWI" else 1.6) + rng.normal(0, 0.007, n)
        else:
            rr = mkt * 1.4 + fac[temas[t]] * rng.uniform(0.8, 1.8) + rng.normal(0, 0.028, n)
            d = int(rng.integers(-6, 45))
            p = float(rng.uniform(5, 300))
            info[t] = {"nombre": f"Ejemplo {t}", "pais": "United States",
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
    if a["liq"] is not None and a["liq"] < LIQUIDEZ_MIN_USD_MM:
        s.append(("bad", "Poca liquidez: el precio puede saltar mucho"))
    return [{"tipo": t, "texto": x} for t, x in s]


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
def construir(es_demo=False):
    temas = {t: tema for tema, ts in SEMILLA.items() for t in ts}
    tickers = list(temas)
    todos = tickers + [d for d in DRIVERS if d not in tickers]

    print(f"Descargando precios de {len(tickers)} acciones...")
    if es_demo:
        close, volu, info = demo(todos, temas)
    else:
        close, volu = descargar(todos)
        print("Descargando datos y noticias de cada empresa (2-3 minutos)...")
        info = info_de(tickers)

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
        earn = row["earn"] if isinstance(row["earn"], str) else None
        target = inf.get("target")
        a = {
            "t": t, "rank": rank, "nombre": inf.get("nombre") or t, "tema": row["tema"],
            "pais": inf.get("pais"), "sector": inf.get("sector"), "industria": inf.get("industria"),
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
            "momentum": cuadrante(r(row["r1m"], 1), r(row["r3m"], 1)),
            "hist": [r(x) for x in close[t].tail(60).tolist()],
            "noticias": inf.get("noticias") or [],
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

    return {
        "version": 2,
        "generado": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "ultimoCierre": hoy.isoformat(),
        "demo": es_demo,
        "fuente": "Datos de ejemplo simulados" if es_demo else "Yahoo Finance",
        "ventana": {"ini": VENTANA_INI.isoformat(), "fin": VENTANA_FIN.isoformat()},
        "liqMin": LIQUIDEZ_MIN_USD_MM,
        "drivers": DRIVERS,
        "mercado": mercado,
        "fechas": [d.strftime("%Y-%m-%d") for d in close.index[-60:]],
        "acciones": acciones,
        "grupos": lista_g,
        "corr": {"tickers": orden, "m": [[r(corr.loc[a, b]) for b in orden] for a in orden]},
    }


def main():
    es_demo = "--demo" in sys.argv
    datos = construir(es_demo)
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
