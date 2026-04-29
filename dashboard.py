import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

sys.path.append(str(Path.cwd().parent))

from data.loader import load_tables, load_excel_files
from data.calculations import (
    build_product_classification,
    build_product_families,
    build_customer_activity,
    enrich_sales_with_classification,
    enrich_customers_with_activity,
    enrich_sales_with_customer_activity,
    filter_sales_by_bodega,
    prepare_sales,
)

st.set_page_config(
    page_title="Cali Commercial Dashboard",
    layout="wide",
)


# =========================================================
# DATA LOAD
# =========================================================

@st.cache_data(show_spinner=False)
def load_base_data():
    access_file = "/Users/ricardolugo/Library/CloudStorage/OneDrive-Personal/LH/Reports/sales_lh.accdb"
    tables = ["sales", "customers"]

    data = load_tables(access_file, tables)

    df_sales = data["sales"]
    df_customers = data["customers"]

    df_actividades, df_clasificacion, df_inventory, df_crm, df_cotizacion = load_excel_files()

    df_grupos = build_product_classification(df_clasificacion)
    df_familias = build_product_families(df_clasificacion)
    df_customer_activity = build_customer_activity(df_actividades)

    df_sales_enriched = enrich_sales_with_classification(
        df_sales,
        df_grupos,
        df_familias,
    )

    df_customers_enriched = enrich_customers_with_activity(
        df_customers,
        df_customer_activity,
    )

    df_sales_final = enrich_sales_with_customer_activity(
        df_sales_enriched,
        df_customers_enriched,
    )

    df_sales_clean = prepare_sales(df_sales_final)

    df_cali = filter_sales_by_bodega(df_sales_clean, 50).copy()

    return df_cali, df_customers_enriched, df_crm


# =========================================================
# PREP SALES
# =========================================================

