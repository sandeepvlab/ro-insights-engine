import os
import glob
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv

# Load .env variables (POSTGRES_*, OPENAI_API_KEY)
load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}

WARRANTY_RULES_DIR = "data/warranty-rules"
EMBEDDING_MODEL = "text-embedding-3-small"


def get_embedding(text: str):
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text
    )
    return response.data[0].embedding


def chunk_text(text: str, max_chars: int = 800):
    """Simple paragraph-based chunking. Good enough for short docs like ours."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current = ""
    for p in paragraphs:
        if len(current) + len(p) < max_chars:
            current += ("\n\n" if current else "") + p
        else:
            if current:
                chunks.append(current)
            current = p
    if current:
        chunks.append(current)
    return chunks


def infer_state_code(filename: str):
    # e.g. "wa_warranty_rules.md" -> "WA"
    base = os.path.basename(filename)
    return base.split("_")[0].upper()


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Clear existing chunks so re-running this script doesn't duplicate data
    cur.execute("DELETE FROM warranty_rule_chunks;")
    conn.commit()

    files = glob.glob(os.path.join(WARRANTY_RULES_DIR, "*.md"))
    print(f"Found {len(files)} warranty rule files.")

    for filepath in files:
        state_code = infer_state_code(filepath)
        with open(filepath, "r") as f:
            text = f.read()

        chunks = chunk_text(text)
        print(f"  {filepath} -> {len(chunks)} chunk(s), state={state_code}")

        for chunk in chunks:
            embedding = get_embedding(chunk)
            cur.execute(
                """
                INSERT INTO warranty_rule_chunks (state, source_doc, chunk_text, embedding)
                VALUES (%s, %s, %s, %s)
                """,
                (state_code, os.path.basename(filepath), chunk, embedding)
            )

    conn.commit()
    cur.close()
    conn.close()
    print("Ingestion complete.")


if __name__ == "__main__":
    main()