import os
import pickle
import pandas as pd
import streamlit as st
import gspread

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from data.google_sheets import load_visitas_from_google_sheet


# =========================================================
# CONFIG
# =========================================================

st.set_page_config(
    page_title="Dashboard Comercial Cali",
    layout="wide"
)

SPREADSHEET_ID_CALI = "PEGAR_ID_DEL_GOOGLE_SHEET_DF_CALI"
WORKSHEET_CALI = "df_cali"

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token_sheets.pickle"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]


# =========================================================
# GOOGLE AUTH
# =========================================================

def get_google_creds():
    creds = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE,
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)

    return creds


# =========================================================
# LOAD DF CALI FROM GOOGLE SHEETS
# =========================================================

def load_df_cali_from_google_sheet():
    creds = get_google_creds()
    client = gspread.authorize(creds)

    sheet = client.open_by_key(SPREADSHEET_ID_CALI)
    worksheet = sheet.worksheet(WORKSHEET_CALI)

    records = worksheet.get_all_records()
    df_cali = pd.DataFrame(records)

    if "fecha" in df_cali.columns:
        df_cali["fecha"] = pd.to_datetime(
            df_cali["fecha"],
            errors="coerce"
        )

    if "valorbruto" in df_cali.columns:
        df_cali["valorbruto"] = pd.to_numeric(
            df_cali["valorbruto"],
            errors="coerce"
        ).fillna(0)

    return df_cali


# =========================================================
# LOAD DATA
# =========================================================

@st.cache_data(ttl=600)
def load_data():
    df_cali = load_df_cali_from_google_sheet()
    df_visitas = load_visitas_from_google_sheet()
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
        .sort_values("ventas_12m", ascending=False)
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

    df_visitas["Fecha_Visita"] = pd.to_datetime(
        df_visitas["Fecha_Visita"],
        errors="coerce"
    )

    resumen_visitas = (
        df_visitas
        .groupby("Cliente_Dashboard", as_index=False)
        .agg(
            ultima_visita=("Fecha_Visita", "max")
        )
    )

    dashboard_clientes = top_clientes.merge(
        resumen_visitas,
        left_on="Cliente_Key",
        right_on="Cliente_Dashboard",
        how="left"
    )

    dashboard_clientes["ultima_visita_display"] = (
        dashboard_clientes["ultima_visita"]
        .dt.strftime("%Y-%m-%d")
        .fillna("No visitado")
    )

    tabla = (
        dashboard_clientes[
            [
                "razonsocial",
                "actividad_economica",
                "semaforo",
                "ultima_visita_display",
            ]
        ]
        .rename(columns={
            "razonsocial": "Cliente",
            "actividad_economica": "Actividad económica",
            "semaforo": "Semáforo compra",
            "ultima_visita_display": "Última visita",
        })
    )

    return tabla


# =========================================================
# APP
# =========================================================

df_cali, df_visitas = load_data()

tabla_top_clientes = build_top_clientes(
    df_cali,
    df_visitas,
    top_n=20
)

tab1, tab2 = st.tabs([
    "Vista Asesor",
    "Gerencial"
])


# =========================================================
# TAB 1
# =========================================================

with tab1:
    st.title("Dashboard Asesor Comercial")

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

    col1, col2 = st.columns(2)

    asesores = ["Todos"] + sorted(
        visitas["Asesor"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    asesor_sel = col1.selectbox(
        "Asesor",
        asesores
    )

    periodo_sel = col2.selectbox(
        "Periodo",
        ["Última semana", "MTD", "QTD", "YTD"]
    )

    today = pd.Timestamp.today().normalize()

    if periodo_sel == "Última semana":
        start_date = today - pd.Timedelta(days=7)
    elif periodo_sel == "MTD":
        start_date = pd.Timestamp(today.year, today.month, 1)
    elif periodo_sel == "QTD":
        quarter = ((today.month - 1) // 3) + 1
        start_month = (quarter - 1) * 3 + 1
        start_date = pd.Timestamp(today.year, start_month, 1)
    else:
        start_date = pd.Timestamp(today.year, 1, 1)

    visitas_view = visitas[
        visitas["Fecha_Visita"] >= start_date
    ].copy()

    if asesor_sel != "Todos":
        visitas_view = visitas_view[
            visitas_view["Asesor"] == asesor_sel
        ]

    total_visitas = len(visitas_view)
    total_clientes = visitas_view["Cliente_Dashboard"].nunique()
    visitas_con_accion = visitas_view["Requiere_Accion"].sum()

    semanas = max(
        ((today - start_date).days / 7),
        1
    )

    promedio_semanal = round(
        total_visitas / semanas,
        1
    )

    k1, k2, k3, k4 = st.columns(4)

    k1.metric("# Visitas", total_visitas)
    k2.metric("# Clientes", total_clientes)
    k3.metric("Promedio semanal", promedio_semanal)
    k4.metric("Con acción pendiente", visitas_con_accion)

    st.divider()

    st.subheader("Clientes estratégicos")

    st.dataframe(
        tabla_top_clientes,
        width="stretch",
        hide_index=True
    )

    st.divider()

    st.subheader("Últimas visitas")

    resumen = visitas_view[
        [
            "Fecha_Visita",
            "Asesor",
            "Cliente_Dashboard",
            "Tipo_Visita",
            "Requiere_Accion",
            "Accion_Requerida",
            "Estado"
        ]
    ].copy()

    resumen["Fecha_Visita"] = (
        resumen["Fecha_Visita"]
        .dt.strftime("%Y-%m-%d")
    )

    resumen = resumen.rename(columns={
        "Fecha_Visita": "Fecha visita",
        "Cliente_Dashboard": "Cliente",
        "Tipo_Visita": "Tipo visita",
        "Requiere_Accion": "Requiere acción",
        "Accion_Requerida": "Acción requerida",
    })

    st.dataframe(
        resumen.sort_values(
            "Fecha visita",
            ascending=False
        ),
        width="stretch",
        hide_index=True
    )


# =========================================================
# TAB 2
# =========================================================

with tab2:
    st.title("Dashboard Gerencial")

    st.dataframe(
        tabla_top_clientes,
        width="stretch",
        hide_index=True
    )