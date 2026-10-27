"""
Method 2: API feasibility study

Purpose:
    Investigate whether a public API can provide useful financial/economic
    data for a loan-approval dataset.

This example uses the World Bank public API. It is NOT bank customer data.
The experiment demonstrates API acquisition, JSON parsing and tabular storage.
"""

import requests
import pandas as pd

API_URL = (
    "https://api.worldbank.org/v2/country/IND/"
    "indicator/NY.GDP.PCAP.CD?format=json&per_page=10"
)

response = requests.get(API_URL, timeout=15)
response.raise_for_status()

payload = response.json()

records = payload[1]

rows = []
for item in records:
    rows.append({
        "country": item.get("country", {}).get("value"),
        "year": item.get("date"),
        "gdp_per_capita": item.get("value"),
    })

df = pd.DataFrame(rows)

print("Data fetched from public API:")
print(df)

print("\nFinding:")
print("The API successfully provides public economic indicators.")
print("However, it does not provide individual loan applications or")
print("loan approval/rejection labels required for our ML problem.")

df.to_csv("api_financial_indicator_sample.csv", index=False)
print("\nSaved: api_financial_indicator_sample.csv")
