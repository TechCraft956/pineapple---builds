"""3D Trend Scraper GUI — manual-paste fallback (the workflow that worked).

Open the site in a browser, copy the page text, paste it here; the GUI
parses it into the same normalized trend records the scrapers emit and
saves JSON + CSV. Sources: Thingiverse, Printables, Google Trends (paste
a trends CSV export). Licence is not in pasted text, so pasted records
stay sellable=False ("licence: unknown") until a model page is checked.
"""
import os
import tkinter as tk
from tkinter import scrolledtext, ttk
import webbrowser

from src.processors.data_cleaner import save_records
from src.processors.paste_parser import parse_pasted_text

SITE_URLS = {
    "Thingiverse": "https://www.thingiverse.com",
    "Printables": "https://www.printables.com",
    "Google Trends": "https://trends.google.com",
}


class TrendScraperGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("3D Trend Scraper")
        self.root.geometry("600x450")

        os.makedirs("data", exist_ok=True)

        self.label = tk.Label(root, text="Select Source:")
        self.label.pack(pady=(10, 0))

        self.scraper_choice = ttk.Combobox(
            root, values=list(SITE_URLS), state="readonly")
        self.scraper_choice.pack(pady=5)
        self.scraper_choice.current(0)

        self.run_button = tk.Button(root, text="Open Website",
                                    command=self.run_scraper)
        self.run_button.pack(pady=5)

        self.text_area_label = tk.Label(root, text="Paste copied data below:")
        self.text_area_label.pack(pady=(10, 0))

        self.text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD,
                                                   width=70, height=12)
        self.text_area.pack(padx=10, pady=5)
        self.text_area.focus_set()

        self.submit_button = tk.Button(root, text="Submit",
                                       command=self.process_input)
        self.submit_button.pack(pady=10)

        self.status_label = tk.Label(root, text="", fg="green")
        self.status_label.pack(pady=5)

    def run_scraper(self):
        """Open the selected website for manual data extraction."""
        selected = self.scraper_choice.get()
        webbrowser.open(SITE_URLS.get(selected, "https://www.thingiverse.com"))
        self.root.after(1000, lambda: self.text_area.focus_set())

    def process_input(self):
        """Parse pasted text into trend records and save them."""
        user_input = self.text_area.get("1.0", tk.END).strip()
        if not user_input:
            self.status_label.config(text="No data entered!", fg="red")
            return
        selected = self.scraper_choice.get()
        source = {"Thingiverse": "thingiverse",
                  "Printables": "printables",
                  "Google Trends": "google_trends"}.get(selected, "thingiverse")
        try:
            records = parse_pasted_text(user_input, source=source)
        except ValueError as exc:
            self.status_label.config(text=str(exc), fg="red")
            return
        if not records:
            self.status_label.config(
                text="No models found in pasted text.", fg="red")
            return
        json_path, csv_path = save_records(records)
        self.status_label.config(
            text=f"Saved {len(records)} records: {json_path}", fg="green")


def main():
    root = tk.Tk()
    TrendScraperGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
