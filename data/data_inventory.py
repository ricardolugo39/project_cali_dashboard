import pandas as pd


def load_inventory(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df = df.rename(columns={
        "Código": "sku",
        "Nombre Producto": "nombre",
        "Cód": "suc",
        "Disponible": "disponible",
        "Ultimo": "costo",
        "Familia": "familia"
    })

    df["disponible"] = pd.to_numeric(df["disponible"], errors="coerce").fillna(0)
    df["costo"] = pd.to_numeric(df["costo"], errors="coerce").fillna(0)
    df["suc"] = pd.to_numeric(df["suc"], errors="coerce")

    return df


def filter_valid_sucursales(df: pd.DataFrame) -> pd.DataFrame:
    # Bogotá = 1, Cali = 50
    return df[df["suc"].isin([1, 50])].copy()


def extract_metadata(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("sku", as_index=False)
        .agg({
            "nombre": "first",
            "costo": "mean",
            "familia": "first"
        })
    )


def aggregate_inventory(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["sku", "suc"], as_index=False)
        .agg({
            "disponible": "sum"
        })
    )


def pivot_inventory(df: pd.DataFrame) -> pd.DataFrame:
    df_pivot = df.pivot_table(
        index="sku",
        columns="suc",
        values="disponible",
        aggfunc="sum",
        fill_value=0
    ).reset_index()

    df_pivot = df_pivot.rename(columns={
        1: "stock_bogota",
        50: "stock_cali"
    })

    if "stock_bogota" not in df_pivot.columns:
        df_pivot["stock_bogota"] = 0

    if "stock_cali" not in df_pivot.columns:
        df_pivot["stock_cali"] = 0

    return df_pivot


def add_metadata(df_meta: pd.DataFrame, df_pivot: pd.DataFrame) -> pd.DataFrame:
    return df_pivot.merge(df_meta, on="sku", how="left")


def filter_valid_skus(df: pd.DataFrame) -> pd.DataFrame:
    return df[
        (df["stock_bogota"] > 0) | (df["stock_cali"] > 0)
    ].copy()


def prepare_inventory(df_raw: pd.DataFrame) -> pd.DataFrame:
    df = load_inventory(df_raw)
    df = filter_valid_sucursales(df)

    df_meta = extract_metadata(df)
    df_agg = aggregate_inventory(df)
    df_pivot = pivot_inventory(df_agg)

    df_final = add_metadata(df_meta, df_pivot)
    df_final = filter_valid_skus(df_final)

    return df_final