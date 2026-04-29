import pandas as pd
import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

SPREADSHEET_ID_VISITAS = "168FSopPqvlI5hUgM3Uzk9fRsa51zF2Uem5DYJD3JjJ8"
WORKSHEET_VISITAS = "Visitas"

SPREADSHEET_ID_CALI = "1MgbbhbYUvm9NHBtKqRI7MuvTtw7RONifqwoke-R49Ro"
WORKSHEET_CALI = "df_cali"


def get_google_creds():
    service_account_info = dict(st.secrets["gcp_service_account"])
    return Credentials.from_service_account_info(
        service_account_info,
        scopes=SCOPES,
    )


def load_visitas_from_google_sheet():
    creds = get_google_creds()
    client = gspread.authorize(creds)

    sheet = client.open_by_key(SPREADSHEET_ID_VISITAS)
    worksheet = sheet.worksheet(WORKSHEET_VISITAS)

    return pd.DataFrame(worksheet.get_all_records())


def load_df_cali_from_google_sheet():
    creds = get_google_creds()
    client = gspread.authorize(creds)

    sheet = client.open_by_key(SPREADSHEET_ID_CALI)
    worksheet = sheet.worksheet(WORKSHEET_CALI)

    return pd.DataFrame(worksheet.get_all_records())