@st.cache_data(show_spinner=False)
def build_cali_analysis(df_cali: pd.DataFrame, df_customers_enriched: pd.DataFrame):
    df = df_cali.copy()

    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")

    for col in ["valorbruto", "cantidad", "precio", "costo"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df.loc[df["cantidad"] <= 0, "cantidad"] = 1

    df["year"] = df["fecha"].dt.year
    df["year_month"] = df["fecha"].dt.to_period("M").astype(str)

    df["venta_total"] = df["valorbruto"]
    df["costo_total"] = df["costo"] * df["cantidad"]
    df["utilidad_total"] = df["venta_total"] - df["costo_total"]

    df["margen_pct"] = np.where(
        df["venta_total"] > 0,
        df["utilidad_total"] / df["venta_total"],
        np.nan,
    )

    df["ventas_mm"] = df["venta_total"] / 1_000_000
    df["costos_mm"] = df["costo_total"] / 1_000_000
    df["utilidad_mm"] = df["utilidad_total"] / 1_000_000

    df_vendedores = (
        df_customers_enriched[["nit", "vendedor", "ciudad"]]
        .drop_duplicates(subset=["nit"])
        .copy()
    )

    df = df.merge(df_vendedores, on="nit", how="left")

    return df


@st.cache_data(show_spinner=False)
def build_resumen_clientes(df_cali_analysis: pd.DataFrame):
    max_date = df_cali_analysis["fecha"].max()

    start_12m = max_date - pd.DateOffset(months=12)
    start_6m = max_date - pd.DateOffset(months=6)
    start_prev_12m = start_12m - pd.DateOffset(months=12)

    df_12m = df_cali_analysis[df_cali_analysis["fecha"] >= start_12m].copy()
    df_6m = df_cali_analysis[df_cali_analysis["fecha"] >= start_6m].copy()

    df_prev_12m = df_cali_analysis[
        (df_cali_analysis["fecha"] >= start_prev_12m)
        & (df_cali_analysis["fecha"] < start_12m)
    ].copy()

    base = (
        df_cali_analysis.groupby(["nit", "razonsocial"], as_index=False)
        .agg(
            primera_compra=("fecha", "min"),
            ultima_compra=("fecha", "max"),
            ventas_historicas=("venta_total", "sum"),
            utilidad_historica=("utilidad_total", "sum"),
            facturas_historicas=("numero", "nunique"),
            skus_historicos=("sku", "nunique"),
            actividad_economica=("actividad_economica", "last"),
            vendedor=("vendedor", "last"),
            ciudad=("ciudad", "last"),
        )
    )

    agg_12m = (
        df_12m.groupby(["nit", "razonsocial"], as_index=False)
        .agg(
            ventas_12m=("venta_total", "sum"),
            utilidad_12m=("utilidad_total", "sum"),
            facturas_12m=("numero", "nunique"),
            skus_12m=("sku", "nunique"),
            ultima_compra_12m=("fecha", "max"),
        )
    )

    agg_6m = (
        df_6m.groupby(["nit", "razonsocial"], as_index=False)
        .agg(
            ventas_6m=("venta_total", "sum"),
            utilidad_6m=("utilidad_total", "sum"),
            facturas_6m=("numero", "nunique"),
            skus_6m=("sku", "nunique"),
        )
    )

    agg_prev_12m = (
        df_prev_12m.groupby(["nit", "razonsocial"], as_index=False)
        .agg(
            ventas_prev_12m=("venta_total", "sum"),
            utilidad_prev_12m=("utilidad_total", "sum"),
            facturas_prev_12m=("numero", "nunique"),
        )
    )

    resumen = (
        base.merge(agg_12m, on=["nit", "razonsocial"], how="left")
        .merge(agg_6m, on=["nit", "razonsocial"], how="left")
        .merge(agg_prev_12m, on=["nit", "razonsocial"], how="left")
    )

    fill_zero_cols = [
        "ventas_12m",
        "utilidad_12m",
        "facturas_12m",
        "skus_12m",
        "ventas_6m",
        "utilidad_6m",
        "facturas_6m",
        "skus_6m",
        "ventas_prev_12m",
        "utilidad_prev_12m",
        "facturas_prev_12m",
    ]

    for col in fill_zero_cols:
        resumen[col] = resumen[col].fillna(0)

    resumen["dias_sin_comprar"] = (max_date - resumen["ultima_compra"]).dt.days

    resumen["ticket_promedio_12m"] = np.where(
        resumen["facturas_12m"] > 0,
        resumen["ventas_12m"] / resumen["facturas_12m"],
        0,
    )

    resumen["margen_bruto_pct_12m"] = np.where(
        resumen["ventas_12m"] > 0,
        resumen["utilidad_12m"] / resumen["ventas_12m"],
        0,
    )

    resumen["variacion_ventas_12m_vs_prev"] = np.where(
        resumen["ventas_prev_12m"] > 0,
        (resumen["ventas_12m"] / resumen["ventas_prev_12m"]) - 1,
        np.nan,
    )

    conditions = [
        (resumen["ventas_12m"] > 0) & (resumen["dias_sin_comprar"] <= 60),
        (resumen["ventas_12m"] > 0) & (resumen["dias_sin_comprar"].between(61, 120)),
        (resumen["ventas_12m"] > 0) & (resumen["dias_sin_comprar"] > 120),
        (resumen["ventas_12m"] == 0) & (resumen["ventas_historicas"] > 0),
    ]

    choices = [
        "Activa",
        "En Riesgo",
        "Dormida",
        "Sin compra reciente",
    ]

    resumen["estado_comercial"] = np.select(
        conditions,
        choices,
        default="Nueva / sin historia reciente",
    )

    def minmax(series):
        series = series.fillna(0)

        if series.max() == series.min():
            return pd.Series(0, index=series.index)

        return (series - series.min()) / (series.max() - series.min())

    resumen["score_ventas"] = minmax(resumen["ventas_12m"])
    resumen["score_utilidad"] = minmax(resumen["utilidad_12m"])
    resumen["score_recencia"] = minmax(resumen["dias_sin_comprar"])

    resumen["score_caida"] = minmax(
        resumen["variacion_ventas_12m_vs_prev"]
        .fillna(0)
        .apply(lambda x: abs(x) if x < 0 else 0)
    )

    resumen["priority_score"] = (
        resumen["score_ventas"] * 0.35
        + resumen["score_utilidad"] * 0.20
        + resumen["score_recencia"] * 0.25
        + resumen["score_caida"] * 0.20
    )

    priority_conditions = [
        resumen["priority_score"] >= 0.75,
        resumen["priority_score"] >= 0.55,
        resumen["priority_score"] >= 0.35,
    ]

    priority_choices = ["Critica", "Alta", "Media"]

    resumen["prioridad_comercial"] = np.select(
        priority_conditions,
        priority_choices,
        default="Baja",
    )

    resumen = resumen.sort_values(
        ["ventas_12m", "utilidad_12m"],
        ascending=[False, False],
    ).reset_index(drop=True)

    resumen["rank_ventas_12m"] = resumen.index + 1

    return resumen


# =========================================================
# PREP CRM
# =========================================================

@st.cache_data(show_spinner=False)
def prepare_crm_cali(df_crm: pd.DataFrame):
    df = df_crm.copy()

    df.columns = df.columns.str.strip()

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df["Fecha Cierre"] = pd.to_datetime(df["Fecha Cierre"], errors="coerce")

    df["Ingreso"] = pd.to_numeric(df["Ingreso"], errors="coerce").fillna(0)
    df["Probabilidad"] = pd.to_numeric(df["Probabilidad"], errors="coerce").fillna(0)

    df["Probabilidad_clean"] = df["Probabilidad"]

    df.loc[df["Estado"] == "Cancelado", "Probabilidad_clean"] = 0
    df.loc[df["Estado"] == "Realizado", "Probabilidad_clean"] = 100

    df["Ingreso_ponderado"] = df["Ingreso"] * df["Probabilidad_clean"] / 100

    today = pd.Timestamp.today().normalize()

    # Nueva lógica: control contra fecha de cierre
    df["Dias_para_cierre"] = (df["Fecha Cierre"] - today).dt.days

    df["Oportunidad_vencida"] = (
        (df["Estado"] == "Abierto")
        & (df["Fecha Cierre"] < today)
    )

    df["Dias_vencida"] = np.where(
        df["Oportunidad_vencida"],
        (today - df["Fecha Cierre"]).dt.days,
        0
    )

    vendedores_cali = [
        "JAIRO DAVID VERA",
        "JEISMAN HOLGUIN",
        "YEISSON ANDRES RENTERIA MOSQUERA",
        "NUBIA ANDREA JIMENEZ",
    ]

    df["Vendedor"] = df["Vendedor"].astype(str).str.strip()

    df_cali = df[df["Vendedor"].isin(vendedores_cali)].copy()

    return df_cali


@st.cache_data(show_spinner=False)
def build_pipeline_vendedor_cali(df_crm_cali: pd.DataFrame):
    abiertas = df_crm_cali[df_crm_cali["Estado"] == "Abierto"].copy()

    pipeline_vendedor = (
        abiertas
        .groupby("Vendedor", dropna=False)
        .agg(
            oportunidades_abiertas=("ID", "count"),
            pipeline_total=("Ingreso", "sum"),
            pipeline_ponderado=("Ingreso_ponderado", "sum"),
            oportunidades_vencidas=("Oportunidad_vencida", "sum"),
            dias_vencida_promedio=("Dias_vencida", "mean"),
        )
        .reset_index()
    )

    realizadas_vendedor = (
        df_crm_cali[df_crm_cali["Estado"] == "Realizado"]
        .groupby("Vendedor")
        .agg(
            realizadas=("ID", "count"),
            valor_realizado=("Ingreso", "sum"),
        )
        .reset_index()
    )

    canceladas_vendedor = (
        df_crm_cali[df_crm_cali["Estado"] == "Cancelado"]
        .groupby("Vendedor")
        .agg(
            canceladas=("ID", "count"),
            valor_cancelado=("Ingreso", "sum"),
        )
        .reset_index()
    )

    pipeline_vendedor = (
        pipeline_vendedor
        .merge(realizadas_vendedor, on="Vendedor", how="left")
        .merge(canceladas_vendedor, on="Vendedor", how="left")
    )

    fill_cols = [
        "realizadas",
        "canceladas",
        "valor_realizado",
        "valor_cancelado",
    ]

    pipeline_vendedor[fill_cols] = pipeline_vendedor[fill_cols].fillna(0)

    pipeline_vendedor["pct_vencidas"] = np.where(
        pipeline_vendedor["oportunidades_abiertas"] > 0,
        pipeline_vendedor["oportunidades_vencidas"] / pipeline_vendedor["oportunidades_abiertas"],
        0,
    )

    # Win rate por cantidad
    pipeline_vendedor["win_rate_cantidad"] = np.where(
        (pipeline_vendedor["realizadas"] + pipeline_vendedor["canceladas"]) > 0,
        pipeline_vendedor["realizadas"] /
        (pipeline_vendedor["realizadas"] + pipeline_vendedor["canceladas"]),
        0,
    )

    # Win rate por valor
    pipeline_vendedor["win_rate_valor"] = np.where(
        (pipeline_vendedor["valor_realizado"] + pipeline_vendedor["valor_cancelado"]) > 0,
        pipeline_vendedor["valor_realizado"] /
        (pipeline_vendedor["valor_realizado"] + pipeline_vendedor["valor_cancelado"]),
        0,
    )

    pipeline_vendedor = pipeline_vendedor.sort_values(
        "pipeline_total",
        ascending=False,
    ).reset_index(drop=True)

    return pipeline_vendedor


# =========================================================
# PREP MARGIN
# =========================================================

@st.cache_data(show_spinner=False)
def build_negative_margin_comercial(df_cali_analysis: pd.DataFrame):
    negative_margin_comercial = df_cali_analysis[
        (df_cali_analysis["venta_total"] > 0)
        & (df_cali_analysis["utilidad_total"] < 0)
    ].copy()

    grouped = (
        negative_margin_comercial
        .groupby(
            ["razonsocial", "vendedor", "sku", "nombreproducto", "sufijo"],
            as_index=False,
        )
        .agg(
            ventas_total=("venta_total", "sum"),
            costos_total=("costo_total", "sum"),
            utilidad_total=("utilidad_total", "sum"),
            cantidad_total=("cantidad", "sum"),
            facturas=("numero", "nunique"),
            ultima_venta=("fecha", "max"),
        )
    )

    grouped["margen_pct"] = grouped["utilidad_total"] / grouped["ventas_total"]
    grouped = grouped.sort_values("utilidad_total", ascending=True).reset_index(drop=True)

    return grouped


@st.cache_data(show_spinner=False)
def build_negative_by_vendedor(top_negative_comercial: pd.DataFrame):
    negative_by_vendedor = (
        top_negative_comercial
        .groupby(["vendedor"], as_index=False)
        .agg(
            perdidas_mm=("utilidad_total", "sum"),
            ventas_mm=("ventas_total", "sum"),
            clientes_afectados=("razonsocial", "nunique"),
            skus_negativos=("sku", "nunique"),
            facturas_negativas=("facturas", "sum"),
            ultima_revision=("ultima_venta", "max"),
        )
        .copy()
    )

    negative_by_vendedor["margen_pct"] = (
        negative_by_vendedor["perdidas_mm"]
        / negative_by_vendedor["ventas_mm"]
    ) * 100

    negative_by_vendedor["perdidas_mm"] = (
        negative_by_vendedor["perdidas_mm"] / 1_000_000
    ).round(2)

    negative_by_vendedor["ventas_mm"] = (
        negative_by_vendedor["ventas_mm"] / 1_000_000
    ).round(2)

    negative_by_vendedor["margen_pct"] = negative_by_vendedor["margen_pct"].round(1)

    negative_by_vendedor = negative_by_vendedor.sort_values(
        "perdidas_mm"
    ).reset_index(drop=True)

    negative_by_vendedor["rank_perdida"] = negative_by_vendedor.index + 1

    return negative_by_vendedor


# =========================================================
# APP LOAD
# =========================================================

df_cali, df_customers_enriched, df_crm = load_base_data()

df_cali_analysis = build_cali_analysis(df_cali, df_customers_enriched)
resumen_clientes = build_resumen_clientes(df_cali_analysis)

df_crm_cali = prepare_crm_cali(df_crm)
pipeline_vendedor_cali = build_pipeline_vendedor_cali(df_crm_cali)

top_negative_comercial = build_negative_margin_comercial(df_cali_analysis)
negative_by_vendedor = build_negative_by_vendedor(top_negative_comercial)


# =========================================================
# APP UI
# =========================================================

st.title("Cali Commercial Dashboard")
st.caption("MVP local para seguimiento comercial, CRM y control de margen")

with st.sidebar:
    st.header("Filtros")

    vendedores = sorted(
        [v for v in resumen_clientes["vendedor"].dropna().unique().tolist()]
    )
    vendedor_sel = st.multiselect("Vendedor", vendedores, default=[])

    prioridades = sorted(
        resumen_clientes["prioridad_comercial"].dropna().unique().tolist()
    )
    prioridad_sel = st.multiselect("Prioridad", prioridades, default=[])

    estados = sorted(
        resumen_clientes["estado_comercial"].dropna().unique().tolist()
    )
    estado_sel = st.multiselect("Estado comercial", estados, default=[])

    actividades = sorted(
        [a for a in resumen_clientes["actividad_economica"].dropna().unique().tolist()]
    )
    actividad_sel = st.multiselect("Actividad económica", actividades, default=[])

    excluir_comercio = st.checkbox(
        "Excluir comercio general / rodamientos",
        value=True,
    )


# =========================================================
# FILTERS
# =========================================================

filtered_resumen = resumen_clientes.copy()

if vendedor_sel:
    filtered_resumen = filtered_resumen[
        filtered_resumen["vendedor"].isin(vendedor_sel)
    ]

if prioridad_sel:
    filtered_resumen = filtered_resumen[
        filtered_resumen["prioridad_comercial"].isin(prioridad_sel)
    ]

if estado_sel:
    filtered_resumen = filtered_resumen[
        filtered_resumen["estado_comercial"].isin(estado_sel)
    ]

if actividad_sel:
    filtered_resumen = filtered_resumen[
        filtered_resumen["actividad_economica"].isin(actividad_sel)
    ]

if excluir_comercio:
    filtered_resumen = filtered_resumen[
        ~filtered_resumen["actividad_economica"].isin(
            [
                "COMERCIO EN GENERAL",
                "COMERCIO DE RODAMIENTOS Y AFINES",
            ]
        )
    ]


# =========================================================
# KPIS TOP
# =========================================================

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Clientes", f"{filtered_resumen['razonsocial'].nunique():,.0f}")

with col2:
    st.metric(
        "Ventas 12M (MM)",
        f"{filtered_resumen['ventas_12m'].sum() / 1_000_000:,.1f}",
    )

with col3:
    st.metric(
        "Utilidad 12M (MM)",
        f"{filtered_resumen['utilidad_12m'].sum() / 1_000_000:,.1f}",
    )

with col4:
    criticas = (filtered_resumen["prioridad_comercial"] == "Critica").sum()
    st.metric("Cuentas críticas", f"{criticas:,.0f}")


# =========================================================
# TABS
# =========================================================

main_tab1, main_tab2, main_tab3, main_tab4 = st.tabs(
    [
        "Key Accounts",
        "CRM",
        "Margin Control",
        "Customer Deep Dive",
    ]
)


# =========================================================
# TAB 1 - KEY ACCOUNTS
# =========================================================

with main_tab1:
    st.subheader("Key Accounts")

    view_accounts = filtered_resumen.copy()

    view_accounts["ventas_12m"] = (view_accounts["ventas_12m"] / 1_000_000).round(1)
    view_accounts["ventas_6m"] = (view_accounts["ventas_6m"] / 1_000_000).round(1)
    view_accounts["utilidad_12m"] = (view_accounts["utilidad_12m"] / 1_000_000).round(1)
    view_accounts["ticket_promedio_12m"] = (
        view_accounts["ticket_promedio_12m"] / 1_000_000
    ).round(1)

    view_accounts["margen_bruto_pct_12m"] = (
        view_accounts["margen_bruto_pct_12m"] * 100
    ).round(1)

    view_accounts["variacion_ventas_12m_vs_prev"] = (
        view_accounts["variacion_ventas_12m_vs_prev"] * 100
    ).round(1)

    view_accounts["priority_score"] = view_accounts["priority_score"].round(2)

    st.dataframe(
        view_accounts[
            [
                "rank_ventas_12m",
                "razonsocial",
                "vendedor",
                "actividad_economica",
                "ventas_12m",
                "ventas_6m",
                "utilidad_12m",
                "margen_bruto_pct_12m",
                "facturas_12m",
                "skus_12m",
                "ticket_promedio_12m",
                "dias_sin_comprar",
                "variacion_ventas_12m_vs_prev",
                "estado_comercial",
                "prioridad_comercial",
                "priority_score",
            ]
        ],
        use_container_width=True,
        height=520,
    )


# =========================================================
# TAB 2 - CRM
# =========================================================

with main_tab2:
    st.subheader("CRM Pipeline Cali")

    crm_total = len(df_crm_cali)
    crm_abiertas = (df_crm_cali["Estado"] == "Abierto").sum()
    crm_realizadas = (df_crm_cali["Estado"] == "Realizado").sum()
    crm_canceladas = (df_crm_cali["Estado"] == "Cancelado").sum()

    pipeline_total = df_crm_cali.loc[df_crm_cali["Estado"] == "Abierto", "Ingreso"].sum()
    pipeline_ponderado = df_crm_cali.loc[df_crm_cali["Estado"] == "Abierto", "Ingreso_ponderado"].sum()

    valor_realizado = df_crm_cali.loc[df_crm_cali["Estado"] == "Realizado", "Ingreso"].sum()
    valor_cancelado = df_crm_cali.loc[df_crm_cali["Estado"] == "Cancelado", "Ingreso"].sum()

    oportunidades_vencidas = df_crm_cali["Oportunidad_vencida"].sum()

    pct_vencidas = oportunidades_vencidas / crm_abiertas if crm_abiertas > 0 else 0

    win_rate_cantidad = (
        crm_realizadas / (crm_realizadas + crm_canceladas)
        if (crm_realizadas + crm_canceladas) > 0
        else 0
    )

    win_rate_valor = (
        valor_realizado / (valor_realizado + valor_cancelado)
        if (valor_realizado + valor_cancelado) > 0
        else 0
    )

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric("Oportunidades", f"{crm_total:,.0f}")
    with c2:
        st.metric("Abiertas", f"{crm_abiertas:,.0f}")
    with c3:
        st.metric("Realizadas", f"{crm_realizadas:,.0f}")
    with c4:
        st.metric("Canceladas", f"{crm_canceladas:,.0f}")

    c5, c6, c7, c8 = st.columns(4)

    with c5:
        st.metric("Pipeline abierto (MM)", f"{pipeline_total / 1_000_000:,.1f}")
    with c6:
        st.metric("Pipeline ponderado (MM)", f"{pipeline_ponderado / 1_000_000:,.1f}")
    with c7:
        st.metric("Ops vencidas", f"{oportunidades_vencidas:,.0f}")
    with c8:
        st.metric("% vencidas", f"{pct_vencidas * 100:,.1f}%")

    c9, c10, c11, c12 = st.columns(4)

    with c9:
        st.metric("Win Rate cantidad", f"{win_rate_cantidad * 100:,.1f}%")
    with c10:
        st.metric("Win Rate valor", f"{win_rate_valor * 100:,.1f}%")
    with c11:
        st.metric("Valor realizado (MM)", f"{valor_realizado / 1_000_000:,.1f}")
    with c12:
        st.metric("Valor cancelado (MM)", f"{valor_cancelado / 1_000_000:,.1f}")

    st.divider()

    pipeline_view = pipeline_vendedor_cali.copy()

    pipeline_view["pipeline_total"] = (pipeline_view["pipeline_total"] / 1_000_000).round(1)
    pipeline_view["pipeline_ponderado"] = (pipeline_view["pipeline_ponderado"] / 1_000_000).round(1)
    pipeline_view["valor_realizado"] = (pipeline_view["valor_realizado"] / 1_000_000).round(1)
    pipeline_view["valor_cancelado"] = (pipeline_view["valor_cancelado"] / 1_000_000).round(1)
    pipeline_view["pct_vencidas"] = (pipeline_view["pct_vencidas"] * 100).round(1)
    pipeline_view["win_rate_cantidad"] = (pipeline_view["win_rate_cantidad"] * 100).round(1)
    pipeline_view["win_rate_valor"] = (pipeline_view["win_rate_valor"] * 100).round(1)
    pipeline_view["dias_vencida_promedio"] = pipeline_view["dias_vencida_promedio"].round(1)

    st.markdown("**Pipeline por vendedor**")

    st.dataframe(
        pipeline_view[
            [
                "Vendedor",
                "oportunidades_abiertas",
                "pipeline_total",
                "pipeline_ponderado",
                "oportunidades_vencidas",
                "pct_vencidas",
                "realizadas",
                "canceladas",
                "win_rate_cantidad",
                "valor_realizado",
                "valor_cancelado",
                "win_rate_valor",
                "dias_vencida_promedio",
            ]
        ],
        use_container_width=True,
        height=300,
    )

    st.markdown("**Pipeline abierto por vendedor**")

    chart_pipeline = pipeline_view.set_index("Vendedor")[
        ["pipeline_total", "pipeline_ponderado"]
    ]

    st.bar_chart(chart_pipeline, height=320)

    st.markdown("**Top oportunidades abiertas**")

    top_abiertas = (
        df_crm_cali[df_crm_cali["Estado"] == "Abierto"]
        .sort_values("Ingreso", ascending=False)
        [
            [
                "Fecha Cierre",
                "Nombre empresa",
                "Documento",
                "Ingreso",
                "Probabilidad_clean",
                "Etapa",
                "Vendedor",
                "Dias_para_cierre",
                "Dias_vencida",
                "Oportunidad_vencida",
            ]
        ]
        .head(30)
        .copy()
    )

    top_abiertas["Ingreso"] = (top_abiertas["Ingreso"] / 1_000_000).round(1)

    st.dataframe(
        top_abiertas,
        use_container_width=True,
        height=420,
    )

    st.markdown("**Top oportunidades canceladas**")

    top_canceladas = (
        df_crm_cali[df_crm_cali["Estado"] == "Cancelado"]
        .sort_values("Ingreso", ascending=False)
        [
            [
                "Fecha Cierre",
                "Nombre empresa",
                "Documento",
                "Ingreso",
                "Etapa",
                "Vendedor",
            ]
        ]
        .head(30)
        .copy()
    )

    top_canceladas["Ingreso"] = (top_canceladas["Ingreso"] / 1_000_000).round(1)

    st.dataframe(
        top_canceladas,
        use_container_width=True,
        height=420,
    )

# =========================================================
# TAB 3 - MARGIN CONTROL
# =========================================================

with main_tab3:
    st.subheader("Margin Control")

    col_a, col_b = st.columns([2, 3])

    with col_a:
        st.markdown("**Pérdida por vendedor**")

        st.dataframe(
            negative_by_vendedor[
                [
                    "rank_perdida",
                    "vendedor",
                    "perdidas_mm",
                    "ventas_mm",
                    "margen_pct",
                    "clientes_afectados",
                    "skus_negativos",
                    "facturas_negativas",
                    "ultima_revision",
                ]
            ],
            use_container_width=True,
            height=320,
        )

    with col_b:
        st.markdown("**Top pérdidas comerciales reales**")

        neg_view = top_negative_comercial.copy()

        neg_view["ventas_total"] = (neg_view["ventas_total"] / 1_000_000).round(2)
        neg_view["costos_total"] = (neg_view["costos_total"] / 1_000_000).round(2)
        neg_view["utilidad_total"] = (neg_view["utilidad_total"] / 1_000_000).round(2)
        neg_view["margen_pct"] = (neg_view["margen_pct"] * 100).round(1)

        st.dataframe(
            neg_view[
                [
                    "razonsocial",
                    "vendedor",
                    "sku",
                    "nombreproducto",
                    "ventas_total",
                    "costos_total",
                    "utilidad_total",
                    "margen_pct",
                    "facturas",
                    "ultima_venta",
                ]
            ].head(50),
            use_container_width=True,
            height=520,
        )


# =========================================================
# TAB 4 - CUSTOMER DEEP DIVE
# =========================================================

with main_tab4:
    st.subheader("Customer Deep Dive")

    clientes = sorted(filtered_resumen["razonsocial"].dropna().unique().tolist())

    if not clientes:
        st.warning("No hay clientes para mostrar con los filtros actuales.")
        st.stop()

    cliente_sel = st.selectbox("Selecciona un cliente", clientes)

    period_option = st.selectbox(
        "Periodo evaluado",
        [
            "Last 12 Months",
            "Last 6 Months",
            "YTD",
            "QTD",
        ],
        index=0,
    )

    df_cliente_base = df_cali_analysis[
        df_cali_analysis["razonsocial"] == cliente_sel
    ].copy()

    max_date = df_cali_analysis["fecha"].max().normalize()

    if period_option == "Last 12 Months":
        current_start = max_date - pd.DateOffset(months=12)
        current_end = max_date

        prev_start = current_start - pd.DateOffset(months=12)
        prev_end = current_start

    elif period_option == "Last 6 Months":
        current_start = max_date - pd.DateOffset(months=6)
        current_end = max_date

        prev_start = current_start - pd.DateOffset(months=6)
        prev_end = current_start

    elif period_option == "YTD":
        current_start = pd.Timestamp(year=max_date.year, month=1, day=1)
        current_end = max_date

        prev_start = pd.Timestamp(year=max_date.year - 1, month=1, day=1)
        prev_end = pd.Timestamp(
            year=max_date.year - 1,
            month=max_date.month,
            day=max_date.day,
        )

    elif period_option == "QTD":
        current_quarter = ((max_date.month - 1) // 3) + 1
        quarter_start_month = (current_quarter - 1) * 3 + 1

        current_start = pd.Timestamp(
            year=max_date.year,
            month=quarter_start_month,
            day=1,
        )
        current_end = max_date

        prev_start = pd.Timestamp(
            year=max_date.year - 1,
            month=quarter_start_month,
            day=1,
        )
        prev_end = prev_start + (current_end - current_start)

    st.caption(
        f"Periodo actual: {current_start.date()} a {current_end.date()} | "
        f"Comparado contra: {prev_start.date()} a {prev_end.date()}"
    )

    df_current = df_cliente_base[
        (df_cliente_base["fecha"] >= current_start)
        & (df_cliente_base["fecha"] <= current_end)
    ].copy()

    df_previous = df_cliente_base[
        (df_cliente_base["fecha"] >= prev_start)
        & (df_cliente_base["fecha"] <= prev_end)
    ].copy()

    df_cliente = df_current.copy()

    def calc_delta(current, previous):
        if previous == 0:
            return None

        return ((current / previous) - 1) * 100

    ventas_current = df_current["ventas_mm"].sum()
    ventas_prev = df_previous["ventas_mm"].sum()

    utilidad_current = df_current["utilidad_mm"].sum()
    utilidad_prev = df_previous["utilidad_mm"].sum()

    facturas_current = df_current["numero"].nunique()
    facturas_prev = df_previous["numero"].nunique()

    skus_current = df_current["sku"].nunique()
    skus_prev = df_previous["sku"].nunique()

    ventas_delta = calc_delta(ventas_current, ventas_prev)
    utilidad_delta = calc_delta(utilidad_current, utilidad_prev)
    facturas_delta = calc_delta(facturas_current, facturas_prev)
    skus_delta = calc_delta(skus_current, skus_prev)

    resumen_a, resumen_b, resumen_c, resumen_d = st.columns(4)

    with resumen_a:
        st.metric(
            "Ventas total (MM)",
            f"{ventas_current:,.1f}",
            None if ventas_delta is None else f"{ventas_delta:,.1f}%",
        )

    with resumen_b:
        st.metric(
            "Utilidad total (MM)",
            f"{utilidad_current:,.1f}",
            None if utilidad_delta is None else f"{utilidad_delta:,.1f}%",
        )

    with resumen_c:
        st.metric(
            "Facturas",
            f"{facturas_current:,.0f}",
            None if facturas_delta is None else f"{facturas_delta:,.1f}%",
        )

    with resumen_d:
        st.metric(
            "SKUs",
            f"{skus_current:,.0f}",
            None if skus_delta is None else f"{skus_delta:,.1f}%",
        )

    trend = (
        df_cliente.groupby("year_month", as_index=False)
        .agg(
            ventas_mm=("ventas_mm", "sum"),
            utilidad_mm=("utilidad_mm", "sum"),
            facturas=("numero", "nunique"),
            skus=("sku", "nunique"),
        )
        .sort_values("year_month")
    )

    fam_current = (
        df_current.groupby("nombre_familia", as_index=False)
        .agg(
            ventas_mm=("ventas_mm", "sum"),
            utilidad_mm=("utilidad_mm", "sum"),
            skus=("sku", "nunique"),
            facturas=("numero", "nunique"),
        )
    )

    fam_previous = (
        df_previous.groupby("nombre_familia", as_index=False)
        .agg(
            ventas_prev_mm=("ventas_mm", "sum"),
            utilidad_prev_mm=("utilidad_mm", "sum"),
            skus_prev=("sku", "nunique"),
            facturas_prev=("numero", "nunique"),
        )
    )

    fam = fam_current.merge(
        fam_previous,
        on="nombre_familia",
        how="left",
    ).fillna(0)

    fam["ventas_var_pct"] = np.where(
        fam["ventas_prev_mm"] > 0,
        ((fam["ventas_mm"] / fam["ventas_prev_mm"]) - 1) * 100,
        np.nan,
    )

    fam = fam.sort_values("ventas_mm", ascending=False)

    marcas_current = (
        df_current.groupby("sufijo", as_index=False)
        .agg(
            ventas_mm=("ventas_mm", "sum"),
            utilidad_mm=("utilidad_mm", "sum"),
            skus=("sku", "nunique"),
            facturas=("numero", "nunique"),
        )
    )

    marcas_previous = (
        df_previous.groupby("sufijo", as_index=False)
        .agg(
            ventas_prev_mm=("ventas_mm", "sum"),
            utilidad_prev_mm=("utilidad_mm", "sum"),
        )
    )

    marcas = marcas_current.merge(
        marcas_previous,
        on="sufijo",
        how="left",
    ).fillna(0)

    marcas["ventas_var_pct"] = np.where(
        marcas["ventas_prev_mm"] > 0,
        ((marcas["ventas_mm"] / marcas["ventas_prev_mm"]) - 1) * 100,
        np.nan,
    )

    marcas = marcas.sort_values("ventas_mm", ascending=False)

    left, right = st.columns([2, 3])

    with left:
        st.markdown("**Top familias**")

        st.dataframe(
            fam[
                [
                    "nombre_familia",
                    "ventas_mm",
                    "ventas_prev_mm",
                    "ventas_var_pct",
                    "utilidad_mm",
                    "skus",
                    "facturas",
                ]
            ].head(15),
            use_container_width=True,
            height=320,
        )

    with right:
        st.markdown("**Top marcas**")

        st.dataframe(
            marcas[
                [
                    "sufijo",
                    "ventas_mm",
                    "ventas_prev_mm",
                    "ventas_var_pct",
                    "utilidad_mm",
                    "skus",
                    "facturas",
                ]
            ].head(15),
            use_container_width=True,
            height=320,
        )

    st.markdown("**Tendencia mensual**")

    if not trend.empty:
        st.line_chart(
            trend.set_index("year_month")[["ventas_mm", "utilidad_mm"]],
            height=320,
        )
    else:
        st.info("No hay información de tendencia para este cliente en el periodo seleccionado.")