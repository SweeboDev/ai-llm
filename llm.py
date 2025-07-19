import os
import re
import json
import datetime

from dotenv import load_dotenv
from difflib import SequenceMatcher
from db import run_query
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

load_dotenv()

with open("prompts/examples.json", "r", encoding="utf-8") as f:
    ALL_EXAMPLES = json.load(f)
    
from openai import AzureOpenAI

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version=os.getenv("AZURE_OPENAI_VERSION", "2025-01-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
}

KEYWORD_ALIASES = {
    "kw": ["power", "energy", "load", "consumption"],
    "temperature": ["temp", "heat", "cooling"],
    "humidity": ["moisture"],
    "outside": ["weather", "external"],
}
OCN_MAP = {
    "microsoft": "Microsoft_ECw6jl6b75sU",
    "oracle": "Oracle_SuQDd8B3ozL8",
    "bank of america": "BoA_43Ahafdsb63",
    "mitsubishi": "Mit_75AJfamdnuj"
}

def save_prompt_response_log(prompt, response_sql, matched_example=None, metadata=None):
    log_data = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "original_prompt": prompt,
        "response_sql": response_sql,
        "matched_example": matched_example["user"] if matched_example else None,
        "metadata": metadata or {}
    }

    try:
        with open("logs/fine_tune_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(log_data) + "\n")
    except Exception as e:
        print(f"[LOGGING ERROR] {e}")

def should_compare_real_weather(prompt: str) -> bool:
    return "real world weather" in prompt.lower() or "compare to real weather" in prompt.lower()


def log_token_usage(context_label, response):
    try:
        usage = response.usage
        if DEBUG:
            print(f"[GPT USAGE] context={context_label} prompt_tokens={usage.prompt_tokens} "
              f"completion_tokens={usage.completion_tokens} total={usage.total_tokens}")
    except:
        if DEBUG:
            print(f"[GPT USAGE] context={context_label} usage data not available")

def replace_ocn_names(prompt: str) -> str:
    prompt_lower = prompt.lower()
    for name, ocn in OCN_MAP.items():
        if name in prompt_lower:
            prompt = re.sub(name, ocn, prompt, flags=re.IGNORECASE)
    return prompt


def ask_gpt_to_choose(prompt, candidates):
    formatted = "\n".join(
        f"{i+1}. {ex['user']}" for i, ex in enumerate(candidates)
    )

    system_msg = (
        "You are a matcher. A user asked a telemetry question. "
        "Choose the best-matching example from the list. "
        "Return ONLY the number of the best match (like '2'). No explanation."
    )

    user_msg = f"""
User prompt:
"{prompt}"

Available examples:
{formatted}
""".strip()

    try:
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            max_tokens=5
        )
        if DEBUG:
            print("\n[GPT MATCHING DEBUG]")
            print("System message:", system_msg)
            print("User message:", user_msg)
            print("GPT response:", response.choices[0].message.content.strip())

        log_token_usage("example_match", response)

        choice = int(response.choices[0].message.content.strip())
        return candidates[choice - 1]

    except Exception as e:
        if DEBUG:
            print(f"[GPT MATCHING ERROR] {str(e)}")
        return candidates[0]



def expand_tokens(tokens):
    expanded = set(tokens)
    for token in tokens:
        for key, synonyms in KEYWORD_ALIASES.items():
            if token == key or token in synonyms:
                expanded.update(synonyms)
                expanded.add(key)
    return expanded

def tokenize(text):
    return set(re.findall(r'\b\w+\b', text.lower()))

def score_example(prompt_tokens, example_keywords):
    return len(prompt_tokens & set(example_keywords))

def find_relevant_examples(prompt, is_historical=False, max_results=5):
    prompt_tokens = expand_tokens(tokenize(prompt))
    scored = []
    if DEBUG:
        print(f"\n🔍 User Prompt: {prompt}")
        print(f"🧠 Tokens: {sorted(prompt_tokens)}\n")

    for ex in ALL_EXAMPLES:
        category = ex.get("category", "")
        if is_historical and "historical" not in category and "lookup" not in category:
            continue
        if not is_historical and "historical" in category:
            continue


        ex_keywords = set(ex.get("keywords", []))
        score = len(prompt_tokens & ex_keywords)
        if prompt.lower() in ex["user"].lower():
            score += 2

        if score > 0:
            scored.append((score, ex))
            if DEBUG:
                print(f"✅ MATCH ({score}): \"{ex['user']}\"")
                print(f"   Overlap: {sorted(prompt_tokens & ex_keywords)}\n")

    top = sorted(scored, key=lambda x: x[0], reverse=True)[:max_results]

    if not top:
        if DEBUG:
            print("⚠️ No good matches found.\n")
        return []
    
    if len(top) == 1:
        best = top[0][1]
    else:
        best = ask_gpt_to_choose(prompt, [e for _, e in top])
    if DEBUG:
        print(f"🏆 Final match selected by GPT: \"{best['user']}\"\n")
    return [best]



