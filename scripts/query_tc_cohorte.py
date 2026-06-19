#!/usr/bin/env python3
"""
Extrae los TC abdominales / abdominopélvicos de la cohorte Lynch (CAR) desde DataNex.

Reglas (por etiqueta de `status` en data/processed/cohorte_lynch_car.csv):
  - CRC    → todos los TC abdominales/abdominopélvicos entre 2006 y 2026 (ambos inclusive).
  - LynchP → todos los TC abdominales/abdominopélvicos del 01/01/2020 al 31/12/2024.

Se reutiliza la lógica de prestaciones de `query_imaging.py` (lista TC_ABDOMINAL),
EXCLUYENDO la RMN (solo level_2_ref = '039').

Conexión vía `connection.execute_query` (Metabase → validador).

Datos protegidos: el script NUNCA imprime filas individuales ni NHC.
Solo muestra agregados (conteos) y guarda el resultado en CSV y Excel.

Uso:
    python scripts/query_tc_cohorte.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT_PATH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_PATH))

from connection import execute_query_yearly  # noqa: E402

# --- Rutas ---
PATH_DATA = ROOT_PATH / "data"
COHORT_CSV = PATH_DATA / "processed" / "cohorte_lynch_car.csv"
OUTPUT_CSV = PATH_DATA / "processed" / "tc_cohorte_lynch_car.csv"
OUTPUT_XLSX = PATH_DATA / "processed" / "tc_cohorte_lynch_car.xlsx"

OUTPUT_COLUMNS = [
    "status",
    "nhc",
    "data_naixement",
    "sexe",
    "episode_sap",
    "data_prova",
    "prestacion",
    "prov_descr",
    "accession_number",
]

# --- Lote: por seguridad ante consultas grandes (cohortes < 500, una sola tanda) ---
COHORT_BATCH_SIZE = 500

# --- Ventanas por etiqueta de status (años inclusivos) ---
WINDOWS = {
    "CRC": (2006, 2026),
    "LynchP": (2020, 2024),
}

# --- TC abdominal / toracoabdominal / abdominopélvico (prov_ref confirmados) ---
# Misma lista que query_imaging.py. Se EXCLUYE deliberadamente la RMN.
TC_ABDOMINAL = [
    # Toracoabdominal
    "9632", "9632A", "9632B", "9633", "9633F", "9643",
    "9635", "9635A", "9635D", "9635E",
    "9637I", "9637J", "9639B", "9641B",
    # Abdominal / abdominopélvico
    "9630", "9630B", "9630C", "9630D", "9630Z",
    "9633A", "9633B", "9633C", "9633D", "9633E", "9633G", "9633H",
    "9634", "9634C", "9634D", "9634E", "9634F", "9634G", "9634J", "9634K", "9634L",
    "9636", "9636A",
    "9637C", "9637D", "9637E", "9637K",
    "9639", "9639D",
    "9631A",           # evaluación hepática de donante
    "9813", "9814",    # pielo-TC, cisto-TC
    # Angio-TC abdominal vascular
    "11503", "11504", "11505", "11506", "11507",
    # ICS abdominales
    "11912", "11923", "11924",
    "11213",           # TC pared abdominal
]

PROV_REFS_SQL = ", ".join(f"'{c}'" for c in TC_ABDOMINAL)


def load_cohort() -> pd.DataFrame:
    """Carga la cohorte y deja solo NHC válidos. No imprime datos individuales."""
    df = pd.read_csv(COHORT_CSV)
    df = df.dropna(subset=["sap"]).copy()
    df["sap"] = df["sap"].astype("int64")
    df["status"] = df["status"].astype(str).str.strip()
    return df


def cohort_values_sql(nhcs: list[int]) -> str:
    """Tabla VALUES con los NHC del grupo: (nhc), (nhc), ..."""
    return ",\n        ".join(f"({int(n)})" for n in nhcs)


def build_tc_query(cohort_values: str, status_label: str, year: int) -> str:
    """SQL para un grupo (status) y un año concreto. Solo TC (level_2_ref='039')."""
    return f"""
