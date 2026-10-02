"""
Method 1: Web-scraping feasibility study

Purpose:
    Check whether a publicly accessible webpage provides
    loan application data with approval/rejection labels.

Note:
    This study does not access private or confidential bank data.
"""

import pandas as pd
import requests
from bs4 import BeautifulSoup

URL = "https://www.kaggle.com/datasets/itssuru/loan-data"

headers = {
    "User-Agent": "Academic data-collection feasibility study"
}

response = requests.get(URL, headers=headers, timeout=15)

print("HTTP Status:", response.status_code)

if response.ok:

    soup = BeautifulSoup(response.text, "html.parser")

    try:
        tables = pd.read_html(str(soup))
        print("Public HTML tables found:", len(tables))

        for i, table in enumerate(tables):
            print(f"\nTable {i}:")
            print(table.head())

    except ValueError:
        print("No HTML tables found on the webpage.")
        print("Finding: The required loan application data")
        print("was not directly available as an HTML table.")

else:
    print("The webpage could not be fetched directly.")

print("\nConclusion:")
print("- Public webpages may contain useful financial information.")
print("- Complete applicant-level loan decisions are generally not")
print("  available as directly accessible public HTML data.")
print("- Therefore, web scraping was not selected as the primary data source.")