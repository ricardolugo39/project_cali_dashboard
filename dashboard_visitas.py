# dashboard_visitas.py

import sys
from pathlib import Path
import pandas as pd
import streamlit as st

sys.path.append(str(Path.cwd()))

from data.loader import load_tables, load_excel_files
from data.calculations import (
    build_product_classification,
    build_product_families,
    enrich_sales_with_classification,
    build_customer_activity,
    enrich_customers_with_activity,
    enrich_sales_with_customer_activity,
    filter_sales_by_bodega,
    prepare_sales,
)
from data.google_sheets import load_visitas_from_google_sheet


st.set_page_config(
    page_title="Dashboard Comercial Cali",
    layout="wide"
)


# =========================================================
# LOAD DATA
# =========================================================

@st.cache_data
def load_data():
    access_file = "/Users/ricardolugo/Library/CloudStorage/OneDrive-Personal/LH/Reports/sales_lh.accdb"
    tables = ["sales", "customers"]

    data = load_tables(access_file, tables)

    df_sales = data["sales"]
    df_customers = data["customers"]

    (
        df_actividades,
        df_clasificacion,
        df_inventario,
        df_crm,
        df_cotizacion
    ) = load_excel_files()

    df_visitas = load_visitas_from_google_sheet()

    df_grupos = build_product_classification(df_clasificacion)
    df_familias = build_product_families(df_clasificacion)
    df_customer_activity = build_customer_activity(df_actividades)

    df_sales_enriched = enrich_sales_with_classification(
        df_sales,
        df_grupos,
        df_familias
    )

    df_customers_enriched = enrich_customers_with_activity(
        df_customers,
        df_customer_activity
    )

    df_sales_final = enrich_sales_with_customer_activity(
        df_sales_enriched,
        df_customers_enriched
    )

    df_sales_clean = prepare_sales(df_sales_final)

    df_cali = filter_sales_by_bodega(df_sales_clean, 50)

    return df_cali, df_visitas


# =========================================================
# CLEAN CLIENT FIELD
# =========================================================