WITH cohort AS (
    SELECT *
    FROM (VALUES
        {cohort_values}
    ) AS t(nhc)
),

imaging AS (
    SELECT
        p.nhc,
        p.episode_sap,
        p.prov_ref,
        p.prov_descr,
        p.start_date,
        p.accession_number
    FROM datascope_validador_prod.provisions p
    INNER JOIN cohort c
        ON p.nhc = c.nhc
    WHERE p.category = 6
      AND p.level_1_ref = 'DIM'
      AND p.level_2_ref = '039'                 -- solo TC (RMN '038' excluida)
      AND p.prov_ref IN ({PROV_REFS_SQL})
      AND p.start_date >= DATE '{year}-01-01'
      AND p.start_date <  DATE '{year + 1}-01-01'
)

SELECT
    '{status_label}'                         AS status,
    i.nhc,
    CAST(d.birth_date AS date)                AS data_naixement,
    CASE d.sex
        WHEN 1 THEN 'Home'
        WHEN 2 THEN 'Dona'
        WHEN 3 THEN 'Altre'
    END                                       AS sexe,
    i.episode_sap,
    CAST(i.start_date AS date)                AS data_prova,
    i.prov_ref                                AS prestacion,
    i.prov_descr,
    i.accession_number
FROM imaging i
LEFT JOIN datascope_validador_prod.demographics d
    ON d.nhc = i.nhc
ORDER BY i.nhc, data_prova
"""


def run_group(nhcs: list[int], status_label: str) -> pd.DataFrame:
    """Ejecuta la extracción de un grupo año a año (esquiva el tope de 2000 filas)."""
    if not nhcs:
        return pd.DataFrame()

    min_year, max_year = WINDOWS[status_label]
    frames: list[pd.DataFrame] = []

    # Lotes de NHC (las cohortes actuales caben en uno solo, pero por robustez).
    for i in range(0, len(nhcs), COHORT_BATCH_SIZE):
        chunk = nhcs[i : i + COHORT_BATCH_SIZE]
        values = cohort_values_sql(chunk)
        frame = execute_query_yearly(
            lambda year: build_tc_query(values, status_label, year),
            min_year,
            max_year,
            label=f"TC-{status_label}",
        )
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def prepare_output(df: pd.DataFrame) -> pd.DataFrame:
    """Ordena columnas y normaliza las fechas (sin zona horaria)."""
    out = df.copy()
    # Evita problemas con offsets mixtos (+01:00 / +02:00) del validador.
    for col in ("data_prova", "data_naixement"):
        if col in out.columns:
            out[col] = pd.to_datetime(
                out[col].astype(str).str.slice(0, 10),
                format="%Y-%m-%d",
                errors="coerce",
            )
    return out[OUTPUT_COLUMNS]


def save_results(df: pd.DataFrame) -> None:
    """Guarda CSV y Excel en data/processed/."""
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out = prepare_output(df)
    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    out.to_excel(OUTPUT_XLSX, index=False, engine="openpyxl")


def main() -> int:
    cohort = load_cohort()

    print("Cohorte cargada (agregado):")
    print(cohort["status"].value_counts().to_string())
    print()

    results: list[pd.DataFrame] = []
    for status_label in WINDOWS:
        nhcs = cohort.loc[cohort["status"] == status_label, "sap"].tolist()
        min_year, max_year = WINDOWS[status_label]
        print(
            f"[{status_label}] {len(nhcs)} pacientes — "
            f"ventana {min_year}–{max_year}"
        )
        group_df = run_group(nhcs, status_label)
        if not group_df.empty:
            results.append(group_df)
        print()

    if not results:
        print("No se encontraron TC para ningún grupo.")
        return 0

    out = pd.concat(results, ignore_index=True)

    # --- Resumen agregado (sin datos individuales) ---
    print("Total TC encontrados:", len(out))
    print("\nPor status:")
    print(
        out.groupby("status")
        .agg(proves=("prestacion", "count"), pacients=("nhc", "nunique"))
        .to_string()
    )

    save_results(out)
    print(f"\nResultados guardados en:")
    print(f"  {OUTPUT_CSV}")
    print(f"  {OUTPUT_XLSX}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
