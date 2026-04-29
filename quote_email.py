import base64
import os.path
from email.mime.text import MIMEText
from pathlib import Path

import numpy as np
import pandas as pd

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# =========================================================
# GMAIL AUTH
# =========================================================

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose"
]


def gmail_auth():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file(
            "token.json",
            SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    service = build(
        "gmail",
        "v1",
        credentials=creds
    )

    return service


# =========================================================
# LOAD CRM
# =========================================================

def load_quotes():

    base_path = Path(__file__).resolve().parent

    cotizacion_path = base_path / "data" / "cotizacion.xlsx"

    df_cotizacion = pd.read_excel(cotizacion_path)

    return df_cotizacion

def prepare_quotes_cali(df_cotizacion):
    df = df_cotizacion.copy()

    df.columns = df.columns.str.strip()

    df["Fecha Doc"] = pd.to_datetime(
        df["Fecha Doc"],
        errors="coerce",
        dayfirst=True
    )

    df["Valor Documento"] = pd.to_numeric(
        df["Valor Documento"],
        errors="coerce"
    ).fillna(0)

    df["Usuario"] = (
        df["Usuario"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    df["Estado"] = (
        df["Estado"]
        .astype(str)
        .str.strip()
    )

    df["Anulado"] = (
        df["Anulado"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    vendedores_cali = [
        "JVERA",
        "JHOLGUIN",
        "YRENTERIA",
        "AJIMENEZ",
    ]

    df_cali = df[
        (df["Usuario"].isin(vendedores_cali))
        & (df["Anulado"] == "N")
    ].copy()

    return df_cali


def get_weekly_quotes(df):
    today = pd.Timestamp.today().normalize()

    start_date = today - pd.Timedelta(days=7)
    end_date = today

    df_period = df[
        (df["Fecha Doc"] >= start_date)
        & (df["Fecha Doc"] <= end_date)
    ].copy()

    df_priority = df_period[
        (df_period["Estado"] == "Pendiente")
        & (df_period["Valor Documento"] >= 5_000_000)
    ].copy()

    df_priority["Dias Pendiente"] = (
        end_date - df_priority["Fecha Doc"]
    ).dt.days

    return df_period, df_priority, start_date, end_date


def summarize_by_vendor(df_cali, df_priority):
    summary = []

    for usuario in sorted(df_cali["Usuario"].dropna().unique()):
        df_vendor_all = df_cali[df_cali["Usuario"] == usuario].copy()
        df_vendor_priority = df_priority[df_priority["Usuario"] == usuario].copy()

        total_quotes = len(df_vendor_all)
        total_value = df_vendor_all["Valor Documento"].sum()

        pending = df_vendor_all[df_vendor_all["Estado"] == "Pendiente"]
        billed = df_vendor_all[df_vendor_all["Estado"] == "Facturado"]

        pending_count = len(pending)
        billed_count = len(billed)

        pending_value = pending["Valor Documento"].sum()
        billed_value = billed["Valor Documento"].sum()

        efficiency_count = (
            billed_count / total_quotes
            if total_quotes > 0
            else 0
        )

        efficiency_value = (
            billed_value / total_value
            if total_value > 0
            else 0
        )

        summary.append({
            "Usuario": usuario,
            "Cotizaciones": total_quotes,
            "Valor Total": total_value,
            "Pendientes": pending_count,
            "Valor Pendiente": pending_value,
            "Facturadas": billed_count,
            "Valor Facturado": billed_value,
            "Eficiencia Cantidad": efficiency_count,
            "Eficiencia Valor": efficiency_value,
            "Prioritarias >5M": len(df_vendor_priority),
            "Valor Prioritario": df_vendor_priority["Valor Documento"].sum(),
        })

    return pd.DataFrame(summary)

def format_cop(value):
    return f"${value:,.0f}".replace(",", ".")


def format_pct(value):
    return f"{value * 100:,.1f}%".replace(",", "X").replace(".", ",").replace("X", ".")


def build_vendor_quote_summary(df_cali, df_priority, usuario, start_date, end_date):
    df_vendor_all = df_cali[df_cali["Usuario"] == usuario].copy()
    df_vendor_priority = df_priority[df_priority["Usuario"] == usuario].copy()

    total_quotes = len(df_vendor_all)
    total_value = df_vendor_all["Valor Documento"].sum()

    pending = df_vendor_all[df_vendor_all["Estado"] == "Pendiente"]
    billed = df_vendor_all[df_vendor_all["Estado"] == "Facturado"]

    pending_count = len(pending)
    billed_count = len(billed)

    pending_value = pending["Valor Documento"].sum()
    billed_value = billed["Valor Documento"].sum()

    efficiency_count = billed_count / total_quotes if total_quotes > 0 else 0
    efficiency_value = billed_value / total_value if total_value > 0 else 0

    priority_rows = ""

    for _, row in df_vendor_priority.sort_values(
        "Valor Documento",
        ascending=False
    ).iterrows():

        priority_rows += f"""
        <tr>
            <td>{int(row["Número"])}</td>
            <td>{row["Fecha Doc"].strftime("%d/%m/%Y")}</td>
            <td>{row["Nombre"]}</td>
            <td style="text-align:right;">{format_cop(row["Valor Documento"])}</td>
            <td>{row["Estado"]}</td>
            <td style="text-align:center;">{int(row["Dias Pendiente"])}</td>
            <td>Registrar o actualizar oportunidad en Sigma</td>
        </tr>
        """

    if priority_rows == "":
        priority_rows = """
        <tr>
            <td colspan="7" style="padding:12px; text-align:center;">
                No tienes cotizaciones pendientes mayores a $5.000.000 en este periodo.
            </td>
        </tr>
        """

    body = f"""
        <html>
        <body style="
            font-family: Arial, sans-serif;
            font-size:14px;
            color:#222;
            line-height:1.5;
        ">

        <h2 style="margin-bottom:5px;">
            Seguimiento de Cotizaciones – {usuario}
        </h2>

        <p>
            Hola <strong>{usuario}</strong>,
        </p>

        <p>
            Este es tu seguimiento semanal de cotizaciones.
        </p>

        <h3 style="margin-top:30px; margin-bottom:15px; color:#0d47a1;">
            KPIs DEL PERIODO
        </h3>

        <table style="
            width:100%;
            border-collapse:separate;
            border-spacing:12px;
        ">
            <tr>
                <td style="border:1px solid #ddd; padding:15px;">
                    <strong>Cotizaciones creadas</strong><br>
                    <span style="font-size:24px;">{total_quotes}</span>
                </td>

                <td style="border:1px solid #ddd; padding:15px;">
                    <strong>Valor total cotizado</strong><br>
                    <span style="font-size:24px;">{format_cop(total_value)}</span>
                </td>

                <td style="border:1px solid #ddd; padding:15px;">
                    <strong>Pendientes</strong><br>
                    <span style="font-size:24px;">{pending_count}</span>
                </td>

                <td style="border:1px solid #ddd; padding:15px;">
                    <strong>Valor pendiente</strong><br>
                    <span style="font-size:24px;">{format_cop(pending_value)}</span>
                </td>
            </tr>

            <tr>
                <td style="border:1px solid #ddd; padding:15px;">
                    <strong>Facturadas</strong><br>
                    <span style="font-size:24px;">{billed_count}</span>
                </td>

                <td style="border:1px solid #ddd; padding:15px;">
                    <strong>Valor facturado</strong><br>
                    <span style="font-size:24px;">{format_cop(billed_value)}</span>
                </td>

                <td style="border:1px solid #ddd; padding:15px;">
                    <strong>Eficiencia cantidad</strong><br>
                    <span style="font-size:24px;">{format_pct(efficiency_count)}</span>
                </td>

                <td style="border:1px solid #ddd; padding:15px;">
                    <strong>Eficiencia valor</strong><br>
                    <span style="font-size:24px;">{format_pct(efficiency_value)}</span>
                </td>
            </tr>
        </table>

        <p style="margin-top:25px;">
            Estas son tus cotizaciones pendientes mayores a
            <strong>$5.000.000</strong> correspondientes al periodo del
            <strong>{start_date.strftime('%d/%m/%Y')}</strong> al
            <strong>{end_date.strftime('%d/%m/%Y')}</strong>.
        </p>

        <h3 style="margin-top:30px; margin-bottom:15px; color:#0d47a1;">
            ACCIONES REQUERIDAS
        </h3>

        <p>
            Las siguientes cotizaciones deben ser revisadas y, si siguen activas,
            registradas o actualizadas como oportunidades en Sigma.
        </p>

        <table style="
            width:100%;
            border-collapse:collapse;
            font-size:13px;
        ">
            <thead>
                <tr style="background:#0d47a1; color:white;">
                    <th style="padding:10px;">Número</th>
                    <th style="padding:10px;">Fecha</th>
                    <th style="padding:10px;">Cliente</th>
                    <th style="padding:10px;">Valor</th>
                    <th style="padding:10px;">Estado</th>
                    <th style="padding:10px;">Días pendiente</th>
                    <th style="padding:10px;">Acción requerida</th>
                </tr>
            </thead>

            <tbody>
                {priority_rows}
            </tbody>
        </table>

        <p style="margin-top:25px;">
            Una vez registres la oportunidad en Sigma, por favor responde este mismo correo indicando:
        </p>

        <ul>
            <li>Número de cotización</li>
            <li>Número de oportunidad creada en Sigma</li>
        </ul>

        <p>
            Ejemplo:
        </p>

        <p style="
            background:#f5f5f5;
            padding:12px;
            border-left:4px solid #0d47a1;
        ">
            Cotización: 42877<br>
            Oportunidad Sigma: 2-PC1-845
        </p>

        <p style="margin-top:30px;">
            Por favor revisar estas cotizaciones y actualizar Sigma según corresponda.
        </p>

        <p>
            Ricardo
        </p>

        </body>
        </html>
        """

    return body

def create_quote_email_drafts(df_cali, df_priority, start_date, end_date):
    service = gmail_auth()

    email_map = {
        "JVERA": "jairo.vera@lugohermanos.com",
        "JHOLGUIN": "jeisman-holguin@lugohermanos.com",
        "YRENTERIA": "yeisson.renteria@lugohermanos.com",
        "AJIMENEZ": "andrea.jimenez@lugohermanos.com",
    }

    cc_emails = (
        "ricardo.lugo@lugohermanos.com, "
        "marialucy.florez@lugohermanos.com, "
        "nicolas.lugo@lugohermanos.com, "
        "gerencia@lugohermanos.com"
    )

    for usuario, receiver_email in email_map.items():
        body = build_vendor_quote_summary(
            df_cali=df_cali,
            df_priority=df_priority,
            usuario=usuario,
            start_date=start_date,
            end_date=end_date
        )

        subject = (
            f"Seguimiento cotizaciones "
            f"{start_date.strftime('%d/%m/%Y')} - "
            f"{end_date.strftime('%d/%m/%Y')} – {usuario}"
        )

        message = MIMEText(body, "html", "utf-8")

        message["To"] = receiver_email
        message["Cc"] = cc_emails
        message["Subject"] = subject

        raw_message = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode()

        draft_body = {
            "message": {
                "raw": raw_message
            }
        }

        service.users().drafts().create(
            userId="me",
            body=draft_body
        ).execute()

        print(f"Draft creado para {usuario} → {receiver_email}")

if __name__ == "__main__":
    df_cotizacion = load_quotes()

    df_cotizacion_cali = prepare_quotes_cali(df_cotizacion)

    df_period, df_priority, start_date, end_date = get_weekly_quotes(
    df_cotizacion_cali
    )

    create_quote_email_drafts(
        df_period,
        df_priority,
        start_date,
        end_date
    )

    print("Todos los drafts de cotizaciones fueron creados correctamente.")