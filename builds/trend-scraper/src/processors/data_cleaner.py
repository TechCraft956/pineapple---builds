"""Data cleaning + saving (recovered code, extended for trend records).

Original functions kept (clean_data / save_data operate on plain text
lines, as the GUI used them). New: save_records() writes normalized
TrendRecords as JSON + CSV, the same shape every scraper emits.
"""
import csv
import json
import os

from src.models import RECORD_FIELDS, TrendRecord


def clean_data(raw_text):
    """
    Cleans raw text input by removing empty lines and redundant data.

    Args:
        raw_text (str): The raw text data copied from the website.

    Returns:
        list: A list of cleaned text lines.
    """
    lines = raw_text.split("\n")
    cleaned_lines = [line.strip() for line in lines if line.strip()]
    return cleaned_lines


def save_data(cleaned_data, filename="cleaned_trends"):
    """
    Saves cleaned data in both JSON and CSV formats.

    Args:
        cleaned_data (list): A list of cleaned text data.
        filename (str, optional): The filename to save the data. Defaults to "cleaned_trends".

    Returns:
        tuple: Paths of the saved JSON and CSV files.
    """
    # Ensure 'data' directory exists
    os.makedirs("data", exist_ok=True)

    # Save as JSON
    json_path = f"data/{filename}.json"
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving JSON file: {e}")
        return None

    # Save as CSV
    csv_path = f"data/{filename}.csv"
    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for row in cleaned_data:
                writer.writerow([row])
    except Exception as e:
        print(f"Error saving CSV file: {e}")
        return None

    print(f"Data saved successfully! JSON: {json_path} | CSV: {csv_path}")
    return json_path, csv_path


def save_records(records, filename="trend_records", out_dir="data"):
    """Save normalized TrendRecords as JSON + CSV (one row per record)."""
    os.makedirs(out_dir, exist_ok=True)
    dicts = [r.to_dict() if isinstance(r, TrendRecord) else dict(r)
             for r in records]
    json_path = os.path.join(out_dir, f"{filename}.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(dicts, fh, indent=2, ensure_ascii=False)
    csv_path = os.path.join(out_dir, f"{filename}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(RECORD_FIELDS))
        writer.writeheader()
        for d in dicts:
            writer.writerow({k: d.get(k, "") for k in RECORD_FIELDS})
    return json_path, csv_path
