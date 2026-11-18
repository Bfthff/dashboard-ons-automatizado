"""Leitura e normalização do dataset de balanço de energia por subsistema (horário)."""
import io

import pandas as pd

TZ = "America/Sao_Paulo"  # o ONS publica em horário de Brasília

# coluna interna -> nomes possíveis na fonte
ALIASES = {
    "ts": ["din_instante"],
    "subsistema": ["id_subsistema"],
    "nom_subsistema": ["nom_subsistema"],
    "ger_hidraulica": ["val_gerhidraulica"],
    "ger_termica": ["val_gertermica"],
    "ger_eolica": ["val_gereolica"],
    "ger_solar": ["val_gersolar"],
    "carga": ["val_carga"],
    "intercambio": ["val_intercambio"],
}
REQUIRED = ["ts", "subsistema", "ger_hidraulica", "ger_termica", "ger_eolica", "ger_solar", "carga"]
NUMERIC = ["ger_hidraulica", "ger_termica", "ger_eolica", "ger_solar", "carga", "intercambio"]
OUTPUT_COLUMNS = ["ts", "subsistema", "nom_subsistema", *NUMERIC]


class SchemaError(ValueError):
    pass


def _read_raw(content: bytes, key: str) -> pd.DataFrame:
    if key.lower().endswith(".parquet"):
        return pd.read_parquet(io.BytesIO(content))
    return pd.read_csv(io.BytesIO(content), sep=";")


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=lambda c: str(c).strip().lower())
    mapping = {}
    for internal, candidates in ALIASES.items():
        for cand in candidates:
            if cand in df.columns:
                mapping[cand] = internal
                break
    missing = [c for c in REQUIRED if c not in mapping.values()]
    if missing:
        raise SchemaError(
            f"colunas ausentes: {missing}; colunas encontradas: {list(df.columns)}"
        )
    df = df.rename(columns=mapping)
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[OUTPUT_COLUMNS].copy()

    ts = pd.to_datetime(df["ts"], errors="coerce")
    # Horas ambíguas (fim do horário de verão, anos antes de 2019) viram NaT e são descartadas.
    ts = ts.dt.tz_localize(TZ, ambiguous="NaT", nonexistent="shift_forward")
    df["ts"] = ts.dt.tz_convert("UTC")
    df["subsistema"] = df["subsistema"].astype(str).str.strip().str.upper()
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["ts"])
    df = df[~df["subsistema"].isin(["", "NAN", "SIN"])]
    df = df.drop_duplicates(subset=["subsistema", "ts"], keep="last")
    return df.sort_values(["ts", "subsistema"]).reset_index(drop=True)


def read_balanco(content: bytes, key: str) -> pd.DataFrame:
    return normalize(_read_raw(content, key))
