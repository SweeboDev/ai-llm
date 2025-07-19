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
from dotenv import load_dotenv

from agent import get_agent_executor
from flask_session import Session

load_dotenv()

app = Flask(__name__)
CORS(app)

app.config['SESSION_TYPE'] = 'filesystem'  # Or 'redis' for production
Session(app)

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

@app.route('/ask', methods=['POST'])
def ask():
    print("[DEBUG] Received request to /ask")  # Log entry
    data = request.json
    prompt = data.get("prompt")
    print(f"[DEBUG] Prompt received: {prompt}")  # Log prompt
    session_id = data.get("session_id", "default")
    print(f"[DEBUG] Session ID: {session_id}")

    try:
        executor = get_agent_executor(session_id)
        print("[DEBUG] Agent executor initialized")
        response = executor.invoke({"input": prompt})
        print(f"[DEBUG] Agent raw response: {response}")  # Log full agent output
        reply = response['output']

        # Reuse your formatting if needed
        if "table" in prompt.lower():
            reply = format_reply(prompt, json.loads(reply))

        print("[DEBUG] Sending reply")
        return jsonify({
            "prompt": prompt,
            "reply": reply,
        })
    except Exception as e:
        print(f"[ERROR in /ask] {str(e)}")  # Log any errors
        return jsonify({"error": str(e)})

@app.route('/')
def health():
    return "API is running!", 200



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)