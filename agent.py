import os
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain.agents import Tool, create_react_agent, AgentExecutor
from langchain.memory import ConversationBufferMemory
from langchain.prompts import ChatPromptTemplate
from langchain import hub  # For pre-built prompts
from langchain.tools import tool
from db import run_query  # Reuse your db.py
from utils import get_real_world_temp, load_sla_for_location, check_sla_breaches  # Reuse utils.py
import json
from flask import session  # We'll use Flask session for per-user memory
from langchain_openai import AzureOpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import JSONLoader
import warnings  # For suppressing deprecations

# Suppress deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=PendingDeprecationWarning)

load_dotenv()

# Initialize LLM (reuse your Azure setup)
llm = AzureChatOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
    api_version=os.getenv("AZURE_OPENAI_VERSION"),
    temperature=0.0,
    max_tokens=1024
)

# Load and index examples
loader = JSONLoader("prompts/examples.json", jq_schema=".", text_content=False)
docs = loader.load()
embeddings = AzureOpenAIEmbeddings(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    openai_api_version=os.getenv("AZURE_EMBEDDING_VERSION"),
    azure_deployment=os.getenv("AZURE_EMBEDDING_DEPLOYMENT")
)
vectorstore = FAISS.from_documents(docs, embeddings)

@tool
def retrieve_examples(query: str, k: int = 3):
    """Retrieve relevant SQL examples for a prompt."""
    results = vectorstore.similarity_search(query, k=k)
    return json.dumps([doc.page_content for doc in results])

@tool
def execute_sql(sql: str):
    """Execute T-SQL on the telemetry database and return results as JSON."""
    try:
        results = run_query(sql)
        return json.dumps(results)  # Agent expects string output
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def fetch_real_weather(site_code: str):
    """Fetch real-world temperature for a site code (e.g., 'PAR1')."""
    temp = get_real_world_temp(site_code.upper())
    return json.dumps({"temperature": temp}) if temp else "No data available."

@tool
def check_sla(site: str, building: str, datahall: str, data_json: str):
    """Check for SLA breaches given site, building, datahall, and query results (JSON)."""
    sla = load_sla_for_location(site, building, datahall)
    if not sla:
        return "No SLA found."
    data = json.loads(data_json)
    breaches = check_sla_breaches(data, sla)
    return json.dumps(breaches)

@tool
def get_db_schema(table: str = "ctpdashboard"):
    """Get schema (columns) for a table like 'ctpdashboard', 'ctp_lookup', or 'TemperatureReading_4h'."""
    if table == "ctpdashboard":
        return "Columns: Site, Building, DH, [Point Name], Global_Asset_ID, gateway_timestamp, readvalue (for live data)"
    elif table == "ctp_lookup":
        return "Columns: Global_Asset_ID, Point_Name, Customer_OCN, Site, Building"
    elif table == "TemperatureReading_4h":
        return "Columns: Primary_Key, TimeStamp, Temperature (for historical data)"
    return "Unknown table."

tools = [execute_sql, fetch_real_weather, check_sla, get_db_schema]
tools.append(retrieve_examples)  # Add to tools list

# Pull a base prompt from LangChain Hub or customize
prompt = hub.pull("hwchase17/react-chat")  # Pre-built ReAct prompt; customize if needed

# Custom prompt (better for your domain)
custom_prompt = ChatPromptTemplate.from_template("""
You are a telemetry AI assistant for data centers. For live data (current/latest), use [dbo].[ctpdashboard] table and 'gateway_timestamp' column. For historical (past dates, trends), use [dbo].[TemperatureReading_4h] table and 'TimeStamp' column.

Tools: {tools}
Tool names: {tool_names}

Use this format:
Thought: [Reasoning]
Action: [Tool name]
Action Input: [Params]
Observation: [Tool output]
Final Answer: [final response]

{agent_scratchpad}

Steps:
1. Determine if live (use ctpdashboard, gateway_timestamp) or historical (TemperatureReading_4h, TimeStamp).
2. Extract site/building/datahall/metric.
3. Generate SQL directly if possible; use schema tool only if unsure.
4. Post-process (SLA/weather).
5. Respond naturally.

Chat History: {history}
User: {input}
""")

# Create agent
agent = create_react_agent(llm, tools, custom_prompt)  # Use custom_prompt for domain-specific

def get_memory(session_id: str):
    """Get or create memory for a session."""
    if 'memory' not in session:
        session['memory'] = {}
    if session_id not in session['memory']:
        session['memory'][session_id] = ConversationBufferMemory(memory_key="history", return_messages=True)
    return session['memory'][session_id]

# Wrap agent with history
def get_agent_executor(session_id: str):
    memory = get_memory(session_id)
    agent_executor = AgentExecutor(
        agent=agent, 
        tools=tools, 
        memory=memory, 
        verbose=True
    )
    return agent_executor