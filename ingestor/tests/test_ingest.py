import io
import threading

import pandas as pd
import pytest
import requests

from ons_ingest import parse, s3, web
from ons_ingest.config import Config


def _sample_df():
    return pd.DataFrame(
        {
            "id_subsistema": ["SE", "S", "SE", "SE"],
            "nom_subsistema": ["Sudeste", "Sul", "Sudeste", "Sudeste"],
            "din_instante": ["2025-06-01 00:00:00", "2025-06-01 00:00:00",
                             "2025-06-01 01:00:00", "2025-06-01 01:00:00"],  # última duplicada
            "val_gerhidraulica": [30000.5, 5000.0, 29000.0, 29500.0],
            "val_gertermica": [3000.0, 900.0, 3100.0, 3200.0],
            "val_gereolica": [100.0, 800.0, 120.0, 130.0],
            "val_gersolar": [0.0, 0.0, 0.0, 0.0],
            "val_carga": [38000.0, 11000.0, 37000.0, 37000.0],
            "val_intercambio": [-500.0, 200.0, -400.0, -400.0],
        }
    )


def test_parquet_roundtrip_converts_to_utc_and_dedupes():
    buf = io.BytesIO()
    _sample_df().to_parquet(buf)
    out = parse.read_balanco(buf.getvalue(), "BALANCO_2025.parquet")

    assert list(out.columns) == parse.OUTPUT_COLUMNS
    assert len(out) == 3  # duplicata (SE, 01:00) removida, mantendo a última
    first = out.iloc[0]
    assert first["subsistema"] == "S"
    # 00:00 em Brasília (UTC-3) == 03:00 UTC
    assert first["ts"] == pd.Timestamp("2025-06-01 03:00:00", tz="UTC")
    se_1h = out[(out.subsistema == "SE") & (out.ts == pd.Timestamp("2025-06-01 04:00", tz="UTC"))]
    assert se_1h.iloc[0]["ger_hidraulica"] == 29500.0


def test_csv_with_semicolon():
    csv = _sample_df().to_csv(sep=";", index=False).encode()
    out = parse.read_balanco(csv, "BALANCO_2025.csv")
    assert len(out) == 3


def test_missing_required_column_raises_with_found_columns():
    df = _sample_df().drop(columns=["val_gereolica"])
    with pytest.raises(parse.SchemaError) as exc:
        parse.normalize(df)
    assert "ger_eolica" in str(exc.value)
    assert "val_carga" in str(exc.value)


def test_non_numeric_values_become_null():
    df = _sample_df()
    df["val_carga"] = df["val_carga"].astype(object)
    df.loc[0, "val_carga"] = "n/d"
    out = parse.normalize(df)
    assert out["carga"].isna().sum() == 1


def test_drops_sin_aggregate_row():
    df = _sample_df()
    sin_row = pd.DataFrame(
        {
            "id_subsistema": ["SIN", " sin "],
            "nom_subsistema": ["Sistema Interligado Nacional", "SIN"],
            "din_instante": ["2025-06-01 00:00:00", "2025-06-01 01:00:00"],
            "val_gerhidraulica": [35000.5, 29500.0],
            "val_gertermica": [3900.0, 3200.0],
            "val_gereolica": [900.0, 130.0],
            "val_gersolar": [0.0, 0.0],
            "val_carga": [49000.0, 37000.0],
            "val_intercambio": [0.0, 0.0],
        }
    )
    out = parse.normalize(pd.concat([df, sin_row], ignore_index=True))
    assert "SIN" not in set(out["subsistema"])
    assert len(out) == 3


def test_select_keys_filters_by_year_and_extension():
    objs = [
        {"key": "dataset/x/BALANCO_2022.parquet", "etag": "a"},
        {"key": "dataset/x/BALANCO_2025.csv", "etag": "b1"},
        {"key": "dataset/x/BALANCO_2025.parquet", "etag": "b2"},
        {"key": "dataset/x/BALANCO_2026.csv", "etag": "c"},
        {"key": "dataset/x/BALANCO_2027.parquet", "etag": "d1"},
        {"key": "dataset/x/BALANCO_2027.csv", "etag": "d2"},
        {"key": "dataset/x/DicionarioDados.pdf", "etag": "e"},
        {"key": "dataset/x/sem_ano.parquet", "etag": "f"},
    ]
    keys = [o["key"] for o in s3.select_keys(objs, 2025)]
    assert keys == [
        "dataset/x/BALANCO_2025.parquet",
        "dataset/x/BALANCO_2026.csv",
        "dataset/x/BALANCO_2027.parquet",
    ]


def test_web_health_and_index_respond_200():
    cfg = Config(
        database_url="postgresql://unused:unused@127.0.0.1:5432/unused",
        bucket_url="https://example.com",
        dataset_prefix="dataset/",
        poll_interval=3600,
        backfill_years=2,
    )
    server = web.make_server(cfg, port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        health = requests.get(f"http://127.0.0.1:{port}/health", timeout=5)
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        home = requests.get(f"http://127.0.0.1:{port}/", timeout=5)
        assert home.status_code == 200
        assert "SIN em Tempo Real" in home.text
        for marker in ("panel-controls", "sub-controls", "energy-controls", "chart-legend"):
            assert marker in home.text
    finally:
        server.shutdown()
        server.server_close()


def test_web_parse_params_clamps_days_and_filters_subsistemas():
    assert web._parse_params("") == (3, ["N", "NE", "S", "SE"])
    assert web._parse_params("days=999&subsistemas=ne, INVALID, s") == (365, ["NE", "S"])
    assert web._parse_params("days=0&subsistemas=") == (1, [])
