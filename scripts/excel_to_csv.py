#!/usr/bin/env python3
"""
Convierte el Excel Pacte Sd a CSV para análisis con DataNex.

Uso:
    python scripts/excel_to_csv.py              # exporta CSV

El Excel vive en data/ (gitignored). Edita las constantes de abajo si cambia el archivo.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

# --- Rutas (Path es la forma moderna de manejar rutas de archivo en Python) ---
# __file__ es la ruta de este script; .parents[1] sube dos niveles → raíz del proyecto.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Archivo Excel de entrada y carpeta donde se guardará el CSV.
EXCEL_PATH = PROJECT_ROOT / "data" / "Pacte Sd Lynch CAR 2026_new.xlsx"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"

# Solo la hoja 1 tiene datos; las otras están vacías.
SHEET_NAME = "Hoja1"

# Fila (empezando en 0) donde están los nombres de columna en el Excel.
HEADER_ROW = 0

# Nombre de archivo de salida
OUTPUT_CSV_NAME = "cohorte_lynch_car.csv"

def to_snake_case(name: str) -> str:
    """
    Convierte un nombre de columna a minúsculas con guiones bajos.

    Ejemplos:
        "SAP"           → "sap"
        "Date of Birth" → "date_of_birth"
    """
    text = unicodedata.normalize("NFKD", str(name))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "_", text.strip().lower())
    text = re.sub(r"_+", "_", text)
    return text or "column"


def parse_european_birth_date(value) -> pd.Timestamp:
    """
    Convierte una fecha europea (d/m/y) a un objeto datetime de pandas.

    Acepta día y mes con 1 o 2 dígitos (p. ej. 5/3/65 o 15/10/72).
    Si el año tiene 2 dígitos: 65 → 1965, 05 → 2005.
    Devuelve pd.NaT (Not a Time) si el valor no es válido.
    """
    if pd.isna(value) or (isinstance(value, str) and not value.strip()):
        return pd.NaT

    # Excel a veces ya devuelve un datetime; lo normalizamos sin hora.
    if isinstance(value, pd.Timestamp):
        return value.normalize()
    if hasattr(value, "year") and not isinstance(value, str):
        return pd.Timestamp(value).normalize()

    text = str(value).strip()
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", text)
    if not match:
        return pd.to_datetime(text, dayfirst=True, errors="coerce")

    day, month, year = (int(part) for part in match.groups())
    if year < 100:
        year = 1900 + year if year >= 30 else 2000 + year

    return pd.Timestamp(year=year, month=month, day=day)


def read_cohort_sheet(excel_path: Path) -> pd.DataFrame:
    """Lee la hoja de cohorte del Excel con pandas."""
    return pd.read_excel(
        excel_path,
        sheet_name=SHEET_NAME,
        header=HEADER_ROW,
        engine="openpyxl",
    )


def transform_cohort(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica todas las transformaciones a la cohorte.

    pandas trabaja con DataFrames: tablas con filas y columnas nombradas.
    Cada paso devuelve un DataFrame nuevo o modifica una copia.
    """
    out = df.copy()

    # 1. Cabeceras: minúsculas y guiones bajos (SAP → sap, Date of Birth → date_of_birth).
    out.columns = [to_snake_case(col) for col in out.columns]

    # 2. Quitar filas y columnas totalmente vacías.
    out = out.dropna(axis=1, how="all").dropna(axis=0, how="all")

    # 3. Recortar espacios en texto.
    for col in out.select_dtypes(include="object").columns:
        out[col] = out[col].map(lambda v: v.strip() if isinstance(v, str) else v)

    # 4. SAP = número de historia clínica como entero nullable (Int64 permite NaN).
    if "sap" in out.columns:
        out["sap"] = pd.to_numeric(out["sap"], errors="coerce").round(0).astype("Int64")

    # 5. Date of birth → fecha estándar (se guardará en CSV como YYYY-MM-DD).
    if "date_of_birth" in out.columns:
        out["date_of_birth"] = out["date_of_birth"].map(parse_european_birth_date)

    return out


def inspect_excel(excel_path: Path) -> None:
    """Muestra hojas y nombres de columna sin imprimir datos de pacientes."""
    xl = pd.ExcelFile(excel_path, engine="openpyxl")
    print(f"Archivo: {excel_path}")
    print(f"Hojas ({len(xl.sheet_names)}): {', '.join(xl.sheet_names)}")

    for sheet in xl.sheet_names:
        df = pd.read_excel(excel_path, sheet_name=sheet, header=HEADER_ROW, engine="openpyxl")
        df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
        print(f"\n[{sheet}] columnas ({len(df.columns)}):")
        for i, col in enumerate(df.columns, start=1):
            print(f"  {i:2d}. {col}")
        print(f"  → filas con datos (aprox.): {len(df)}")


def export_csv(excel_path: Path, output_dir: Path) -> Path:
    """Lee, transforma y escribe un único CSV."""
    raw = read_cohort_sheet(excel_path)
    cohort = transform_cohort(raw)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / OUTPUT_CSV_NAME

    # utf-8-sig: Excel en Windows abre bien los acentos. date_format: fechas como 1965-03-05.
    cohort.to_csv(
        out_path,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    print(f"  [{SHEET_NAME}] {len(cohort)} filas × {len(cohort.columns)} columnas → {out_path}")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convierte el Excel del pacte Lynch (CAR) a CSV."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=EXCEL_PATH,
        help="Ruta al Excel (por defecto: data/Pacte Sd Lynch CAR 2026.xlsx)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Carpeta de salida (por defecto: data/processed)",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Solo muestra hojas y columnas, sin exportar",
    )
    args = parser.parse_args()

    excel_path = args.input if args.input.is_absolute() else PROJECT_ROOT / args.input
    output_dir = args.output_dir if args.output_dir.is_absolute() else PROJECT_ROOT / args.output_dir

    if not excel_path.exists():
        print(f"Error: no existe el Excel {excel_path}", file=sys.stderr)
        return 1

    if args.inspect:
        inspect_excel(excel_path)
        return 0

    print(f"Entrada:  {excel_path}")
    print(f"Salida:   {output_dir}")
    export_csv(excel_path, output_dir)
    print("Listo.")
    return 0


# Solo ejecuta main() si lanzas este archivo directamente (no si lo importas).
if __name__ == "__main__":
    raise SystemExit(main())
