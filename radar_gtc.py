"""
Radar GTC - genera radar_gtc.json con datos de Yahoo Finance
Bloomberg Global Trading Challenge 2026 (12-oct a 13-nov-2026)

En Google Colab: pega todo en una celda y presiona Ejecutar.
El archivo radar_gtc.json se descarga solo; subelo al panel "Radar GTC".

Para usar tu propia lista de acciones, edita SEMILLA abajo.
"""
import json
import sys
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

VENTANA_INI = date(2026, 10, 12)
VENTANA_FIN = date(2026, 11, 13)
LIQUIDEZ_MIN_USD_MM = 20  # volumen diario promedio minimo (millones USD)

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


def r(x, n=2):
    try:
        x = float(x)
        return None if np.isnan(x) or np.isinf(x) else round(x, n)
    except (TypeError, ValueError):
        return None


def zscore(s):
    s = s.astype(float)
    sd = s.std()
    return (s - s.mean()) / sd if sd and not np.isnan(sd) else s * 0


# ------------------------------------------------------------ descarga
def descargar(tickers):
    import time
    import yfinance as yf
    for intento in range(4):
        df = yf.download(tickers, period="6mo", interval="1d", auto_adjust=True,
                         progress=False, threads=False)
        if not df.empty and df["Close"].notna().sum().gt(40).sum() > len(tickers) * 0.7:
            return df["Close"], df["Volume"]
        print(f"  Yahoo respondio incompleto, reintento {intento + 1}...")
        time.sleep(20 * (intento + 1))
    raise SystemExit("Yahoo no entrego precios suficientes. Se mantiene la version anterior.")


def info_de(tickers):
    import yfinance as yf
    filas = {}
    import time
    for i, t in enumerate(tickers, 1):
        print(f"  {i}/{len(tickers)} {t}        ", end="\r")
        f = {"nombre": None, "pais": None, "mcap": None, "short": None, "earn": None}
        time.sleep(0.4)  # evita que Yahoo corte por exceso de consultas
        try:
            tk = yf.Ticker(t)
            inf = tk.info or {}
            f["nombre"] = inf.get("shortName")
            f["pais"] = inf.get("country")
            mc = inf.get("marketCap")
            f["mcap"] = round(mc / 1e6) if mc else None
            sp = inf.get("shortPercentOfFloat")
            f["short"] = round(sp * 100, 1) if sp else None
            cal = tk.calendar
            fechas = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if fechas:
                f["earn"] = pd.to_datetime(fechas[0]).date().isoformat()
        except Exception as e:
            print(f"\n  aviso: {t} sin datos ({e.__class__.__name__})")
        filas[t] = f
    print()
    return filas


