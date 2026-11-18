import argparse
import logging
import threading
import time

import psycopg

from . import db, parse, s3, web
from .config import Config

log = logging.getLogger("ons_ingest")


def run_once(cfg: Config) -> dict:
    stats = {"files": 0, "rows": 0, "skipped": 0, "errors": 0}
    sess = s3.make_session()
    objects = s3.select_keys(
        s3.list_objects(cfg.bucket_url, cfg.dataset_prefix, sess), cfg.min_year
    )
    if not objects:
        log.warning(
            "nenhum arquivo .parquet/.csv encontrado em %s (ano >= %s); confira ONS_DATASET_PREFIX",
            cfg.dataset_prefix,
            cfg.min_year,
        )
    with psycopg.connect(cfg.database_url) as conn:
        db.init_schema(conn)
        conn.commit()
        log.info(
            "schema inicializado (host=%s, port=%s, db=%s)",
            conn.info.host,
            conn.info.port,
            conn.info.dbname,
        )
        for obj in objects:
            key, etag = obj["key"], obj["etag"]
            if db.already_loaded(conn, key, etag):
                stats["skipped"] += 1
                continue
            try:
                content = s3.download(cfg.bucket_url, key, sess)
                df = parse.read_balanco(content, key)
                n = db.upsert(conn, df)
                db.mark_loaded(conn, key, etag, len(df))
                conn.commit()
                stats["files"] += 1
                stats["rows"] += n
                log.info("%s: %d linhas lidas, %d inseridas/atualizadas", key, len(df), n)
            except Exception:
                conn.rollback()
                stats["errors"] += 1
                log.exception("falha ao processar %s", key)
    return stats


def wait_for_db(url: str, attempts: int = 30) -> None:
    for i in range(attempts):
        try:
            with psycopg.connect(url, connect_timeout=5):
                return
        except psycopg.OperationalError:
            log.info("aguardando banco (%d/%d)...", i + 1, attempts)
            time.sleep(2)
    raise RuntimeError("banco indisponível")


def _ingest_loop(cfg: Config) -> None:
    while True:
        try:
            log.info("ciclo concluído: %s", run_once(cfg))
        except Exception:
            log.exception("ciclo falhou; nova tentativa no próximo intervalo")
        time.sleep(cfg.poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestão dos dados abertos do ONS")
    parser.add_argument("--once", action="store_true", help="roda um ciclo e sai")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = Config.from_env()
    wait_for_db(cfg.database_url)

    with psycopg.connect(cfg.database_url) as conn:
        db.init_schema(conn)
        conn.commit()

    if args.once:
        log.info("ciclo concluído: %s", run_once(cfg))
        return

    threading.Thread(target=_ingest_loop, args=(cfg,), daemon=True).start()
    web.serve(cfg)


if __name__ == "__main__":
    main()