def clean_cliente_dashboard(df):
    df = df.copy()

    if "Cliente_Nombre" in df.columns:
        cliente_nombre = (
            df["Cliente_Nombre"]
            .astype("object")
            .replace("", pd.NA)
        )
    else:
        cliente_nombre = pd.Series(
            [pd.NA] * len(df),
            index=df.index
        )

    cliente_fallback = (
        df["Cliente"]
        .astype("object")
        .replace("", pd.NA)
    )

    df["Cliente_Dashboard"] = (
        cliente_nombre
        .fillna(cliente_fallback)
        .fillna("SIN CLIENTE")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    return df


# =========================================================
# TOP CLIENTES
# =========================================================

def build_top_clientes(df_cali, df_visitas, top_n=20):
    df_cali = df_cali.copy()
    df_visitas = clean_cliente_dashboard(df_visitas)

    df_cali["fecha"] = pd.to_datetime(
        df_cali["fecha"],
        errors="coerce"
    )

    df_cali["valorbruto"] = pd.to_numeric(
        df_cali["valorbruto"],
        errors="coerce"
    ).fillna(0)

    today = df_cali["fecha"].max()
    start_date = today - pd.DateOffset(months=12)

    df_last12 = df_cali[
        df_cali["fecha"] >= start_date
    ].copy()

    top_clientes = (
        df_last12
        .groupby(
            ["nit", "razonsocial", "actividad_economica"],
            as_index=False
        )
        .agg(
            ventas_12m=("valorbruto", "sum"),
            compras=("numero", "nunique"),
            ultima_compra=("fecha", "max")
        )
    )

    top_clientes["dias_sin_comprar"] = (
        today - top_clientes["ultima_compra"]
    ).dt.days

    actividades_excluir = [
        "COMERCIO EN GENERAL",
        "COMERCIO DE RODAMIENTOS Y AFINES",
        "COMERCIO Y MANTENIMIENTO DE AUTOMOTORES"
    ]

    top_clientes = top_clientes[
        ~top_clientes["actividad_economica"].isin(
            actividades_excluir
        )
    ].copy()

    top_clientes = (
        top_clientes
        .sort_values(
            "ventas_12m",
            ascending=False
        )
        .head(top_n)
    )

    def semaforo_cliente(dias):
        if dias <= 15:
            return "Verde"
        elif dias <= 30:
            return "Amarillo"
        return "Rojo"

    top_clientes["semaforo"] = (
        top_clientes["dias_sin_comprar"]
        .apply(semaforo_cliente)
    )

    top_clientes["Cliente_Key"] = (
        top_clientes["razonsocial"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    # visitas
    df_visitas["Fecha_Visita"] = pd.to_datetime(
        df_visitas["Fecha_Visita"],
        errors="coerce"
    )

    df_visitas["Fecha_Compromiso"] = pd.to_datetime(
        df_visitas["Fecha_Compromiso"],
        errors="coerce"
    )

    df_visitas["Requiere_Accion"] = (
        df_visitas["Requiere_Accion"]
        .astype(str)
        .str.upper()
        .eq("TRUE")
    )

    acciones_pendientes_df = df_visitas[
        (df_visitas["Requiere_Accion"] == True)
        &
        (
            df_visitas["Estado"]
            .astype(str)
            .str.upper()
            .isin(
                ["ABIERTO", "EN SEGUIMIENTO", "PENDIENTE"]
            )
        )
    ].copy()

    resumen_visitas = (
        df_visitas
        .groupby(
            "Cliente_Dashboard",
            as_index=False
        )
        .agg(
            ultima_visita=("Fecha_Visita", "max")
        )
    )

    resumen_acciones = (
        acciones_pendientes_df
        .groupby(
            "Cliente_Dashboard",
            as_index=False
        )
        .agg(
            acciones_pendientes=("ID_Visita", "count"),
            proxima_fecha_compromiso=(
                "Fecha_Compromiso",
                "min"
            )
        )
    )

    dashboard_clientes = (
        top_clientes
        .merge(
            resumen_visitas,
            left_on="Cliente_Key",
            right_on="Cliente_Dashboard",
            how="left"
        )
        .merge(
            resumen_acciones,
            left_on="Cliente_Key",
            right_on="Cliente_Dashboard",
            how="left"
        )
    )

    dashboard_clientes["dias_sin_visita"] = (
        pd.Timestamp.today().normalize()
        - dashboard_clientes["ultima_visita"]
    ).dt.days

    dashboard_clientes["acciones_pendientes"] = (
        dashboard_clientes["acciones_pendientes"]
        .fillna(0)
        .astype(int)
    )

    dashboard_clientes["ultima_visita_display"] = (
        dashboard_clientes["ultima_visita"]
        .dt.strftime("%Y-%m-%d")
        .fillna("No visitado")
    )

    dashboard_clientes["proxima_fecha_compromiso_display"] = (
        dashboard_clientes["proxima_fecha_compromiso"]
        .dt.strftime("%Y-%m-%d")
        .fillna("Sin pendiente")
    )

    dashboard_clientes["dias_sin_visita"] = (
        dashboard_clientes["dias_sin_visita"]
        .fillna(999)
        .astype(int)
    )

    dashboard_clientes["dias_sin_visita_display"] = (
        dashboard_clientes["dias_sin_visita"]
        .apply(
            lambda x:
            "No visitado"
            if x == 999
            else str(x)
        )
    )

    tabla_top_clientes = (
        dashboard_clientes[
            [
                "razonsocial",
                "actividad_economica",
                "ventas_12m",
                "semaforo",
                "ultima_visita_display",
                "dias_sin_visita_display",
                "acciones_pendientes",
                "proxima_fecha_compromiso_display",
            ]
        ]
        .sort_values(
            "ventas_12m",
            ascending=False
        )
        .drop(columns=["ventas_12m"])
        .rename(columns={
            "razonsocial": "Cliente",
            "actividad_economica": "Actividad económica",
            "semaforo": "Semáforo compra",
            "ultima_visita_display": "Última visita",
            "dias_sin_visita_display": "Días sin visita",
            "acciones_pendientes": "Acciones pendientes",
            "proxima_fecha_compromiso_display": "Próximo compromiso",
        })
    )

    return tabla_top_clientes


# =========================================================
# TABLA ASESOR
# =========================================================

def build_tabla_pendientes(df_visitas):
    df = clean_cliente_dashboard(df_visitas)

    df["Fecha_Visita"] = pd.to_datetime(
        df["Fecha_Visita"],
        errors="coerce"
    )

    df["Fecha_Compromiso"] = pd.to_datetime(
        df["Fecha_Compromiso"],
        errors="coerce"
    )

    df["Requiere_Accion"] = (
        df["Requiere_Accion"]
        .astype(str)
        .str.upper()
        .eq("TRUE")
    )

    df["Generar_Oportunidad_CRM"] = (
        df["Generar_Oportunidad_CRM"]
        .astype(str)
        .str.upper()
        .eq("TRUE")
    )

    pendientes = df[
        (df["Requiere_Accion"] == True)
        &
        (
            df["Estado"]
            .astype(str)
            .str.upper()
            != "CERRADO"
        )
    ].copy()

    if pendientes.empty:
        return pd.DataFrame()

    pendientes = pendientes[
        [
            "Asesor",
            "Cliente_Dashboard",
            "Fecha_Visita",
            "Tipo_Visita",
            "Accion_Requerida",
            "Fecha_Compromiso",
            "Estado",
            "Generar_Oportunidad_CRM",
            "Responsable_Seguimiento"
        ]
    ].copy()

    pendientes["Fecha_Visita"] = (
        pendientes["Fecha_Visita"]
        .dt.strftime("%Y-%m-%d")
        .fillna("Sin visita")
    )

    pendientes["Fecha_Compromiso"] = (
        pendientes["Fecha_Compromiso"]
        .dt.strftime("%Y-%m-%d")
        .fillna("Sin fecha")
    )

    pendientes = pendientes.rename(columns={
        "Cliente_Dashboard": "Cliente",
        "Fecha_Visita": "Fecha visita",
        "Tipo_Visita": "Tipo visita",
        "Accion_Requerida": "Acción requerida",
        "Fecha_Compromiso": "Fecha compromiso",
        "Generar_Oportunidad_CRM": "Crear oportunidad CRM",
        "Responsable_Seguimiento": "Responsable seguimiento",
    })

    pendientes = pendientes.sort_values(
        ["Asesor", "Fecha compromiso"],
        ascending=[True, True]
    )

    return pendientes


# =========================================================
# APP
# =========================================================

df_cali, df_visitas = load_data()

tabla_top_clientes = build_top_clientes(
    df_cali,
    df_visitas,
    top_n=20
)

tabla_pendientes = build_tabla_pendientes(
    df_visitas
)

tab1, tab2 = st.tabs([
    "Vista Asesor",
    "Gerencial"
])


# =========================================================
# TAB 1 — VISTA ASESOR
# =========================================================

with tab1:
    st.markdown("""
    <style>
    .header-box {
        background: linear-gradient(90deg, #0b2f5b, #123f73);
        padding: 22px;
        border-radius: 14px;
        color: white;
        margin-bottom: 18px;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="header-box">
        <h2 style="margin:0;">DASHBOARD ASESOR COMERCIAL</h2>
        <p style="margin:0;">Seguimiento de visitas, cobertura comercial y acciones pendientes</p>
    </div>
    """, unsafe_allow_html=True)

    # -------------------------
    # Preparar base visitas
    # -------------------------
    visitas = clean_cliente_dashboard(df_visitas)

    visitas["Fecha_Visita"] = pd.to_datetime(
        visitas["Fecha_Visita"],
        errors="coerce"
    )

    visitas["Requiere_Accion"] = (
        visitas["Requiere_Accion"]
        .astype(str)
        .str.upper()
        .eq("TRUE")
    )

    visitas["Cliente_Key"] = (
        visitas["Cliente_Dashboard"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    # Actividad económica desde df_cali
    actividad_map = (
        df_cali[["razonsocial", "actividad_economica"]]
        .drop_duplicates()
        .copy()
    )

    actividad_map["Cliente_Key"] = (
        actividad_map["razonsocial"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    visitas = visitas.merge(
        actividad_map[["Cliente_Key", "actividad_economica"]],
        on="Cliente_Key",
        how="left"
    )

    visitas["actividad_economica"] = visitas["actividad_economica"].fillna("Sin actividad")

    # -------------------------
    # Filtros
    # -------------------------
    colf1, colf2 = st.columns(2)

    asesores = ["Todos"] + sorted(
        visitas["Asesor"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    asesor_sel = colf1.selectbox(
        "Asesor",
        asesores,
        key="asesor_tab1"
    )

    periodo_sel = colf2.selectbox(
        "Periodo",
        ["Última semana", "MTD", "QTD", "YTD"],
        key="periodo_tab1"
    )

    today = pd.Timestamp.today().normalize()

    if periodo_sel == "Última semana":
        start_date = today - pd.Timedelta(days=7)

    elif periodo_sel == "MTD":
        start_date = pd.Timestamp(year=today.year, month=today.month, day=1)

    elif periodo_sel == "QTD":
        quarter = ((today.month - 1) // 3) + 1
        start_month = (quarter - 1) * 3 + 1
        start_date = pd.Timestamp(year=today.year, month=start_month, day=1)

    elif periodo_sel == "YTD":
        start_date = pd.Timestamp(year=today.year, month=1, day=1)

    visitas_view = visitas[
        visitas["Fecha_Visita"] >= start_date
    ].copy()

    if asesor_sel != "Todos":
        visitas_view = visitas_view[
            visitas_view["Asesor"] == asesor_sel
        ].copy()

    # -------------------------
    # KPIs
    # -------------------------
    total_visitas = len(visitas_view)
    total_clientes = visitas_view["Cliente_Dashboard"].nunique()

    semanas = max(
        ((today - start_date).days / 7),
        1
    )

    visitas_promedio_semanales = total_visitas / semanas

    visitas_con_accion = visitas_view[
        visitas_view["Requiere_Accion"] == True
    ].shape[0]

    clientes_estrategicos = set(
        tabla_top_clientes["Cliente"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    clientes_visitados = set(
        visitas_view["Cliente_Dashboard"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    clientes_estrategicos_visitados = len(
        clientes_estrategicos.intersection(clientes_visitados)
    )

    visitas_sin_accion = visitas_view[
        visitas_view["Requiere_Accion"] == False
    ].shape[0]

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    col1.metric("# Visitas", total_visitas)
    col2.metric("# Clientes", total_clientes)
    col3.metric("Prom. semanal", round(visitas_promedio_semanales, 1))
    col4.metric("Con acción pendiente", visitas_con_accion)
    col5.metric("Clientes estratégicos", clientes_estrategicos_visitados)
    col6.metric("Sin acción definida", visitas_sin_accion)

    st.divider()

# -------------------------
# Gráficas
# -------------------------

colg1, colg2, colg3 = st.columns(3)

with colg1:
    st.subheader("Visitas por asesor")

    if not visitas_view.empty:
        visitas_asesor = (
            visitas_view["Asesor"]
            .value_counts()
            .sort_values(ascending=True)
        )

        st.bar_chart(
            visitas_asesor,
            horizontal=True
        )
    else:
        st.info("No hay visitas para el filtro seleccionado.")


with colg2:
    st.subheader("Visitas por tipo")

    if not visitas_view.empty:
        visitas_tipo = (
            visitas_view["Tipo_Visita"]
            .value_counts()
            .reset_index()
        )

        visitas_tipo.columns = [
            "Tipo de visita",
            "Cantidad"
        ]

        st.dataframe(
            visitas_tipo,
            width="stretch",
            hide_index=True
        )

    else:
        st.info("No hay visitas para el filtro seleccionado.")


with colg3:
    st.subheader("Visitas por actividad económica")

    if not visitas_view.empty:
        actividad_chart = (
            visitas_view["actividad_economica"]
            .value_counts()
            .head(10)
        )

        st.bar_chart(
            actividad_chart
        )
    else:
        st.info("No hay visitas para el filtro seleccionado.")


# IMPORTANTE:
# DESDE AQUÍ YA FUERA DE LAS COLUMNAS

st.divider()

# -------------------------
# Tabla últimas visitas
# -------------------------

st.subheader("Resumen de últimas visitas")

ultimas_visitas = visitas_view[
    [
        "Fecha_Visita",
        "Asesor",
        "Cliente_Dashboard",
        "Tipo_Visita",
        "actividad_economica",
        "Resumen_Ejecutivo",
        "Requiere_Accion",
        "Accion_Requerida",
        "Estado",
    ]
].copy()

ultimas_visitas["Fecha_Visita"] = (
    ultimas_visitas["Fecha_Visita"]
    .dt.strftime("%Y-%m-%d")
)

ultimas_visitas = ultimas_visitas.rename(columns={
    "Fecha_Visita": "Fecha visita",
    "Cliente_Dashboard": "Cliente",
    "Tipo_Visita": "Tipo visita",
    "actividad_economica": "Actividad económica",
    "Resumen_Ejecutivo": "Resumen",
    "Requiere_Accion": "Requiere acción",
    "Accion_Requerida": "Acción requerida",
})

ultimas_visitas = ultimas_visitas.sort_values(
    "Fecha visita",
    ascending=False
)

st.dataframe(
    ultimas_visitas,
    width="stretch",
    hide_index=True
)

st.divider()

# -------------------------
# Clientes estratégicos no visitados
# -------------------------

st.subheader("Clientes estratégicos no visitados en el periodo")

clientes_no_visitados = tabla_top_clientes[
    ~tabla_top_clientes["Cliente"]
    .astype(str)
    .str.upper()
    .str.strip()
    .isin(clientes_visitados)
].copy()

st.dataframe(
    clientes_no_visitados,
    width="stretch",
    hide_index=True
)