def demo(tickers, temas):
    rng = np.random.default_rng(11)
    n = 126
    idx = pd.bdate_range(end=datetime(2026, 10, 9), periods=n)
    fac = {k: rng.normal(0, 0.022, n) for k in set(temas.values())}
    mkt = rng.normal(0.0006, 0.009, n)
    close, vol, info = {}, {}, {}
    for t in tickers:
        if t in DRIVERS:
            rr = mkt * (1.0 if t == "ACWI" else 1.6) + rng.normal(0, 0.007, n)
        else:
            rr = mkt * 1.4 + fac[temas[t]] * rng.uniform(0.8, 1.8) + rng.normal(0, 0.028, n)
            d = int(rng.integers(-6, 45))
            info[t] = {"nombre": f"Ejemplo {t}", "pais": "United States",
                       "mcap": int(rng.integers(800, 60000)),
                       "short": round(float(rng.uniform(2, 28)), 1),
                       "earn": (date(2026, 10, 12) + pd.Timedelta(days=d)).isoformat()}
        close[t] = float(rng.uniform(5, 300)) * np.exp(np.cumsum(rr))
        vol[t] = rng.integers(500_000, 30_000_000, n)
    return pd.DataFrame(close, index=idx), pd.DataFrame(vol, index=idx), info


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
        print("Descargando datos de cada empresa (toma 1-2 minutos)...")
        info = info_de(tickers)

    tickers = [t for t in tickers if t in close and close[t].notna().sum() > 40]
    close = close.ffill()
    ret = close.pct_change(fill_method=None)
    ult = close.iloc[-1]

    m = pd.DataFrame(index=tickers)
    m["tema"] = [temas[t] for t in tickers]
    m["r1s"] = (ult / close.iloc[-6] - 1)[tickers] * 100
    m["r1m"] = (ult / close.iloc[-22] - 1)[tickers] * 100
    m["r3m"] = (ult / close.iloc[-64] - 1)[tickers] * 100
    m["vol20"] = ret[tickers].tail(20).std() * np.sqrt(252) * 100
    m["dd3m"] = (ult / close.tail(64).max() - 1)[tickers] * 100
    m["liq"] = (close[tickers] * volu[tickers]).tail(20).mean() / 1e6
    rm = ret["ACWI"]
    m["beta"] = [ret[t].cov(rm) / rm.var() for t in tickers]
    m["short"] = [info.get(t, {}).get("short") for t in tickers]
    m["earn"] = [info.get(t, {}).get("earn") for t in tickers]

    def en_ventana(d):
        return bool(d) and VENTANA_INI.isoformat() <= d <= VENTANA_FIN.isoformat()
    m["enVentana"] = m["earn"].apply(en_ventana)
    liquida = m["liq"] >= LIQUIDEZ_MIN_USD_MM
    m["puntaje"] = (0.35 * zscore(m["vol20"]) + 0.25 * zscore(m["r1m"])
                    + 0.15 * zscore(m["short"].astype(float).fillna(m["short"].astype(float).median()))
                    + 0.10 * zscore(m["beta"]) + 1.0 * m["enVentana"].astype(float)
                    - 2.0 * (~liquida).astype(float))
    m = m.sort_values("puntaje", ascending=False)

    # correlaciones y grupos
    corr = ret[tickers].tail(90).corr()
    try:
        from scipy.cluster.hierarchy import fcluster, linkage, leaves_list
        from scipy.spatial.distance import squareform
        d = np.array((1 - corr.fillna(0)).clip(lower=0).values, dtype=float, copy=True)
        np.fill_diagonal(d, 0)
        d = (d + d.T) / 2
        Z = linkage(squareform(d, checks=False), method="average")
        grupos = pd.Series(fcluster(Z, t=0.6, criterion="distance"), index=tickers)
        orden = [tickers[i] for i in leaves_list(Z)]
    except ImportError:
        grupos = pd.Series(pd.factorize(m.loc[tickers, "tema"])[0] + 1, index=tickers)
        orden = sorted(tickers, key=lambda t: grupos[t])
    # renumerar grupos por tamaño
    tam = grupos.value_counts()
    nuevo = {g: i + 1 for i, g in enumerate(tam.index)}
    grupos = grupos.map(nuevo)

    # drivers
    sens = {}
    for t in tickers:
        bet, cor = {}, {}
        for dname in DRIVERS:
            if dname in ret:
                rd, rt = ret[dname].tail(90), ret[t].tail(90)
                bet[dname] = r(rt.cov(rd) / rd.var())
                cor[dname] = r(rt.corr(rd))
        principal = max(cor, key=lambda k: abs(cor[k] or 0))
        sens[t] = {"betas": bet, "driver": principal, "driverCorr": cor[principal]}

    acciones = []
    for rank, t in enumerate(m.index, 1):
        row = m.loc[t]
        inf = info.get(t, {})
        acciones.append({
            "t": t, "rank": rank, "nombre": inf.get("nombre") or t, "tema": row["tema"],
            "pais": inf.get("pais"), "mcap": inf.get("mcap"),
            "precio": r(ult[t]), "r1s": r(row["r1s"], 1), "r1m": r(row["r1m"], 1),
            "r3m": r(row["r3m"], 1), "vol20": r(row["vol20"], 0), "dd3m": r(row["dd3m"], 1),
            "liq": r(row["liq"], 1), "beta": r(row["beta"]), "short": r(row["short"], 1),
            "earn": row["earn"] if isinstance(row["earn"], str) else None,
            "enVentana": bool(row["enVentana"]),
            "puntaje": r(row["puntaje"]), "grupo": int(grupos[t]),
            "driver": sens[t]["driver"], "driverCorr": sens[t]["driverCorr"],
            "betas": sens[t]["betas"],
            "hist": [r(x) for x in close[t].tail(60).tolist()],
        })

    lista_g = []
    for g in sorted(grupos.unique()):
        ts = [t for t in orden if grupos[t] == g]
        sub = corr.loc[ts, ts].values
        intra = sub[np.triu_indices(len(ts), 1)].mean() if len(ts) > 1 else None
        lista_g.append({"g": int(g), "tickers": ts, "corr": r(intra),
                        "temas": sorted(set(temas[t] for t in ts))})

    return {
        "generado": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "demo": es_demo,
        "fuente": "Datos de ejemplo simulados" if es_demo else "Yahoo Finance",
        "ventana": {"ini": VENTANA_INI.isoformat(), "fin": VENTANA_FIN.isoformat()},
        "liqMin": LIQUIDEZ_MIN_USD_MM,
        "drivers": DRIVERS,
        "fechas": [d.strftime("%Y-%m-%d") for d in close.index[-60:]],
        "acciones": acciones,
        "grupos": lista_g,
        "corr": {"tickers": orden,
                 "m": [[r(corr.loc[a, b]) for b in orden] for a in orden]},
    }


def main():
    es_demo = "--demo" in sys.argv
    datos = construir(es_demo)
    rutas = [a for a in sys.argv[1:] if a.endswith(".json")]
    out = rutas[0] if rutas else "radar_gtc.json"
    with open(out, "w", encoding="utf-8") as f:
        texto = json.dumps(datos, ensure_ascii=False, separators=(",", ":"))
        # cualquier dato faltante que quede como NaN pasa a null (JSON valido)
        texto = texto.replace("NaN", "null").replace("-Infinity", "null").replace("Infinity", "null")
        f.write(texto)
    print(f"Listo: {out} ({len(datos['acciones'])} acciones)")
    try:
        from google.colab import files  # solo existe en Colab
        files.download(out)
        print("Descargando el archivo a tu computador...")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
