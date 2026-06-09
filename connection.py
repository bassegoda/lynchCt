# connection.py - Conexión vía API de Metabase
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

_ENV_PATH_CACHE = None

DATASCOPE_SCHEMA_GESTOR = "datascope_gestor_prod"
DATASCOPE_SCHEMA_VALIDADOR = "datascope_validador_prod"

def get_env_path():
    """Busca el archivo .env exclusivamente en OneDrive (Windows/macOS)."""
    global _ENV_PATH_CACHE
    if _ENV_PATH_CACHE is not None:
        return _ENV_PATH_CACHE

    home = Path.home()
    
    # Intento 1: Variables de entorno de Windows (OneDrive / OneDriveCommercial)
    if os.name == 'nt':
        for env_var in ('OneDrive', 'OneDriveCommercial'):
            p = os.getenv(env_var)
            if p:
                path = Path(p) / '.env'
                if path.exists():
                    _ENV_PATH_CACHE = path
                    return path
    
    # Intento 2: Ruta estándar de macOS (CloudStorage)
    else:
        cloud = home / 'Library' / 'CloudStorage'
        if cloud.exists():
            for s_path in cloud.iterdir():
                if 'OneDrive' in s_path.name:
                    path = s_path / '.env'
                    if path.exists():
                        _ENV_PATH_CACHE = path
                        return path

    # Intento 3: Ruta genérica ~/OneDrive/.env (Ambos)
    path = home / 'OneDrive' / '.env'
    if path.exists():
        _ENV_PATH_CACHE = path
        return path

    raise FileNotFoundError("¡Error! No se encontró el archivo .env en tu OneDrive. Verifica que esté sincronizado.")

def _load_metabase_config():
    """Carga y valida la configuración de Metabase desde el .env."""
    load_dotenv(get_env_path())

    metabase_url = os.getenv("METABASE_URL", "https://metabase.clinic.cat").rstrip("/")
    email = os.getenv("METABASE_EMAIL")
    password = os.getenv("METABASE_PASSWORD")
    database_name = os.getenv("METABASE_DATABASE_NAME")

    if not all([email, password, database_name]):
        raise ValueError(
            "Faltan variables de Metabase en el .env. "
            "Requeridas: METABASE_EMAIL, METABASE_PASSWORD, METABASE_DATABASE_NAME."
        )

    return {
        "metabase_url": metabase_url,
        "email": email,
        "password": password,
        "database_name": database_name,
    }


def authenticate():
    """Autentica contra Metabase y devuelve el session_id."""
    config = _load_metabase_config()
    response = requests.post(
        f"{config['metabase_url']}/api/session",
        json={"username": config["email"], "password": config["password"]},
        timeout=60,
    )
    response.raise_for_status()

    session_id = response.json().get("id")
    if not session_id:
        raise ValueError("No se pudo obtener session_id desde /api/session.")
    return session_id


def map_databases(session_id):
    """Devuelve un diccionario {database_name: database_id} de Metabase."""
    config = _load_metabase_config()
    response = requests.get(
        f"{config['metabase_url']}/api/database",
        headers={"X-Metabase-Session": session_id},
        timeout=30,
    )
    response.raise_for_status()

    data = response.json().get("data", [])
    return {d["name"]: d["id"] for d in data if "name" in d and "id" in d}


def resolve_metabase_database(db_map, database_name):
    """Resuelve el id de base en Metabase; fallback gestor → validador."""
    if database_name in db_map:
        return database_name, False

    if (
        database_name == DATASCOPE_SCHEMA_GESTOR
        and DATASCOPE_SCHEMA_VALIDADOR in db_map
    ):
        return DATASCOPE_SCHEMA_VALIDADOR, True

    available = ", ".join(sorted(db_map.keys()))
    raise ValueError(
        f"No existe la base '{database_name}' en Metabase. Disponibles: {available}"
    )


def adapt_query_for_validador(query):
    """Sustituye esquema gestor por validador y renombra identificadores."""
    adapted = query.replace(
        f"{DATASCOPE_SCHEMA_GESTOR}.",
        f"{DATASCOPE_SCHEMA_VALIDADOR}.",
    )
    adapted = re.sub(r"\bpatient_ref\b", "nhc", adapted)
    adapted = re.sub(r"\bepisode_ref\b", "episode_sap", adapted)
    return adapted


