import pandas as pd


def build_product_classification(df_clasificacion):
    df = df_clasificacion.copy()
    df.columns = df.columns.str.strip().str.lower()

    # grupos válidos
    df_grupos = df[
        (df["grupo"].notna()) &
        (df["subgrupo"].isna()) &
        (df["familia"].notna())
    ].copy()

    df_grupos["familia"] = df_grupos["familia"].astype(int).astype(str)
    df_grupos["grupo"] = df_grupos["grupo"].astype(int).astype(str)

    df_grupos = df_grupos[["familia", "grupo", "denominación"]].rename(
        columns={
            "familia": "idfam1",
            "grupo": "idfam2",
            "denominación": "nombre_grupo"
        }
    )

    return df_grupos

def build_product_families(df_clasificacion):
    df = df_clasificacion.copy()
    df.columns = df.columns.str.strip().str.lower()

    df_familias = df[
        (df["grupo"].isna()) &
        (df["familia"].notna())
    ].copy()

    df_familias["familia"] = df_familias["familia"].astype(int).astype(str)

    df_familias = df_familias[["familia", "denominación"]].rename(
        columns={
            "familia": "idfam1",
            "denominación": "nombre_familia"
        }
    )

    return df_familias

def enrich_sales_with_classification(df_sales, df_grupos, df_familias):
    df = df_sales.copy()

    df["idfam1"] = df["idfam1"].astype(str).str.strip()
    df["idfam2"] = df["idfam2"].astype(str).str.strip()

    df = df.merge(
        df_grupos,
        on=["idfam1", "idfam2"],
        how="left"
    )

    df = df.merge(
        df_familias,
        on="idfam1",
        how="left"
    )

    return df



def build_customer_activity(df_actividades):
    df = df_actividades.copy()
    df.columns = df.columns.str.strip().str.lower()

    df = df.rename(
        columns={
            "id actividad": "idciiu",
            "grupo2": "actividad_economica"
        }
    )

    df["idciiu"] = (
        df["idciiu"]
        .astype(str)
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    )

    df = df[["idciiu", "actividad_economica"]].drop_duplicates()

    return df


def enrich_customers_with_activity(df_customers, df_customer_activity):
    df = df_customers.copy()
    df.columns = df.columns.str.strip().str.lower()

    df["idciiu"] = (
        df["idciiu"]
        .astype(str)
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    )

    df = df.merge(
        df_customer_activity,
        on="idciiu",
        how="left"
    )

    return df

def enrich_sales_with_customer_activity(df_sales, df_customers):
    df_sales_out = df_sales.copy()
    df_customers_out = df_customers.copy()

    # limpiar columnas
    df_sales_out.columns = df_sales_out.columns.str.strip().str.lower()
    df_customers_out.columns = df_customers_out.columns.str.strip().str.lower()

    # limpiar nit
    df_sales_out["nit"] = df_sales_out["nit"].astype(str).str.strip()
    df_customers_out["nit"] = df_customers_out["nit"].astype(str).str.strip()

    # dejar una sola fila por nit
    df_customers_out = df_customers_out.drop_duplicates(subset=["nit"]).copy()

    # merge
    df_sales_out = df_sales_out.merge(
        df_customers_out[["nit", "actividad_economica"]],
        on="nit",
        how="left"
    )

    return df_sales_out

def filter_sales_by_bodega(df_sales, bodega):
    df = df_sales.copy()

    df["bodega"] = pd.to_numeric(df["bodega"], errors="coerce")

    df_filtered = df[df["bodega"] == bodega].copy()

    return df_filtered


def prepare_sales(df_sales: pd.DataFrame) -> pd.DataFrame:
    df = df_sales.copy()

    df = df.rename(columns={
        "idproducto": "sku",
        "fecha": "fecha",
        "cantidad": "cantidad",
        "idbodega": "bodega"
    })

    df["fecha"] = pd.to_datetime(
    df["fecha"],
    format="%m/%d/%y %H:%M:%S",
    errors="coerce")

    
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    df["bodega"] = pd.to_numeric(df["bodega"], errors="coerce")

    df = df.dropna(subset=["sku", "fecha"])

    return df


def filter_sales_by_bodega(df_sales: pd.DataFrame, bodega: int) -> pd.DataFrame:
    df = df_sales.copy()
    df["bodega"] = pd.to_numeric(df["bodega"], errors="coerce")
    return df[df["bodega"] == bodega].copy()


def calculate_demand(df_sales: pd.DataFrame) -> pd.DataFrame:
    """
    Demanda simple:
    - últimos 3 meses
    - últimos 6 meses
    - demanda mensual ponderada 70/30
    """
    df = df_sales.copy()

    if df.empty:
        return pd.DataFrame(columns=[
            "sku",
            "demand_3m",
            "demand_6m",
            "demand_3m_m",
            "demand_6m_m",
            "demanda_mensual"
        ])

    today = df["fecha"].max()
    df["days_diff"] = (today - df["fecha"]).dt.days

    df_3m = df[df["days_diff"] <= 90].copy()
    df_6m = df[df["days_diff"] <= 180].copy()

    demand_3m = (
        df_3m.groupby("sku", as_index=False)["cantidad"]
        .sum()
        .rename(columns={"cantidad": "demand_3m"})
    )

    demand_6m = (
        df_6m.groupby("sku", as_index=False)["cantidad"]
        .sum()
        .rename(columns={"cantidad": "demand_6m"})
    )

    df_demand = demand_6m.merge(demand_3m, on="sku", how="outer").fillna(0)

    df_demand["demand_3m_m"] = df_demand["demand_3m"] / 3
    df_demand["demand_6m_m"] = df_demand["demand_6m"] / 6

    df_demand["demanda_mensual"] = (
        0.7 * df_demand["demand_3m_m"] +
        0.3 * df_demand["demand_6m_m"]
    )

    return df_demand