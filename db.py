import pyodbc
import os
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')}"
    )

def run_query(sql: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    conn.close()
    return [dict(zip(columns, row)) for row in rows]

import pymysql

def get_cache_connection():
    return pymysql.connect(
        host=os.getenv("CACHE_DB_HOST"),
        user=os.getenv("CACHE_DB_USER"),
        password=os.getenv("CACHE_DB_PASSWORD"),
        database=os.getenv("CACHE_DB_NAME"),
        port=int(os.getenv("CACHE_DB_PORT")),
        cursorclass=pymysql.cursors.DictCursor  # ✅ enables dict-style access
    )

def get_cached_sql(prompt: str):
    conn = get_cache_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT `sql` FROM llm_cache WHERE prompt = %s", (prompt,))
        row = cursor.fetchone()
    conn.close()
    return row["sql"] if row and "sql" in row else None


def save_sql_to_cache(prompt: str, sql: str):
    conn = get_cache_connection()
    with conn.cursor() as cursor:
        try:
            cursor.execute(
                "INSERT IGNORE INTO llm_cache (prompt, `sql`, created_at) VALUES (%s, %s, NOW())",
                    (prompt, sql)
            )

            conn.commit()
        except Exception as e:
            print("[CACHE SAVE ERROR]", e)
    conn.close()

from difflib import SequenceMatcher

def find_similar_prompt(prompt: str, threshold: float = 0.85):
    conn = get_cache_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT prompt, `sql` FROM llm_cache")
        rows = cursor.fetchall()
    conn.close()

    user_building = extract_building_number(prompt)
    best_match = None
    highest_ratio = 0

    for row in rows:
        cached_prompt = row["prompt"]
        cached_building = extract_building_number(cached_prompt)

        # Only compare if buildings match or both are unspecified
        if user_building != cached_building:
            continue

        ratio = SequenceMatcher(None, prompt.lower(), cached_prompt.lower()).ratio()

        if ratio > highest_ratio and ratio >= threshold:
            highest_ratio = ratio
            best_match = row

    return best_match


import re

def extract_building_number(text: str):
    match = re.search(r'\bbuilding\s*(\d+)', text.lower())
    return match.group(1) if match else None

def get_all_cached_sql():
    conn = get_cache_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT prompt, `sql` FROM llm_cache")
        rows = cursor.fetchall()  # Already dicts because of DictCursor
    conn.close()
    return rows