def parse_metabase_response(response_json):
    """Convierte la respuesta de /api/dataset a lista de diccionarios por fila."""
    data = response_json.get("data", {})
    cols = [c["name"] for c in data.get("cols", [])]
    rows = data.get("rows", [])
    return [dict(zip(cols, row)) for row in rows]

def execute_query(query, verbose=True):
    """Ejecuta SQL nativo en Metabase y devuelve un DataFrame de pandas."""
    if verbose:
        print("Ejecutando query...")

    start = time.time()
    config = _load_metabase_config()

    session_id = authenticate()
    db_map = map_databases(session_id)
    database_name, used_validador_fallback = resolve_metabase_database(
        db_map, config["database_name"]
    )
    if used_validador_fallback and verbose:
        print(
            f"Base '{DATASCOPE_SCHEMA_GESTOR}' no disponible en Metabase; "
            f"usando '{DATASCOPE_SCHEMA_VALIDADOR}'."
        )

    sql = (
        adapt_query_for_validador(query)
        if database_name == DATASCOPE_SCHEMA_VALIDADOR
        else query
    )

    payload = {
        "database": db_map[database_name],
        "type": "native",
        "native": {"query": sql},
        "cache_ttl": 0,
    }

    response = requests.post(
        f"{config['metabase_url']}/api/dataset",
        headers={"X-Metabase-Session": session_id},
        json=payload,
        timeout=120,
    )

    if response.status_code not in (200, 202):
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise RuntimeError(f"Error query request ({response.status_code}): {detail}")

    rows = parse_metabase_response(response.json())
    df = pd.DataFrame(rows) if rows else pd.DataFrame()

    if verbose:
        print(f"Éxito en {time.time() - start:.2f}s")
    return df


# Tope silencioso del backend Metabase. Si una query devuelve >= 2000 filas,
# la respuesta queda truncada sin error. Avisamos al acercarnos para que el
# llamante slicee a granularidad más fina (mes, unidad).
METABASE_SILENT_ROW_CAP = 2000


def execute_query_yearly(
    render_sql,
    min_year,
    max_year,
    *,
    label="query",
    row_warn_threshold=METABASE_SILENT_ROW_CAP - 100,
    verbose=False,
):
    """Ejecuta `render_sql(year)` año a año y concatena los resultados.

    Pensado para esquivar el tope silencioso de 2000 filas de Metabase
    sin tener que mantener snapshots CSV manualmente. La función no
    pagina dentro de un año: si una sola anualidad supera el tope hay
    que cortar más fino aguas arriba (por unidad, por mes…). Cuando
    detectamos un chunk con >= `row_warn_threshold` filas avisamos para
    que el llamante actúe.

    Args:
        render_sql: callable `int -> str` que devuelve el SQL para un
            año concreto.
        min_year, max_year: rango inclusivo a recorrer.
        label: etiqueta para los logs (p.ej. "cohort", "SOFA").
        row_warn_threshold: límite por chunk a partir del cual emitimos
            aviso. Por defecto, 100 filas por debajo del tope silencioso.
        verbose: si True, propaga `verbose=True` a cada `execute_query`.

    Returns:
        Un DataFrame concatenado, o vacío si todos los chunks vinieron
        vacíos. Conserva el orden cronológico (años ascendentes).
    """
    chunks = []
    total = 0
    for year in range(int(min_year), int(max_year) + 1):
        sql = render_sql(year)
        df = execute_query(sql, verbose=verbose)
        n = len(df)
        total += n
        marker = ""
        if n >= row_warn_threshold:
            marker = (
                f"  ⚠️  {n} filas — cerca del tope silencioso "
                f"({METABASE_SILENT_ROW_CAP}). Cortar este año a mayor "
                "granularidad (mes / unidad) si esperas más datos."
            )
        print(f"  [{label}] {year}: {n} filas{marker}")
        if n:
            chunks.append(df)
    if not chunks:
        return pd.DataFrame()
    print(f"  [{label}] total: {total} filas en {max_year - min_year + 1} años.")
    return pd.concat(chunks, ignore_index=True)