def is_historical_prompt(prompt: str) -> bool:
    try:
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=[
                {
                    "role": "system",
                    "content": (
    "You are a strict binary classifier. "
    "Answer 'yes' ONLY if the user is asking for historical telemetry data. "
    "That includes ANY of the following:\n"
    "- A specific year (e.g., '2022', '2025')\n"
    "- Named months (e.g., 'April', 'June')\n"
    "- Phrases like 'last month', 'last year', 'yesterday', or 'previous'\n"
    "- Comparisons across time (e.g., 'compare this year to last year')\n"
    "If the prompt is about current, now, or latest readings, respond with 'no'.\n"
    "Your response must be only 'yes' or 'no'."
)

                },
                {"role": "user", "content": prompt}
            ],
            max_tokens=1
        )
        answer = response.choices[0].message.content.strip().lower()
        if DEBUG:
            print(f"[HISTORICAL DETECTION] GPT says: {answer}")
        return answer.startswith("y")
    except Exception as e:
        if DEBUG:
            print("[HISTORICAL DETECTION] GPT check failed:", str(e))
        return False

def extract_time_range(prompt: str) -> tuple[str, str] | None:
    """Extract a date range from the user prompt using GPT."""
    try:
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=[
                {"role": "system", "content": (
                    "Extract a start and end date (in ISO 8601 format: YYYY-MM-DD) from the following prompt. "
                    "Return only the range like '2025-04-01 to 2025-05-01'. No explanation."
                )},
                {"role": "user", "content": prompt}
            ],
            max_tokens=20
        )
        raw = response.choices[0].message.content.strip()
        if DEBUG:
            print(f"[GPT TIME RANGE] {raw}")
        parts = raw.split(" to ")
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
    except Exception as e:
        if DEBUG:
            print(f"[TIME RANGE ERROR] {str(e)}")
    return None



def clean_sql(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw, flags=re.IGNORECASE).strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    lines = raw.splitlines()
    sql_lines = []
    started = False
    for line in lines:
        stripped = line.strip()
        if not started and (stripped.lower().startswith("select") or stripped.lower().startswith("with")):
            started = True
        if started:
            sql_lines.append(stripped)

    cleaned = "\n".join(sql_lines).strip()
    cleaned = cleaned.replace("`", "").strip().rstrip(";")

    


    return cleaned




def strip_csv_markers(sql: str) -> str:
    if "[CSV_DATA_START]" in sql:
        sql = sql.split("[CSV_DATA_START]", 1)[1]
    if "[CSV_DATA_END]" in sql:
        sql = sql.split("[CSV_DATA_END]", 1)[0]
    return sql.strip()


def query_llm(prompt: str):
    original_prompt = prompt.strip()
    prompt = replace_ocn_names(original_prompt)
    lower = original_prompt.lower()

    

    if "table view" in lower or "as a table" in lower or "detailed list" in lower:
        prompt += " (Return full table of readings, not just an average)"

    for name, num in MONTH_MAP.items():
        if f"month of {name}" in lower:
            prompt += f" (Use MONTH(timestamp) = {num} AND YEAR(timestamp) = YEAR(GETDATE()))"

    is_historical = is_historical_prompt(original_prompt)
    if DEBUG:
        print(f"[LLM] Is historical? {'Yes' if is_historical else 'No'}")
    with open("prompts/base_rules.txt", "r", encoding="utf-8") as f:

        base_prompt = f.read()

    examples_list = find_relevant_examples(prompt, is_historical)
    examples = "\n\n".join([
        f"User: {ex['user']}\nSQL:\n{ex['sql']}" for ex in examples_list
    ])
    if DEBUG:
        print(f"[LLM] Loaded {len(examples_list)} examples from examples.json")

    if not is_historical and ("humidity" in lower or "temperature" in lower):

        building_match = re.search(r'\b(?:building\s*|b)(\d{1,2})\b', lower)
        if building_match:
            building_num = int(building_match.group(1))
            prompt += f" (Use building B{building_num})"
            dh_matches = re.findall(r'datahall\s*(\d{1,3})', lower)
            if dh_matches:
                dh_list = [f"'DH{str(int(d)).zfill(2)}'" for d in dh_matches]
                prompt += f" (Use DH IN ({', '.join(dh_list)}))"

        else:
            prompt += " (No building specified – use wildcard for building)"


    full_prompt = f"{base_prompt}\n\n### Examples:\n\n{examples}\n\n### Prompt:\n{prompt}"
    response = client.chat.completions.create(
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        messages=[
            {"role": "system", "content": "You generate ONLY raw T-SQL queries for telemetry analysis. No explanations. Do not use ```."},
            {"role": "user", "content": full_prompt}
        ],
        max_tokens=768
    )
    log_token_usage("sql_generation", response)
    raw_sql = strip_csv_markers(response.choices[0].message.content.strip())
    cleaned = clean_sql(raw_sql)

    save_prompt_response_log(
        original_prompt,
        cleaned,
        matched_example=examples_list[0] if examples_list else None,
        metadata={
            "is_historical": is_historical,
            "raw_sql": raw_sql
        }
    )


    return cleaned


    

