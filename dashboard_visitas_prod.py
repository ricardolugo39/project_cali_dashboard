from jinja2 import Environment, FileSystemLoader
import sys
from pathlib import Path
from io import BytesIO
import pandas as pd
import streamlit as st

sys.path.append(str(Path.cwd()))

BASE_DIR = Path(__file__).parent

from data.google_sheets import (
    load_visitas_from_google_sheet,
    load_df_cali_from_google_sheet,
)


st.set_page_config(
    page_title="Dashboard Comercial Cali",
    layout="wide"
)


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
        .apply(lambda x: "No visitado" if x == 999 else str(x))
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

def safe_value(value, default=""):
    if pd.isna(value):
        return default
    value = str(value).strip()
    return value if value else default


def build_visit_report_html(row):

    env = Environment(
        loader=FileSystemLoader(BASE_DIR / "templates"),
        autoescape=True
    )

    template = env.get_template("visit_report.html")

    fecha_visita = row.get("Fecha_Visita")

    if pd.notna(fecha_visita):
        fecha_visita = pd.to_datetime(fecha_visita).strftime("%Y-%m-%d")
    else:
        fecha_visita = ""

    fecha_compromiso = row.get("Fecha_Compromiso")

    if pd.notna(fecha_compromiso):
        fecha_compromiso = pd.to_datetime(fecha_compromiso).strftime("%Y-%m-%d")
    else:
        fecha_compromiso = "Sin fecha definida"

    responsable = safe_value(
        row.get("Responsable_Seguimiento_nombre"),
        safe_value(row.get("Asesor"))
    )

    html_report = template.render(
        cliente=safe_value(row.get("Cliente_Nombre")),
        nit=safe_value(row.get("Cliente")),
        fecha_visita=fecha_visita,
        asesor=safe_value(row.get("Asesor")),
        contacto=safe_value(row.get("Contacto_Visitado")),
        cargo=safe_value(row.get("Cargo_Contacto")),
        tipo_visita=safe_value(row.get("Tipo_Visita")),
        motivo=safe_value(row.get("Motivo_Visita"), "No informado"),
        resumen=safe_value(row.get("Resumen_Ejecutivo"), "No informado"),
        necesidad=safe_value(row.get("Necesidad_Detectada"), "No informado"),
        accion=safe_value(row.get("Accion_Requerida"), "No se registraron acciones pendientes."),
        responsable=responsable,
        estado=safe_value(row.get("Estado"), "Sin estado"),
        fecha_compromiso=fecha_compromiso
    )

    return html_report

def html_to_pdf_bytes(html_content):
    try:
        from xhtml2pdf import pisa
    except ImportError:
        return None

    pdf_buffer = BytesIO()

    pisa_status = pisa.CreatePDF(
        src=html_content,
        dest=pdf_buffer
    )

    if pisa_status.err:
        return None

    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()
# =========================================================
# APP
# =========================================================

df_cali, df_visitas = load_data()

tabla_top_clientes = build_top_clientes(
    df_cali,
    df_visitas,
    top_n=20
)

