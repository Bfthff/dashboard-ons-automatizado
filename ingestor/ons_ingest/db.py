import pandas as pd
import psycopg

from .parse import NUMERIC, OUTPUT_COLUMNS

_UPDATE_COLS = ["nom_subsistema", *NUMERIC]

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS balanco_subsistema (
    ts              timestamptz      NOT NULL,
    subsistema      text             NOT NULL,
    nom_subsistema  text,
    ger_hidraulica  double precision,
    ger_termica     double precision,
    ger_eolica      double precision,
    ger_solar       double precision,
    carga           double precision,
    intercambio     double precision,
    ingested_at     timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (subsistema, ts)
);

CREATE INDEX IF NOT EXISTS idx_balanco_subsistema_ts ON balanco_subsistema (ts DESC);

CREATE TABLE IF NOT EXISTS ingest_log (
    key        text PRIMARY KEY,
    etag       text        NOT NULL,
    rows       integer     NOT NULL,
    loaded_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS capacidade_instalada (
    subsistema text             NOT NULL,
    fonte      text             NOT NULL CHECK (fonte IN ('hidraulica','termica','eolica','solar')),
    mw         double precision NOT NULL CHECK (mw > 0),
    PRIMARY KEY (subsistema, fonte)
);

CREATE TABLE IF NOT EXISTS alerta_config (
    id              boolean PRIMARY KEY DEFAULT true CHECK (id),
    z_alto          numeric NOT NULL DEFAULT 2,
    z_critico       numeric NOT NULL DEFAULT 3,
    rampa_mw_3h     numeric NOT NULL DEFAULT 1500,
    min_historico_h integer NOT NULL DEFAULT 168
);
INSERT INTO alerta_config DEFAULT VALUES ON CONFLICT DO NOTHING;

CREATE OR REPLACE VIEW v_ultimo_instante AS
SELECT max(ts) AS ts
FROM (
    SELECT ts
    FROM balanco_subsistema
    WHERE ts > now() - interval '14 days'
    GROUP BY ts
    HAVING count(*) >= 4
) t;

CREATE OR REPLACE VIEW v_balanco_sin AS
SELECT ts,
       sum(ger_hidraulica) AS ger_hidraulica,
       sum(ger_termica)    AS ger_termica,
       sum(ger_eolica)     AS ger_eolica,
       sum(ger_solar)      AS ger_solar,
       sum(carga)          AS carga,
       count(*)            AS n_subsistemas
FROM balanco_subsistema
GROUP BY ts;

CREATE OR REPLACE VIEW v_capacidade_efetiva AS
WITH obs AS (
    SELECT subsistema,
           max(ger_hidraulica) AS hidraulica,
           max(ger_termica)    AS termica,
           max(ger_eolica)     AS eolica,
           max(ger_solar)      AS solar
    FROM balanco_subsistema
    WHERE ts > now() - interval '365 days'
    GROUP BY subsistema
), unp AS (
    SELECT o.subsistema, f.fonte, f.mw
    FROM obs o
    CROSS JOIN LATERAL (VALUES ('hidraulica', o.hidraulica),
                               ('termica',    o.termica),
                               ('eolica',     o.eolica),
                               ('solar',      o.solar)) AS f(fonte, mw)
)
SELECT u.subsistema,
       u.fonte,
       COALESCE(c.mw, u.mw) AS mw,
       CASE WHEN c.mw IS NULL THEN 'proxy_max_365d' ELSE 'configurada' END AS origem
FROM unp u
LEFT JOIN capacidade_instalada c USING (subsistema, fonte);

CREATE OR REPLACE VIEW v_fator_capacidade AS
SELECT b.ts,
       b.subsistema,
       f.fonte,
       f.geracao,
       cap.mw AS capacidade_mw,
       CASE WHEN cap.mw > 0 THEN f.geracao / cap.mw END AS fator_capacidade
FROM balanco_subsistema b
CROSS JOIN LATERAL (VALUES ('hidraulica', b.ger_hidraulica),
                           ('termica',    b.ger_termica),
                           ('eolica',     b.ger_eolica),
                           ('solar',      b.ger_solar)) AS f(fonte, geracao)
JOIN v_capacidade_efetiva cap
  ON cap.subsistema = b.subsistema AND cap.fonte = f.fonte;

CREATE OR REPLACE VIEW v_alertas_termico AS
WITH base AS (
    SELECT ts, subsistema, ger_termica, carga,
           avg(ger_termica)         OVER w AS media_14d,
           stddev_samp(ger_termica) OVER w AS desvio_14d,
           count(ger_termica)       OVER w AS n_hist,
           ger_termica - lag(ger_termica, 3) OVER o AS rampa_3h
    FROM balanco_subsistema
    WHERE ts > now() - interval '45 days'
    WINDOW o AS (PARTITION BY subsistema ORDER BY ts),
           w AS (PARTITION BY subsistema ORDER BY ts ROWS BETWEEN 336 PRECEDING AND 1 PRECEDING)
), calc AS (
    SELECT base.*,
           (ger_termica - media_14d) / NULLIF(desvio_14d, 0) AS z
    FROM base
)
SELECT c.ts,
       c.subsistema,
       CASE WHEN c.z >= cfg.z_critico OR c.rampa_3h >= cfg.rampa_mw_3h THEN 'CRITICO'
            WHEN c.z >= cfg.z_alto THEN 'ALTO'
       END                                              AS nivel,
       round(c.ger_termica::numeric, 0)                 AS ger_termica,
       round(c.media_14d::numeric, 0)                   AS media_14d,
       round(c.z::numeric, 2)                           AS zscore,
       round(c.rampa_3h::numeric, 0)                    AS rampa_3h,
       round((100 * c.ger_termica / NULLIF(c.carga, 0))::numeric, 1) AS pct_carga
FROM calc c
CROSS JOIN alerta_config cfg
WHERE c.n_hist >= cfg.min_historico_h
  AND (c.z >= cfg.z_alto OR c.rampa_3h >= cfg.rampa_mw_3h);
"""


def init_schema(conn: psycopg.Connection) -> None:
    """Cria tabelas, índice e views de forma idempotente."""
    for stmt in _SCHEMA_SQL.split(";"):
        if stmt.strip():
            conn.execute(stmt)


def already_loaded(conn: psycopg.Connection, key: str, etag: str) -> bool:
    row = conn.execute("SELECT etag FROM ingest_log WHERE key = %s", (key,)).fetchone()
    return row is not None and row[0] == etag


def mark_loaded(conn: psycopg.Connection, key: str, etag: str, rows: int) -> None:
    conn.execute(
        """
        INSERT INTO ingest_log (key, etag, rows) VALUES (%s, %s, %s)
        ON CONFLICT (key) DO UPDATE
           SET etag = EXCLUDED.etag, rows = EXCLUDED.rows, loaded_at = now()
        """,
        (key, etag, rows),
    )


def upsert(conn: psycopg.Connection, df: pd.DataFrame) -> int:
    """Carrega via COPY numa tabela temporária e faz upsert idempotente. Retorna linhas inseridas/atualizadas."""
    if df.empty:
        return 0
    cols = ", ".join(OUTPUT_COLUMNS)
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _UPDATE_COLS)
    old = ", ".join(f"balanco_subsistema.{c}" for c in _UPDATE_COLS)
    new = ", ".join(f"EXCLUDED.{c}" for c in _UPDATE_COLS)

    clean = df[OUTPUT_COLUMNS].astype(object).where(df[OUTPUT_COLUMNS].notna(), None)
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TEMP TABLE _stg (
                ts timestamptz, subsistema text, nom_subsistema text,
                ger_hidraulica double precision, ger_termica double precision,
                ger_eolica double precision, ger_solar double precision,
                carga double precision, intercambio double precision
            ) ON COMMIT DROP
            """
        )
        with cur.copy(f"COPY _stg ({cols}) FROM STDIN") as copy:
            for row in clean.itertuples(index=False, name=None):
                copy.write_row(row)
        cur.execute(
            f"""
            INSERT INTO balanco_subsistema ({cols})
            SELECT {cols} FROM _stg
            ON CONFLICT (subsistema, ts) DO UPDATE
               SET {set_clause}, ingested_at = now()
             WHERE ({old}) IS DISTINCT FROM ({new})
            """
        )
        return cur.rowcount
