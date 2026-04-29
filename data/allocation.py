import numpy as np
import pandas as pd

from data.calculations import prepare_sales, filter_sales_by_bodega, calculate_demand


def build_model(df_inv: pd.DataFrame, df_sales_final: pd.DataFrame) -> pd.DataFrame:
    df_sales_clean = prepare_sales(df_sales_final)

    df_cali = filter_sales_by_bodega(df_sales_clean, 50)
    df_bogota = filter_sales_by_bodega(df_sales_clean, 1)

    df_demand_cali = calculate_demand(df_cali).rename(columns={
        "demand_3m": "demand_3m_cali",
        "demand_6m": "demand_6m_cali",
        "demand_3m_m": "demand_3m_m_cali",
        "demand_6m_m": "demand_6m_m_cali",
        "demanda_mensual": "demanda_mensual_cali"
    })

    df_demand_bogota = calculate_demand(df_bogota).rename(columns={
        "demand_3m": "demand_3m_bogota",
        "demand_6m": "demand_6m_bogota",
        "demand_3m_m": "demand_3m_m_bogota",
        "demand_6m_m": "demand_6m_m_bogota",
        "demanda_mensual": "demanda_mensual_bogota"
    })

    df_model = df_inv.merge(df_demand_cali, on="sku", how="left")
    df_model = df_model.merge(df_demand_bogota, on="sku", how="left")

    cols_fill = [
        "demand_3m_cali", "demand_6m_cali", "demand_3m_m_cali", "demand_6m_m_cali", "demanda_mensual_cali",
        "demand_3m_bogota", "demand_6m_bogota", "demand_3m_m_bogota", "demand_6m_m_bogota", "demanda_mensual_bogota"
    ]

    for col in cols_fill:
        if col in df_model.columns:
            df_model[col] = df_model[col].fillna(0)

    df_model["valor_bogota"] = df_model["stock_bogota"] * df_model["costo"]
    df_model["valor_cali"] = df_model["stock_cali"] * df_model["costo"]

    return df_model


def run_allocation_simple(
    df_model: pd.DataFrame,
    demand_threshold_cali: float = 0.5,
    months_target_cali: float = 2.0,
    months_reserve_bogota: float = 3.0,
    min_post_bogota_units: int = 2
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Modelo simple:
    - Cali entra si demanda mensual >= threshold
    - stock objetivo Cali = demanda * meses_target_cali
    - reserva Bogotá = demanda * meses_reserve_bogota
    - envío = min(necesidad Cali, excedente Bogotá)
    """

    # Baja rotación para análisis
    df_low_rotation = df_model[
        df_model["demanda_mensual_cali"] < demand_threshold_cali
    ].copy()

    # Universo principal
    df = df_model[
        df_model["demanda_mensual_cali"] >= demand_threshold_cali
    ].copy()

    # Objetivo Cali
    df["stock_objetivo_cali"] = np.ceil(
        df["demanda_mensual_cali"] * months_target_cali
    )

    df["necesidad_cali"] = (
        df["stock_objetivo_cali"] - df["stock_cali"]
    ).clip(lower=0)

    # Reserva Bogotá
    df["stock_reserva_bogota"] = np.ceil(
        df["demanda_mensual_bogota"] * months_reserve_bogota
    )

    # Protección mínima Bogotá
    df["stock_reserva_bogota"] = np.maximum(
        df["stock_reserva_bogota"],
        min_post_bogota_units
    )

    # Transferible Bogotá
    df["inventario_transferible_bogota"] = (
        df["stock_bogota"] - df["stock_reserva_bogota"]
    ).clip(lower=0)

    # Envío sugerido
    df["envio_sugerido"] = df[[
        "necesidad_cali",
        "inventario_transferible_bogota"
    ]].min(axis=1)

    df["envio_sugerido"] = np.floor(df["envio_sugerido"]).clip(lower=0)

    # Resultado final
    df_result = df[df["envio_sugerido"] >= 1].copy()

    df_result["stock_bogota_post"] = df_result["stock_bogota"] - df_result["envio_sugerido"]
    df_result["stock_cali_post"] = df_result["stock_cali"] + df_result["envio_sugerido"]
    df_result["valor_envio"] = df_result["envio_sugerido"] * df_result["costo"]
    df_result["decision"] = "ENVIAR"

    return df_result, df_low_rotation


def get_dead_inventory_cali(df_model: pd.DataFrame, df_sales_final: pd.DataFrame) -> pd.DataFrame:
    df_sales_clean = prepare_sales(df_sales_final)
    df_cali = filter_sales_by_bodega(df_sales_clean, 50)

    if df_cali.empty:
        return df_model.iloc[0:0].copy()

    today = df_cali["fecha"].max()
    df_cali["days_diff"] = (today - df_cali["fecha"]).dt.days
    df_12m = df_cali[df_cali["days_diff"] <= 365].copy()

    sales_12m = (
        df_12m.groupby("sku", as_index=False)["cantidad"]
        .sum()
        .rename(columns={"cantidad": "sales_12m_cali"})
    )

    df = df_model.merge(sales_12m, on="sku", how="left")
    df["sales_12m_cali"] = df["sales_12m_cali"].fillna(0)

    return df[
        (df["stock_cali"] > 0) &
        (df["sales_12m_cali"] == 0)
    ].copy()