tab1, tab2, tab3 = st.tabs([
    "Vista Asesor",
    "Gerencial",
    "Cliente 360"
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

    # filtros
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
        asesores
    )

    periodo_sel = colf2.selectbox(
        "Periodo",
        ["Última semana", "MTD", "QTD", "YTD"]
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
    else:
        start_date = pd.Timestamp(year=today.year, month=1, day=1)

    visitas_view = visitas[
        visitas["Fecha_Visita"] >= start_date
    ].copy()

    if asesor_sel != "Todos":
        visitas_view = visitas_view[
            visitas_view["Asesor"] == asesor_sel
        ].copy()

    # KPIs
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

    # gráficas
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

    st.divider()

    # tabla últimas visitas
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


# =========================================================
# TAB 2 — GERENCIAL
# =========================================================

with tab2:
    st.title("Dashboard Gerencial")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Clientes estratégicos",
        len(tabla_top_clientes)
    )

    col2.metric(
        "Clientes no visitados",
        (
            tabla_top_clientes["Última visita"]
            == "No visitado"
        ).sum()
    )

    col3.metric(
        "Acciones pendientes",
        tabla_top_clientes[
            "Acciones pendientes"
        ].sum()
    )

    col4.metric(
        "Clientes amarillo/rojo",
        tabla_top_clientes[
            "Semáforo compra"
        ].isin(
            ["Amarillo", "Rojo"]
        ).sum()
    )

    st.divider()

    st.subheader("Top Clientes Estratégicos")

    st.dataframe(
        tabla_top_clientes,
        width="stretch",
        hide_index=True
    )

# =========================================================
# TAB 3 — CLIENTE 360
# =========================================================

with tab3:
    st.title("Cliente 360")

    visitas_360 = clean_cliente_dashboard(df_visitas)

    visitas_360["Fecha_Visita"] = pd.to_datetime(
        visitas_360["Fecha_Visita"],
        errors="coerce"
    )

    visitas_360["Fecha_Compromiso"] = pd.to_datetime(
        visitas_360["Fecha_Compromiso"],
        errors="coerce"
    )

    visitas_360["Requiere_Accion"] = (
        visitas_360["Requiere_Accion"]
        .astype(str)
        .str.upper()
        .eq("TRUE")
    )

    visitas_360["Estado_Normalizado"] = (
        visitas_360["Estado"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    clientes = sorted(
        visitas_360["Cliente_Dashboard"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    cliente_sel = st.selectbox(
        "Seleccionar cliente",
        clientes
    )

    cliente_df = visitas_360[
        visitas_360["Cliente_Dashboard"] == cliente_sel
    ].copy()

    cliente_df = cliente_df.sort_values(
        "Fecha_Visita",
        ascending=False
    )

    acciones_abiertas = cliente_df[
        (cliente_df["Requiere_Accion"] == True)
        &
        (cliente_df["Estado_Normalizado"].isin([
            "ABIERTO",
            "EN SEGUIMIENTO",
            "PENDIENTE"
        ]))
    ].copy()

    today = pd.Timestamp.today().normalize()

    acciones_abiertas["Dias_Vencido"] = (
        today - acciones_abiertas["Fecha_Compromiso"]
    ).dt.days

    acciones_vencidas = acciones_abiertas[
        acciones_abiertas["Dias_Vencido"] > 0
    ].copy()

    ultima_visita = cliente_df["Fecha_Visita"].max()

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Visitas registradas",
        len(cliente_df)
    )

    col2.metric(
        "Última visita",
        ultima_visita.strftime("%Y-%m-%d") if pd.notna(ultima_visita) else "Sin visita"
    )

    col3.metric(
        "Acciones abiertas",
        len(acciones_abiertas)
    )

    col4.metric(
        "Acciones vencidas",
        len(acciones_vencidas)
    )

    st.divider()

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("Resumen del cliente")

        ultimo_registro = cliente_df.iloc[0]

        st.markdown(f"""
        **Cliente:** {cliente_sel}  
        **Último asesor:** {ultimo_registro.get("Asesor", "")}  
        **Último contacto:** {ultimo_registro.get("Contacto_Visitado", "")}  
        **Cargo:** {ultimo_registro.get("Cargo_Contacto", "")}  
        **Tipo última visita:** {ultimo_registro.get("Tipo_Visita", "")}
        """)

        st.subheader("Última necesidad detectada")
        st.info(
            ultimo_registro.get("Necesidad_Detectada", "Sin información")
        )

    with col_right:
        st.subheader("Riesgos y competencia")

        riesgos = (
            cliente_df["Riesgo_Detectado"]
            .dropna()
            .astype(str)
            .str.strip()
        )

        riesgos = riesgos[riesgos != ""]

        competencia = (
            cliente_df["Competencia_Presente"]
            .dropna()
            .astype(str)
            .str.strip()
        )

        competencia = competencia[competencia != ""]

        if not riesgos.empty:
            st.markdown("**Riesgos detectados:**")
            for riesgo in riesgos.unique():
                st.warning(riesgo)
        else:
            st.write("No hay riesgos registrados.")

        if not competencia.empty:
            st.markdown("**Competencia presente:**")
            for comp in competencia.unique():
                st.info(comp)
        else:
            st.write("No hay competencia registrada.")

    st.divider()

    st.subheader("Acciones pendientes")

    if acciones_abiertas.empty:
        st.success("Este cliente no tiene acciones abiertas.")
    else:
        tabla_acciones = acciones_abiertas[
            [
                "Fecha_Visita",
                "Asesor",
                "Accion_Requerida",
                "Responsable_Seguimiento_nombre",
                "Fecha_Compromiso",
                "Dias_Vencido",
                "Estado",
            ]
        ].copy()

        tabla_acciones["Fecha_Visita"] = tabla_acciones["Fecha_Visita"].dt.strftime("%Y-%m-%d")
        tabla_acciones["Fecha_Compromiso"] = tabla_acciones["Fecha_Compromiso"].dt.strftime("%Y-%m-%d")

        tabla_acciones = tabla_acciones.rename(columns={
            "Fecha_Visita": "Fecha visita",
            "Asesor": "Asesor",
            "Accion_Requerida": "Acción requerida",
            "Responsable_Seguimiento_nombre": "Responsable",
            "Fecha_Compromiso": "Fecha compromiso",
            "Dias_Vencido": "Días vencido",
            "Estado": "Estado",
        })

        st.dataframe(
            tabla_acciones,
            width="stretch",
            hide_index=True
        )

    st.divider()

    st.subheader("Historial de visitas")

    historial = cliente_df[
        [
            "Fecha_Visita",
            "Asesor",
            "Tipo_Visita",
            "Motivo_Visita",
            "Resumen_Ejecutivo",
            "Necesidad_Detectada",
            "Requiere_Accion",
            "Estado",
        ]
    ].copy()

    historial["Fecha_Visita"] = historial["Fecha_Visita"].dt.strftime("%Y-%m-%d")

    historial = historial.rename(columns={
        "Fecha_Visita": "Fecha visita",
        "Tipo_Visita": "Tipo visita",
        "Motivo_Visita": "Motivo",
        "Resumen_Ejecutivo": "Resumen",
        "Necesidad_Detectada": "Necesidad detectada",
        "Requiere_Accion": "Requiere acción",
    })

    st.dataframe(
        historial,
        width="stretch",
        hide_index=True
    )

    st.divider()

    st.subheader("Generar reporte de visita")

    visitas_opciones = cliente_df.copy()

    visitas_opciones["visita_label"] = (
        visitas_opciones["Fecha_Visita"].dt.strftime("%Y-%m-%d")
        + " | "
        + visitas_opciones["Asesor"].astype(str)
        + " | "
        + visitas_opciones["Motivo_Visita"].astype(str)
    )

    visita_label_sel = st.selectbox(
        "Seleccionar visita",
        visitas_opciones["visita_label"].tolist()
    )

    visita_row = visitas_opciones[
        visitas_opciones["visita_label"] == visita_label_sel
    ].iloc[0]

    html_report = build_visit_report_html(visita_row)
    pdf_bytes = html_to_pdf_bytes(html_report)

    with st.expander("Vista previa del reporte"):
        st.markdown(html_report, unsafe_allow_html=True)

    report_id = safe_value(
        visita_row.get("ID_Visita"),
        "sin_id"
    )

    if pdf_bytes:
        st.download_button(
            label="Descargar PDF",
            data=pdf_bytes,
            file_name=f"reporte_visita_{report_id}.pdf",
            mime="application/pdf"
        )
    else:
        st.warning(
            "No se pudo generar PDF. Puedes descargar el reporte en HTML."
        )

        st.download_button(
            label="Descargar reporte HTML",
            data=html_report.encode("utf-8"),
            file_name=f"reporte_visita_{report_id}.html",
            mime="text/html"
        )