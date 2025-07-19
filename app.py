from flask import Flask, request, jsonify
from flask_cors import CORS
from db import run_query
from llm import query_llm
from formatting import format_reply
import re
import json
import datetime
import logging
from openai import AzureOpenAI
import os
from flask import send_file
from llm import should_compare_real_weather
from utils import get_real_world_temp, check_sla_breaches, load_sla_for_location, get_extremes_near_sla
import requests



# Configure logging
logging.basicConfig(
    filename='chatbot.log',
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Initialize OpenAI client
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version=os.getenv("AZURE_OPENAI_VERSION", "2023-05-15"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)


app = Flask(__name__)
CORS(app)

@app.route('/ask', methods=['POST'])
def ask():
    prompt = request.json.get("prompt")
    print(f"[PROMPT] {prompt}")
    logging.info(f"[PROMPT] {prompt}")

    
    # 🧠 Otherwise continue as normal
    sql = query_llm(prompt)

# 🔁 If the result is already a natural language response (e.g. SLA summary), send it back directly
    if sql and not sql.lower().startswith("select"):
        print(f"[GPT-RESPONSE] {sql}")

    

        return jsonify({
        "prompt": prompt,
        "reply": sql,
        "sql": None,
        "result": None
        })



    if sql and sql.startswith("```"):
        sql = re.sub(r"^```[a-zA-Z]*\n?", "", sql.strip(), flags=re.IGNORECASE)
        sql = sql.rstrip("`").strip()

    # Normalize columns
    sql = re.sub(r"\bPointName\b", "[Point Name]", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bPoint_Name\b", "[Point Name]", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bGlobalAssetID\b", "Global_Asset_ID", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bGatewayTimestamp\b", "gateway_timestamp", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bReadValue\b", "readvalue", sql, flags=re.IGNORECASE)

    print(f"[SQL] {sql}")
    logging.info(f"[SQL] {sql}")

    try:
        result = run_query(sql)
        print(f"[RESULT] {result}")
        logging.info(f"[RESULT] {result}")


        if "sla" in prompt.lower() and "breach" in prompt.lower():
            site_match = re.search(r"\b(PAR1|INZ4|LON3|OSA1)\b", prompt.upper())
            building_match = re.search(r"building\s*(\d+)", prompt.lower())
            datahall_match = re.search(r"datahall\s*(\d+)", prompt.lower())

            if site_match and building_match and datahall_match:
                site = site_match.group(1).upper()
                building = f"B{int(building_match.group(1))}"
                datahall = f"DH{int(datahall_match.group(1)):02d}"

                sla = load_sla_for_location(site, building, datahall)
                if sla:
                    breaches = check_sla_breaches(result, sla)
                    if breaches:
                        # Format for GPT summarization
                       
                        reply = format_reply(prompt, breaches)
                        return jsonify({
                        "prompt": prompt,
                        "reply": reply,
                        "sql": sql,
                        "result": breaches
                        })
                    else:
                        

                    # Add proximity summary
                        extremes = get_extremes_near_sla(result, sla)
                        extra_summary = []

                        if "temp_max_actual" in extremes:
                            extra_summary.append(f"Hottest: {extremes['temp_max_actual']}°C (limit: {extremes['temp_max_sla']}°C)")
                            extra_summary.append(f"Coldest: {extremes['temp_min_actual']}°C (limit: {extremes['temp_min_sla']}°C)")

                        if "hum_max_actual" in extremes:
                            extra_summary.append(f"Most humid: {extremes['hum_max_actual']}% (limit: {extremes['hum_max_sla']}%)")
                            extra_summary.append(f"Least humid: {extremes['hum_min_actual']}% (limit: {extremes['hum_min_sla']}%)")

                        summary = "No SLA breaches detected.\n" + "\n".join(extra_summary)

                        return jsonify({
                            "prompt": prompt,
                            "reply": summary,
                            "sql": sql,
                            "result": result
                        }) 
                else:
                    return jsonify({
                        "prompt": prompt,
                        "reply": f"No SLA configuration found for {site} {building} {datahall}.",
                        "sql": sql,
                        "result": result
                    })

        if "create me a dashboard" in prompt.lower() or "generate a dashboard" in prompt.lower():
    # Parse for multiple questions (existing logic from previous suggestion)
            match = re.search(r"Create me a dashboard for (.*)", prompt, re.IGNORECASE)
            if match:
                questions_str = match.group(1).strip()
                questions = [q.strip() + '?' if not q.strip().endswith('?') else q.strip() for q in re.split(r'\?,\s*', questions_str) if q.strip()]
            else:
                questions = [prompt]

            graphs = []
            for question in questions:
                try:
        # Generate SQL individually for each question
                    sql = query_llm(question)
                    sql = sql.strip().strip("`").rstrip(";")
                    graphs.append({
            "title": question.rstrip('?'),
            "prompt": question,
            "sql": sql,
            "type": "Line"  # Let backend detect x/y fields later
                    })
                except Exception as e:
                    logging.error(f"[DASHBOARD GRAPH ERROR] Failed for '{question}': {traceback.format_exc()}")
                    return jsonify({
            "prompt": prompt,
            "reply": "Failed to generate SQL for one or more graphs.",
            "error": str(e)
                    })


            dashboard_payload = {
        "title": "Auto Generated Dashboard" if len(questions) == 1 else "Multi-Query Dashboard",
        "graphs": graphs
            }

            try:
                dashboard_res = requests.post("http://localhost:5050/create_dashboard", json=dashboard_payload)
                if dashboard_res.ok:
                    dashboard_url = dashboard_res.json().get("url")
                    return jsonify({
                "prompt": prompt,
                "reply": f"✅ Dashboard created with {len(graphs)} graph(s): [Open Dashboard](http://localhost:5050{dashboard_url})",
                "url": dashboard_url,
                "sql": [g["sql"] for g in graphs]
                    })
                else:
                    logging.error(f"[DASHBOARD ERROR] {dashboard_res.text}")
                    return jsonify({
                "prompt": prompt,
                "reply": "Dashboard creation failed.",
                "error": dashboard_res.text
                    })
            except Exception as e:
                logging.error(f"[DASHBOARD REQUEST FAILED] {traceback.format_exc()}")
                return jsonify({
            "prompt": prompt,
            "reply": "Something went wrong generating the dashboard.",
            "error": str(e)
                })

    except Exception as e:
        print("[ERROR]", str(e))
        logging.error(f"[ERROR] {str(e)}")
        return jsonify({"error": str(e), "sql": sql})


    


# 🧠 Real-world comparison
    if should_compare_real_weather(prompt):
        site_match = re.search(r'\b(PAR1|INZ4|LON3)\b', prompt.upper())
        if site_match:
            site_code = site_match.group(1)
            real_temp = get_real_world_temp(site_code)
            if real_temp is not None:
                print(f"[REAL WEATHER] {site_code}: {real_temp}°C")
                result.append({
                    "source": "Real World",
                    "temperature": round(float(real_temp), 1)
                })


    reply = format_reply(prompt, result)

# Check if it's a PDF
    if isinstance(reply, str) and reply.startswith("[PDF_DATA_READY]"):
        pdf_path = reply.split("]")[1].strip()
        return send_file(pdf_path, as_attachment=True, download_name="report.pdf", mimetype="application/pdf")



    # ✅ Log if result is not empty
    if result and isinstance(result, list) and result[0]:
        log_entry = {
            "user_prompt": prompt,
            "llm_sql": sql,
            "llm_result": result,
            "llm_reply": reply
        }
        try:
            def json_serial(obj):
                if isinstance(obj, (datetime.datetime, datetime.date)):
                    return obj.isoformat()
                raise TypeError(f"Type {type(obj)} not serializable")

            with open("fine_tune_log.json", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False, default=json_serial) + "\n")

        except Exception as e:
            logging.error(f"[LOGGING ERROR] Failed to write to fine_tune_log.json: {str(e)}")

    return jsonify({
        "prompt": prompt,
        "reply": reply,
        "sql": sql,
        "result": result
    })

