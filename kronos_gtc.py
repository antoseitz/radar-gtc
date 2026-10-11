"""
Kronos para el Radar GTC: pronostico de escenarios de precio con el modelo
open source Kronos (github.com/shiyu-coder/Kronos, licencia MIT).

Se usa para estimar CUANTO se puede mover cada accion en los proximos dias
(volatilidad esperada). La direccion (sube/baja) se muestra solo como referencia.
"""
import os
import sys
import time

import numpy as np
import pandas as pd

KRONOS_DIR = os.environ.get("KRONOS_DIR", "Kronos")
MODELO = os.environ.get("KRONOS_MODELO", "NeoQuasar/Kronos-small")
TOKENIZER = os.environ.get("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-base")


def cargar_predictor(modelo=MODELO, tokenizer=TOKENIZER, kronos_dir=KRONOS_DIR):
    if kronos_dir not in sys.path:
        sys.path.insert(0, kronos_dir)
    import torch
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    from model import Kronos, KronosPredictor, KronosTokenizer
    tok = KronosTokenizer.from_pretrained(tokenizer)
    mod = Kronos.from_pretrained(modelo)
    return KronosPredictor(mod, tok, max_context=512)


def dias_habiles_siguientes(ultima_fecha, n):
    return pd.bdate_range(pd.Timestamp(ultima_fecha) + pd.Timedelta(days=1), periods=n)


def preparar(ohlcv, lookback):
    """ohlcv: DataFrame con columnas open, high, low, close, volume e indice de fechas."""
    df = ohlcv[["open", "high", "low", "close", "volume"]].dropna().tail(lookback).copy()
    df["amount"] = df["volume"] * df[["open", "high", "low", "close"]].mean(axis=1)
    return df


def escenarios(predictor, ohlcv, dias=10, n=20, lookback=256, T=1.0, top_p=0.9):
    """Devuelve una matriz (n escenarios x dias) de precios de cierre simulados."""
    df = preparar(ohlcv, lookback)
    x_ts = pd.Series(pd.to_datetime(df.index))
    y_ts = pd.Series(dias_habiles_siguientes(df.index[-1], dias))
    datos = df.reset_index(drop=True)
    preds = predictor.predict_batch(
        df_list=[datos] * n, x_timestamp_list=[x_ts] * n, y_timestamp_list=[y_ts] * n,
        pred_len=dias, T=T, top_p=top_p, sample_count=1, verbose=False)
    return np.array([p["close"].values for p in preds]), list(y_ts), float(df["close"].iloc[-1])


def resumir(paths, fechas, precio):
    """Resume los escenarios en numeros faciles de leer."""
    finales = paths[:, -1]
    ret = (finales / precio - 1) * 100
    logr = np.log(np.clip(paths, 1e-9, None) / precio)
    q = lambda a, p: float(np.percentile(a, p))
    return {
        "dias": int(paths.shape[1]),
        "mov": round(float(np.std(logr[:, -1]) * 100), 1),      # movimiento tipico +-% al final
        "p10": round(q(ret, 10), 1), "p50": round(q(ret, 50), 1), "p90": round(q(ret, 90), 1),
        "pSube": round(float((finales > precio).mean() * 100)),
        "fechas": [pd.Timestamp(f).strftime("%Y-%m-%d") for f in fechas],
        "fan": {k: [round(q(paths[:, d], p), 2) for d in range(paths.shape[1])]
                for k, p in (("p10", 10), ("p25", 25), ("p50", 50), ("p75", 75), ("p90", 90))},
    }


def pronosticar_todas(ohlcv_por_ticker, tickers, dias=10, n=20, lookback=256, limite_seg=1500):
    """Corre Kronos para varias acciones. Si se acaba el tiempo, devuelve lo que alcanzo."""
    inicio = time.time()
    try:
        predictor = cargar_predictor()
    except Exception as e:
        print(f"Kronos no se pudo cargar ({e.__class__.__name__}: {e}). Se omite.")
        return {}
    out = {}
    for i, t in enumerate(tickers, 1):
        if time.time() - inicio > limite_seg:
            print(f"Kronos: limite de tiempo alcanzado tras {i - 1} acciones.")
            break
        try:
            paths, fechas, precio = escenarios(predictor, ohlcv_por_ticker[t], dias, n, lookback)
            out[t] = resumir(paths, fechas, precio)
            print(f"  Kronos {i}/{len(tickers)} {t}: +-{out[t]['mov']}% en {dias} dias")
        except Exception as e:
            print(f"  Kronos {t} fallo ({e.__class__.__name__}: {e})")
    print(f"Kronos: {len(out)} acciones en {time.time() - inicio:.0f} s")
    return out
