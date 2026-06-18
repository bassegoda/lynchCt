import sys
from pathlib import Path

import pandas as pd

root_path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_path))

from connection import execute_query

COHORT_BATCH_SIZE = 500
PATH_DATA = root_path / "data"
DEFAULT_DATASET_CLEAN = PATH_DATA / "processed" / "pacte_sd_lynch_car_2026.csv"

# --- 1. Load and parse the CSV ---
df = pd.read_csv(DEFAULT_DATASET_CLEAN)

## I need some anchor date to filter the imaging studies... Pending!!
ANCHOR_DATE = "XX/XX/XXXX"

df["data_donacio"] = pd.to_datetime(df["data_donacio"], format="%Y-%m-%d")
df = df.dropna(subset=["nhc", "data_donacio"])

# --- 2. Confirmed abdominal/thoracoabdominal/abdominopelvic TC prov_ref ---
TC_ABDOMINAL = [
    # Thoracoabdominal
    "9632", "9632A", "9632B", "9633", "9633F", "9643",
    "9635", "9635A", "9635D", "9635E",
    "9637I", "9637J", "9639B", "9641B",
    # Abdominal / abdominopelvic
    "9630", "9630B", "9630C", "9630D", "9630Z",
    "9633A", "9633B", "9633C", "9633D", "9633E", "9633G", "9633H",
    "9634", "9634C", "9634D", "9634E", "9634F", "9634G", "9634J", "9634K", "9634L",
    "9636", "9636A",
    "9637C", "9637D", "9637E", "9637K",
    "9639", "9639D",
    "9631A",           # donor hepatic evaluation
    "9813", "9814",    # pielo-TC, cisto-TC
    # Angio-TC abdominal vascular
    "11503", "11504", "11505", "11506", "11507",
    # ICS abdominals
    "11912", "11923", "11924",
    "11213",           # TC paret abdominal
]

# --- 3. Confirmed abdominal/pelvic (visceral) RMN prov_ref ---
RMN_ABDOMINAL = [
    # Hepatic / biliary / pancreatic
    "9507",                                        # liver elastography
    "9530E", "9530F", "9530G", "9530H", "9530Z",
    "9532A", "9532C",
    "9535C", "9535E", "9535F",
    "9537",
    # Renal / urological
    "9530I", "9530J",
    "9534C", "9534K", "9534L",
    # Abdominal / corporal
    "9530", "9531", "9531A",
    "9532", "9532B", "9532G",
    "9534A", "9534G", "9534M", "9534W",
    "9535", "9535A", "9535B", "9535D",
    # Pelvic visceral (digestiu / urològic / ginecològic)
    "9530K", "9530L", "9530M",
    "9532F",
    "9536",
    "11260", "11261",
    "11313",
    # Obstetric / special
    "9515", "9515A",
    # ICS abdominals
    "11914", "11915", "11916", "11917", "11918", "11919", "11920", "11921",
]

ALL_PROV_REFS = TC_ABDOMINAL + RMN_ABDOMINAL
PROV_REFS_SQL = ", ".join(f"'{c}'" for c in ALL_PROV_REFS)


def _escape_sql_string(value: str) -> str:
    return str(value).replace("'", "''")


def cohort_values_sql(chunk: pd.DataFrame) -> str:
    return ",\n        ".join(
        f"({int(row.nhc)}, DATE '{row.data_donacio.strftime('%Y-%m-%d')}', "
        f"'{_escape_sql_string(row.codi_cas)}', "
        f"'{_escape_sql_string(row.diagnostic)}')"
        for row in chunk.itertuples(index=False)
    )


def build_imaging_query(cohort_values: str) -> str:
    """Query acotada: solo NHC de cohorte, ventana global de fechas y category=6."""
    return f"""
WITH cohort AS (
    SELECT *
    FROM (VALUES
        {cohort_values}
    ) AS t(nhc, data_donacio, codi_cas, diagnostic)
),

bounds AS (
    SELECT
        MIN(date_add('month', -6, data_donacio)) AS start_min,
        MAX(date_add('month',  6, data_donacio)) AS start_max
    FROM cohort
),

imaging AS (
    SELECT
        p.nhc,
        p.episode_sap,
        p.prov_ref,
        p.prov_descr,
        p.level_2_descr,
        p.level_3_descr,
        p.start_date,
        p.accession_number,
        CASE
            WHEN p.level_2_ref = '039' THEN 'TC'
            WHEN p.level_2_ref = '038' THEN 'RMN'
        END AS modalitat
    FROM datascope_validador_prod.provisions p
    INNER JOIN (SELECT DISTINCT nhc FROM cohort) c
        ON p.nhc = c.nhc
    CROSS JOIN bounds b
    WHERE p.category = 6
      AND p.level_1_ref = 'DIM'
      AND p.level_2_ref IN ('038', '039')
      AND p.prov_ref IN ({PROV_REFS_SQL})
      AND p.start_date >= b.start_min
      AND p.start_date < date_add('day', 1, b.start_max)
)

SELECT
    c.codi_cas,
    c.nhc,
    c.diagnostic,
    c.data_donacio,
    i.episode_sap,
    i.modalitat,
    i.prov_ref,
    i.prov_descr,
    i.level_2_descr,
    i.level_3_descr,
    i.accession_number,
    CAST(i.start_date AS date)                                   AS data_prova,
    date_diff('day', c.data_donacio, CAST(i.start_date AS date)) AS dies_diferencia
FROM cohort c
INNER JOIN imaging i
    ON i.nhc = c.nhc
   AND i.start_date >= date_add('month', -6, c.data_donacio)
   AND i.start_date <  date_add('day', 1, date_add('month', 6, c.data_donacio))
ORDER BY c.nhc, data_prova
"""


def run_imaging_queries(cohort_df: pd.DataFrame) -> pd.DataFrame:
    if cohort_df.empty:
        return pd.DataFrame()

    chunks = [
        cohort_df.iloc[i : i + COHORT_BATCH_SIZE]
        for i in range(0, len(cohort_df), COHORT_BATCH_SIZE)
    ]
    frames = []
    for idx, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            print(f"Lote {idx}/{len(chunks)} ({len(chunk)} filas de cohorte)...")
        sql = build_imaging_query(cohort_values_sql(chunk))
        frames.append(execute_query(sql))

    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True)


# --- Execute and save ---
results_df = run_imaging_queries(df)

print(f"Total proves trobades:          {len(results_df)}")
if not results_df.empty:
    print(f"Pacients amb almenys una prova: {results_df['nhc'].nunique()}")
    print("\nPer modalitat:")
    print(
        results_df.groupby("modalitat")
        .agg(proves=("prov_ref", "count"), pacients=("nhc", "nunique"))
    )

DEFAULT_IMAGING_CSV.parent.mkdir(parents=True, exist_ok=True)
results_df.to_csv(DEFAULT_IMAGING_CSV, index=False)
print(f"\nResultats guardats a: {DEFAULT_IMAGING_CSV}")
