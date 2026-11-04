"""Neurosynth functional dissociation API.

Data contract: Tren's ns-nano create_db.py PostgreSQL/PostGIS schema `ns`.
No synthetic Neurosynth research results are returned when the DB is unavailable.
"""
import os
import re
from functools import lru_cache
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)
app.json.sort_keys = False


@lru_cache(maxsize=1)
def get_engine():
    db_url = os.getenv("DB_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DB_URL is not configured; connect a populated Neurosynth PostgreSQL database")
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]
    return create_engine(db_url, pool_pre_ping=True, pool_size=3, max_overflow=2, connect_args={"connect_timeout": 8})


def parse_coordinate(raw):
    parts = raw.split("_")
    if len(parts) != 3:
        raise ValueError("Coordinates must use x_y_z, for example 0_-52_26")
    try:
        xyz = tuple(float(part) for part in parts)
    except ValueError as error:
        raise ValueError("Coordinates must contain three numbers") from error
    if any(not (-200 <= value <= 200) for value in xyz):
        raise ValueError("Coordinate components must be between -200 and 200")
    return xyz


def clean_term(raw):
    term = raw.strip().replace("_", " ").lower()
    if not term or len(term) > 100 or not re.fullmatch(r"[\w\s\-]+", term, re.UNICODE):
        raise ValueError("Term must be 1-100 characters (letters, digits, spaces, hyphens)")
    return term


def query_pagination():
    try:
        limit = int(request.args.get("limit", "100"))
        offset = int(request.args.get("offset", "0"))
    except ValueError as error:
        raise ValueError("limit and offset must be integers") from error
    if not 1 <= limit <= 500 or not 0 <= offset <= 1_000_000:
        raise ValueError("limit must be 1-500, offset must be 0-1000000")
    return limit, offset


@app.after_request
def add_cors(resp):
    # API is public and read-only. No credentialed cross-origin requests allowed.
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.errorhandler(ValueError)
def invalid_argument(error):
    return jsonify({"ok": False, "error": str(error)}), 400


@app.get("/")
def root():
    return jsonify({"service": "Neurosynth API Server", "status": "running", "data_status": "check /test_db", "endpoints": ["/health", "/test_db", "/dissociate/terms/fear/memory", "/dissociate/locations/0_-52_26/-2_50_-6", "/terms/fear/studies", "/locations/0_-52_26/studies", "/img"]})


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "neurosynth-api"})


@app.get("/img")
def image():
    path = BASE_DIR / "amygdala.gif"
    if not path.is_file():
        return jsonify({"ok": False, "error": "optional image asset not installed"}), 404
    return send_file(path, mimetype="image/gif")


@app.get("/test_db")
def test_db():
    try:
        with get_engine().connect() as conn:
            counts = {}
            for table in ("coordinates", "metadata", "annotations_terms"):
                counts[table] = conn.execute(text(f"SELECT COUNT(*) FROM ns.{table}")).scalar_one()
        ready = all(value > 0 for value in counts.values())
        return jsonify({"ok": ready, "database": "connected", "counts": counts}), (200 if ready else 503)
    except (RuntimeError, SQLAlchemyError) as error:
        # Never echo DB URLs, SQL exception text, or passwords to a public endpoint.
        app.logger.warning("Database check failed: %s", type(error).__name__)
        return jsonify({"ok": False, "database": "unavailable", "error": "Database is not configured, reachable, or initialized"}), 503


def run_study_query(source_sql, params, criterion):
    limit, offset = query_pagination()
    sql = f"""
        WITH matched AS ({source_sql})
        SELECT study_id FROM matched ORDER BY study_id LIMIT :limit OFFSET :offset
    """
    count_sql = f"WITH matched AS ({source_sql}) SELECT COUNT(*) FROM matched"
    try:
        with get_engine().connect() as conn:
            total = conn.execute(text(count_sql), params).scalar_one()
            studies = conn.execute(text(sql), {**params, "limit": limit, "offset": offset}).scalars().all()
    except (RuntimeError, SQLAlchemyError) as error:
        app.logger.warning("Study query failed: %s", type(error).__name__)
        return jsonify({"ok": False, "error": "Neurosynth database unavailable or not initialized"}), 503
    return jsonify({"ok": True, "query": criterion, "total": total, "limit": limit, "offset": offset, "study_ids": studies})


TERMS_QUERY = """
    SELECT DISTINCT a.study_id
    FROM ns.annotations_terms a
    WHERE a.term = :a AND a.weight > 0
      AND NOT EXISTS (
        SELECT 1 FROM ns.annotations_terms b
        WHERE b.study_id = a.study_id AND b.term = :b AND b.weight > 0
      )
"""

LOCATION_QUERY = """
    SELECT DISTINCT a.study_id
    FROM ns.coordinates a
    WHERE ST_3DDWithin(a.geom, ST_MakePoint(:ax, :ay, :az), :radius)
      AND NOT EXISTS (
        SELECT 1 FROM ns.coordinates b
        WHERE b.study_id = a.study_id
          AND ST_3DDWithin(b.geom, ST_MakePoint(:bx, :by, :bz), :radius)
      )
"""


@app.get("/dissociate/terms/<term_a>/<term_b>")
def dissociate_terms(term_a, term_b):
    a, b = clean_term(term_a), clean_term(term_b)
    return run_study_query(TERMS_QUERY, {"a": a, "b": b}, {"type": "terms", "a": a, "b": b, "direction": "A_minus_B"})


@app.get("/dissociate/locations/<coord_a>/<coord_b>")
def dissociate_locations(coord_a, coord_b):
    a, b = parse_coordinate(coord_a), parse_coordinate(coord_b)
    try:
        radius = float(request.args.get("radius", "6"))
    except ValueError as error:
        raise ValueError("radius must be a number") from error
    if not 0 < radius <= 30:
        raise ValueError("radius must be > 0 and <= 30 mm")
    params = dict(zip(("ax", "ay", "az", "bx", "by", "bz"), (*a, *b)))
    params["radius"] = radius
    return run_study_query(LOCATION_QUERY, params, {"type": "locations", "a": a, "b": b, "radius_mm": radius, "direction": "A_minus_B"})


@app.get("/terms/<term>/studies")
def studies_by_term(term):
    cleaned = clean_term(term)
    return run_study_query("SELECT DISTINCT study_id FROM ns.annotations_terms WHERE term = :a AND weight > 0", {"a": cleaned}, {"type": "term", "term": cleaned})


@app.get("/locations/<coords>/studies")
def studies_by_location(coords):
    xyz = parse_coordinate(coords)
    try:
        radius = float(request.args.get("radius", "6"))
    except ValueError as error:
        raise ValueError("radius must be a number") from error
    if not 0 < radius <= 30:
        raise ValueError("radius must be > 0 and <= 30 mm")
    return run_study_query("SELECT DISTINCT study_id FROM ns.coordinates WHERE ST_3DDWithin(geom, ST_MakePoint(:x, :y, :z), :radius)", dict(zip(("x", "y", "z", "radius"), (*xyz, radius))), {"type": "location", "xyz": xyz, "radius_mm": radius})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False)
