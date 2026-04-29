# crm_email_drafts.py

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

def load_crm():

    base_path = Path(__file__).resolve().parent

    crm_path = base_path / "data" / "crm.xlsx"

    df = pd.read_excel(crm_path)

    return df


# =========================================================
# PREP CRM
# =========================================================

def prepare_crm_cali(df_crm):
    df = df_crm.copy()

    df.columns = df.columns.str.strip()

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df["Fecha Cierre"] = pd.to_datetime(df["Fecha Cierre"], errors="coerce")

    df["Ingreso"] = pd.to_numeric(
        df["Ingreso"],
        errors="coerce"
    ).fillna(0)

    df["Probabilidad"] = pd.to_numeric(
        df["Probabilidad"],
        errors="coerce"
    ).fillna(0)

    df["Probabilidad_clean"] = df["Probabilidad"]

    df.loc[
        df["Estado"] == "Cancelado",
        "Probabilidad_clean"
    ] = 0

    df.loc[
        df["Estado"] == "Realizado",
        "Probabilidad_clean"
    ] = 100

    df["Ingreso_ponderado"] = (
        df["Ingreso"]
        * df["Probabilidad_clean"]
        / 100
    )

    today = pd.Timestamp.today().normalize()

    df["Dias_para_cierre"] = (
        df["Fecha Cierre"] - today
    ).dt.days

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

    df["Vendedor"] = (
        df["Vendedor"]
        .astype(str)
        .str.strip()
    )

    df_cali = df[
        df["Vendedor"].isin(vendedores_cali)
    ].copy()

    return df_cali


# =========================================================
# BUILD EMAIL BODY
# =========================================================

