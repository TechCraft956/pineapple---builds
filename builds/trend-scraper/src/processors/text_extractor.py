import json
import logging
import re

# Configure logging
logging.basicConfig(filename="text_extractor.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def sanitize_text(text):
    """Cleans input text to prevent errors."""
    text = re.sub(r"[+]", "", text)  # Remove `+` symbols
    text = re.sub(r"[/]", "-", text)  # Replace `/` with `-`
    text = re.sub(r"[^\w\s\-,]", "", text)  # Remove special characters except `-` and `,`
    text = re.sub(r"\s+", " ", text).strip()  # Remove extra spaces
    return text

def save_to_json(data, filename="extracted_results.json"):
    """Saves cleaned data to JSON."""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    logging.info(f"Results saved to {filename}")

def main():
    print("\n*** Copy text from Google Trends / Thingiverse / GrabCAD, then paste it below. Type 'done' when finished. ***")
    user_input = []

    while True:
        try:
            line = input("> ").strip()
            if line.lower() == "done":
                break
            user_input.append(sanitize_text(line))  # Clean each line
        except KeyboardInterrupt:
            print("\nExiting...")
            return

    text_data = "\n".join(user_input)

    # Save to JSON
    save_to_json({"extracted_text": text_data})

    print("\n✅ Data successfully extracted and saved!")
    logging.info("Text extraction complete.")

if __name__ == "__main__":
    main()
