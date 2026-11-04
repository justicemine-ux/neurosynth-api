# Neurosynth API Server — Submission

This is a Flask + PostgreSQL/PostGIS backend compatible with the database schema created by [Tren's ns-nano](https://github.com/spiketren/ns-nano). It includes real SQL-backed functional dissociation endpoints (A minus B), not placeholder fake Neurosynth data.

## Endpoints

| URL | Purpose |
|---|---|
| `/` | Server landing JSON; server can be up even when DB is missing |
| `/health` | Process liveness, HTTP 200 |
| `/test_db` | Database readiness; **must report `ok: true`** |
| `/dissociate/terms/fear/memory` | Studies annotated for fear, not memory |
| `/dissociate/locations/0_-52_26/-2_50_-6` | Studies near first MNI coordinate, not second |
| `/terms/fear/studies` | Studies annotated for fear |
| `/locations/0_-52_26/studies` | Studies with activation within radius |
| `/img` | Optional amygdala.gif, if copied into repo |

For study endpoints, `?limit=100&offset=0` controls pagination. For coordinate endpoints, `?radius=6` uses a 6 mm three-dimensional radius. Location queries apply **study-level** exclusion: a study containing any coordinate in location B is excluded from A minus B. Output is JSON with `study_ids` and `total`.

## Deployment: actual steps

**Prerequisites: GitHub account, Render account, populated PostgreSQL database with PostGIS.** A public Flask website is **not** the same as a populated Neurosynth API. The tutorial zip contains example Flask/FastAPI only, **not the Neurosynth datasets or an initialized database**.

### 1. Prepare database

1. From [Tren's original repository](https://github.com/spiketren/ns-nano), download `coordinates.parquet`, `metadata.parquet`, `annotations.parquet`, and `create_db.py` into a local folder. You can also use Git to clone the original project. The data must be from the corresponding schema version.
2. Provision PostgreSQL with the **PostGIS extension available**. A managed PostgreSQL service may charge fees; check plan and availability before proceeding. Save the **internal** connection URL if deploying Flask on the same platform, and use an **external** URL only for running the import script from your laptop.
3. In a local Python 3.11 environment, install import dependencies:
   `python -m pip install pandas numpy pyarrow sqlalchemy psycopg2-binary`
4. Run the original data import script from the directory containing the Parquet files:
   `python create_db.py --url "postgresql://USER:PASSWORD@HOST:5432/DBNAME"`
   This can take a long time and needs enough storage/RAM. Read original `python create_db.py --help` and the [upstream README](https://github.com/spiketren/ns-nano) before running. **Never push your database URL/password to GitHub.**
5. Ensure imported tables `ns.coordinates`, `ns.annotations_terms`, `ns.metadata` exist and are populated.

### 2. Upload the server repository

1. Go to https://github.com/new . Create a repository such as `neurosynth-api-homework`.
2. Upload this package's **contents** (not the zip as a single file) to the root of your repository. Include `app.py`, `requirements.txt`, `render.yaml`, `.gitignore`, `README.md`, and `tests/`.
3. Commit the files. Do not upload `.env`, passwords or DB credentials.

### 3. Deploy web service on Render

1. Go to https://dashboard.render.com/ and sign in with GitHub.
2. Choose **New → Web Service** and select your new repository (alternatively, use a Render Blueprint from `render.yaml`).
3. Runtime: `Python`. Build command: `pip install -r requirements.txt`.
4. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`.
5. Add **secret environment variable** `DB_URL` with the connection string of the populated PostgreSQL/PostGIS database. If Render and DB are on the same private network, use the private DB URL when applicable.
6. Choose an available instance plan and deploy. Render will assign a `https://YOUR-SERVICE.onrender.com` URL; this is not known until deployment.

### 4. Verify from the public Internet

Replace `YOUR-SERVICE` with your actual Render service name and open in your browser:

- `https://YOUR-SERVICE.onrender.com/health` → `{"ok":true,"service":"neurosynth-api"}`
- `https://YOUR-SERVICE.onrender.com/test_db` → `"ok":true` and **non-zero row counts** for all three tables
- `https://YOUR-SERVICE.onrender.com/dissociate/terms/fear/memory` → HTTP 200 JSON with `study_ids` / `total`
- `https://YOUR-SERVICE.onrender.com/dissociate/locations/0_-52_26/-2_50_-6` → HTTP 200 JSON with `study_ids` / `total`

If `/health` succeeds but `/test_db` is HTTP 503, **the assignment is not fully deployed**; fix DB_URL, PostGIS, DB access, or dataset import. This backend intentionally returns HTTP 503 rather than fabricated research records.

### 5. Submit

[1] Your **actual working public URL**, e.g. `https://YOUR-SERVICE.onrender.com/dissociate/terms/fear/memory` (replace the placeholder and verify).

[2] The `.zip` file containing the full backend Python program (this package), or `app.py` if your instructor accepts just the `.py` file.

## Run locally (optional)

```bash
python -m pip install -r requirements.txt
# Configure DB_URL in environment (do not commit secrets)
python app.py
```

Then visit `http://localhost:8000/health`. Local HTTP success **does not** satisfy the external deployment requirement.

## Tests

Install `pytest` (`python -m pip install pytest`) and run `python -m pytest -q`. These tests check routing, validation, and behavior when the DB is missing; they **do not** replace live DB integration testing after deployment.

## Credits

API and database schema adapted from the approach documented by [spiketren/ns-nano](https://github.com/spiketren/ns-nano). The assignment tutorial's basic Flask/JSON examples inspired the simple HTTP interface. No upstream Neurosynth parquet dataset is bundled; it must be imported separately.
