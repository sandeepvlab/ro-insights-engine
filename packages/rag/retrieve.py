import os
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}

EMBEDDING_MODEL = "text-embedding-3-small"


def get_embedding(text: str):
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text
    )
    return response.data[0].embedding


def retrieve_relevant_chunks(query: str, state_code: str = None, top_k: int = 3):
    """
    Retrieve the most relevant warranty-rule chunks for a query,
    optionally filtered to a specific state.
    """
    query_embedding = get_embedding(query)

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    if state_code:
        cur.execute(
            """
            SELECT state, source_doc, chunk_text,
                   embedding <=> %s::vector AS distance
            FROM warranty_rule_chunks
            WHERE state = %s
            ORDER BY distance
            LIMIT %s
            """,
            (query_embedding, state_code, top_k)
        )
    else:
        cur.execute(
            """
            SELECT state, source_doc, chunk_text,
                   embedding <=> %s::vector AS distance
            FROM warranty_rule_chunks
            ORDER BY distance
            LIMIT %s
            """,
            (query_embedding, top_k)
        )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {"state": r[0], "source_doc": r[1], "chunk_text": r[2], "distance": float(r[3])}
        for r in rows
    ]


if __name__ == "__main__":
    # Quick manual test
    results = retrieve_relevant_chunks("What is the statutory labor rate?", state_code="WA")
    for r in results:
        print(f"[{r['state']}] {r['source_doc']} (distance={r['distance']:.4f})")
        print(r["chunk_text"][:150])
        print("---")