@app.route('/')
def health():
    return "API is running!", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)


####### ALL FOR DASHBOARD STUFF ######
@app.route("/create_dashboard", methods=["POST"])
def create_dashboard():
    from db import get_cache_connection
    from llm import query_llm  # this must resolve to the working query_llm()
    import traceback

    data = request.json
    dashboard_id = uuid.uuid4().hex[:6]
    full_graphs = []

    for graph in data["graphs"]:
        prompt = graph["prompt"]
        try:
            print(f"[CREATE_DASHBOARD] Prompt: {prompt}")
            sql = query_llm(prompt)
            print(f"[CREATE_DASHBOARD] SQL: {sql}")
            sql = sql.strip().strip("`").rstrip(";")
        except Exception as e:
            print("[CREATE_DASHBOARD ERROR]", traceback.format_exc())
            return jsonify({"error": f"Failed to generate SQL: {str(e)}"}), 500

        full_graphs.append({
            "title": graph["title"],
            "prompt": prompt,
            "sql": sql,
            "xField": graph["xField"],
            "yField": graph["yField"],
            "type": graph.get("type", "Line")
        })

    try:
        db = get_cache_connection()
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO dashboards (id, title, config) VALUES (%s, %s, %s)",
                (dashboard_id, data["title"], json.dumps(full_graphs))
            )
            db.commit()
    except Exception as db_error:
        print("[DB SAVE ERROR]", traceback.format_exc())
        return jsonify({"error": f"DB insert failed: {str(db_error)}"}), 500

    return jsonify({"url": f"http://localhost:5050/dashboard/{dashboard_id}"})