def build_vendor_crm_summary(df_crm_cali, vendedor):
    df_vendor = df_crm_cali[
        df_crm_cali["Vendedor"] == vendedor
    ].copy()

    abiertas = df_vendor[
        df_vendor["Estado"] == "Abierto"
    ].copy()

    realizadas = df_vendor[
        df_vendor["Estado"] == "Realizado"
    ].copy()

    canceladas = df_vendor[
        df_vendor["Estado"] == "Cancelado"
    ].copy()

    oportunidades_abiertas = len(abiertas)
    oportunidades_vencidas = int(
        abiertas["Oportunidad_vencida"].sum()
    )

    pipeline_total = abiertas["Ingreso"].sum()
    pipeline_ponderado = abiertas["Ingreso_ponderado"].sum()

    valor_realizado = realizadas["Ingreso"].sum()
    valor_cancelado = canceladas["Ingreso"].sum()

    win_rate_cantidad = (
        len(realizadas) /
        (len(realizadas) + len(canceladas))
        if (len(realizadas) + len(canceladas)) > 0
        else 0
    )

    win_rate_valor = (
        valor_realizado /
        (valor_realizado + valor_cancelado)
        if (valor_realizado + valor_cancelado) > 0
        else 0
    )

    top_ops = (
        abiertas
        .sort_values(
            ["Oportunidad_vencida", "Ingreso"],
            ascending=[False, False]
        )
        .head(15)
        .copy()
    )

    top_rows = ""

    for _, row in top_ops.iterrows():
        vencida = "Sí" if row["Oportunidad_vencida"] else "No"

        dias_color = "#d32f2f" if row["Oportunidad_vencida"] else "#2e7d32"

        top_rows += f"""
        <tr>
            <td>{row['Fecha Cierre'].date() if pd.notnull(row['Fecha Cierre']) else ''}</td>
            <td>{row.get('Nombre empresa', '')}</td>
            <td>{row.get('Documento', '')}</td>
            <td>{row['Ingreso']/1_000_000:,.1f}</td>
            <td>{row['Probabilidad_clean']:.0f}%</td>
            <td>{row.get('Etapa', '')}</td>
            <td style="color:{dias_color}; font-weight:600;">
                {int(row.get('Dias_vencida', 0))}
            </td>
            <td>{vencida}</td>
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
        Seguimiento CRM – {vendedor}
    </h2>

    <p>
        Hola <strong>{vendedor}</strong>,
    </p>

    <p>
        Este es tu seguimiento semanal de oportunidades CRM.
    </p>

    <h3 style="
        margin-top:30px;
        margin-bottom:15px;
        color:#0d47a1;
    ">
        KPIs ACTUALES
    </h3>

    <table style="
        width:100%;
        border-collapse:separate;
        border-spacing:12px;
    ">
        <tr>
            <td style="border:1px solid #ddd; padding:15px;">
                <strong>Oportunidades Abiertas</strong><br>
                <span style="font-size:24px;">{oportunidades_abiertas}</span>
            </td>

            <td style="border:1px solid #ddd; padding:15px;">
                <strong>Oportunidades Vencidas</strong><br>
                <span style="font-size:24px; color:#d32f2f;">
                    {oportunidades_vencidas}
                </span>
            </td>

            <td style="border:1px solid #ddd; padding:15px;">
                <strong>Pipeline Abierto</strong><br>
                <span style="font-size:24px;">
                    {pipeline_total/1_000_000:,.1f} MM
                </span>
            </td>

            <td style="border:1px solid #ddd; padding:15px;">
                <strong>Pipeline Ponderado</strong><br>
                <span style="font-size:24px;">
                    {pipeline_ponderado/1_000_000:,.1f} MM
                </span>
            </td>
        </tr>

        <tr>
            <td style="border:1px solid #ddd; padding:15px;">
                <strong>Valor Realizado</strong><br>
                <span style="font-size:24px;">
                    {valor_realizado/1_000_000:,.1f} MM
                </span>
            </td>

            <td style="border:1px solid #ddd; padding:15px;">
                <strong>Valor Cancelado</strong><br>
                <span style="font-size:24px;">
                    {valor_cancelado/1_000_000:,.1f} MM
                </span>
            </td>

            <td style="border:1px solid #ddd; padding:15px;">
                <strong>Win Rate Cantidad</strong><br>
                <span style="font-size:24px;">
                    {win_rate_cantidad*100:,.1f}%
                </span>
            </td>

            <td style="border:1px solid #ddd; padding:15px;">
                <strong>Win Rate Valor</strong><br>
                <span style="font-size:24px;">
                    {win_rate_valor*100:,.1f}%
                </span>
            </td>
        </tr>
    </table>

    <h3 style="
        margin-top:30px;
        margin-bottom:15px;
        color:#0d47a1;
    ">

    ACCIONES REQUERIDAS

</h3>

<p>

    Por favor revisar cada oportunidad y actualizar el CRM según corresponda:

</p>

<ul>

    <li>

        <strong>Si la oportunidad sigue activa:</strong>

        actualizar la fecha de cierre con una fecha realista y dejar un seguimiento claro.

    </li>

    <li>

        <strong>Si la oportunidad avanzó:</strong>

        actualizar la etapa comercial para reflejar el estado actual de la negociación.

    </li>

    <li>

        <strong>Si ya se concretó la venta:</strong>

        cambiar el estado a <strong>Realizado</strong>.

    </li>

    <li>

        <strong>Si el negocio se perdió o ya no aplica:</strong>

        cambiar el estado a <strong>Cancelado</strong>.

    </li>

    <li>

        <strong>Si la oportunidad está vencida:</strong>

        no debe quedar igual. Debe actualizarse, cerrarse o justificarse.

    </li>

</ul>

    <h3 style="
        margin-top:30px;
        margin-bottom:15px;
        color:#0d47a1;
    ">
        Oportunidades abiertas (TOP a revisar)
    </h3>

    <table style="
        width:100%;
        border-collapse:collapse;
        font-size:13px;
    ">
        <thead>
            <tr style="
                background:#0d47a1;
                color:white;
            ">
                <th style="padding:10px;">Fecha Cierre</th>
                <th style="padding:10px;">Cliente</th>
                <th style="padding:10px;">Documento</th>
                <th style="padding:10px;">Valor (MM)</th>
                <th style="padding:10px;">Prob %</th>
                <th style="padding:10px;">Etapa</th>
                <th style="padding:10px;">Días vencida</th>
                <th style="padding:10px;">Vencida</th>
            </tr>
        </thead>

        <tbody>
            {top_rows}
        </tbody>
    </table>

    <p style="margin-top:30px;">
        El lunes revisaré nuevamente el pipeline actualizado.
    </p>

    <p>
        Ricardo
    </p>

    </body>
    </html>
    """

    return body


# =========================================================
# CREATE DRAFTS
# =========================================================

def create_crm_email_drafts(df_crm_cali):
    service = gmail_auth()

    email_map = {
        "JAIRO DAVID VERA": "jairo.vera@lugohermanos.com",
        "JEISMAN HOLGUIN": "jeisman-holguin@lugohermanos.com",
        "YEISSON ANDRES RENTERIA MOSQUERA": "yeisson.renteria@lugohermanos.com",
        "NUBIA ANDREA JIMENEZ": "andrea.jimenez@lugohermanos.com",
    }
    cc_emails = [
        "ricardo.lugo@lugohermanos.com",
        "marialucy.florez@lugohermanos.com",
        "nicolas.lugo@lugohermanos.com",
        "gerencia@lugohermanos.com",
    ]

    for vendedor, receiver_email in email_map.items():

        body = build_vendor_crm_summary(df_crm_cali, vendedor)

        subject = f"Seguimiento CRM – {vendedor}"

        message = MIMEText(body, "html", "utf-8")

        message["To"] = receiver_email
        message["Cc"] = (

            "ricardo.lugo@lugohermanos.com, "

            "marialucy.florez@lugohermanos.com, "

            "nicolas.lugo@lugohermanos.com, "

            "gerencia@lugohermanos.com"

        )
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

        print(f"Draft creado para {vendedor} → {receiver_email}")


if __name__ == "__main__":
    df_crm_raw = load_crm()
    df_crm_cali = prepare_crm_cali(df_crm_raw)

    create_crm_email_drafts(df_crm_cali)

    print("Todos los drafts fueron creados correctamente.")