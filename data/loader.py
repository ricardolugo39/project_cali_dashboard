# data/loader.py

import subprocess
import pandas as pd
import csv
from io import StringIO
from pathlib import Path


def list_tables(access_file):
    command = ["mdb-tables", "-1", access_file]
    result = subprocess.run(command, capture_output=True, text=True)
    return [t.strip() for t in result.stdout.splitlines() if t.strip()]


def get_table_data(access_file, table_name):
    command = ["mdb-export", "-d", "\t", access_file, table_name]
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error exporting {table_name}: {result.stderr}")
        return pd.DataFrame()

    reader = csv.reader(StringIO(result.stdout), delimiter="\t")
    rows = list(reader)

    if not rows:
        return pd.DataFrame()

    columns = rows[0]
    data_rows = rows[1:]

    clean_rows = [
        row[:len(columns)] if len(row) > len(columns)
        else row + [""] * (len(columns) - len(row))
        for row in data_rows
    ]

    return pd.DataFrame(clean_rows, columns=columns)


def load_tables(access_file, tables):
    """
    Load multiple tables into a dictionary
    """
    data = {}

    for table in tables:
        print(f"Loading {table}...")
        df = get_table_data(access_file, table)

        if df.empty:
            print(f"{table} is empty or failed.")
        else:
            print(f"{table} loaded: {df.shape}")

        data[table] = df

    return data


def load_excel_files():
    from pathlib import Path
    import pandas as pd

    base_path = Path(__file__).resolve().parent

    actividades_path = base_path / "actividades_economicas.xlsx"
    clasificacion_path = base_path / "clasificacion.xlsx"
    inventario_path = base_path / "inventario.xlsx"
    crm_path = base_path / "crm.xlsx"
    cotizacion_path = base_path / "cotizacion.xlsx"

    df_actividades = pd.read_excel(actividades_path)
    df_clasificacion = pd.read_excel(clasificacion_path)
    df_inventario = pd.read_excel(inventario_path)
    df_crm = pd.read_excel(crm_path)
    df_cotizacion = pd.read_excel(cotizacion_path)

    print("Actividades shape:", df_actividades.shape)
    print("Clasificacion shape:", df_clasificacion.shape)
    print("Inventario shape:", df_inventario.shape)
    print("CRM shape:", df_crm.shape)
    print("Cotizacion shape:", df_cotizacion.shape)

    return df_actividades, df_clasificacion, df_inventario, df_crm, df_cotizacion