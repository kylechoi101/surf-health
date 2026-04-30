import os
import itertools
from typing import TypedDict, Annotated, List, Literal
import operator
from dotenv import load_dotenv

from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage, AnyMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

# Load .env to get the 3 NVIDIA API keys
load_dotenv(os.path.join(os.path.dirname(__file__), '../backend/.env'))

# ---------------------------------------------------------
# 1. API Key Rotation Setup (The "Brain")
# ---------------------------------------------------------
keys_env = os.environ.get("NVIDIA_API_KEYS", "")
nim_keys = [k.strip() for k in keys_env.split(",") if k.strip()]

if not nim_keys:
    # Fallback to single key for testing if NVIDIA_API_KEYS not set
    single_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if single_key:
        nim_keys = [single_key]
    else:
        print("WARNING: No NVIDIA API keys found. Please set NVIDIA_API_KEYS or NVIDIA_API_KEY in backend/.env")
        nim_keys = ["mock-key-1", "mock-key-2"] # allow script to start even if it will fail on API call

key_iterator = itertools.cycle(nim_keys)

# ---------------------------------------------------------
# 2. Define the State
# ---------------------------------------------------------
class WorkerState(TypedDict):
    messages: Annotated[List[AnyMessage], operator.add]
    current_plan: str

# ---------------------------------------------------------
# 3. Define the Tools
# ---------------------------------------------------------
@tool
def execute_bash(cmd: str) -> str:
    """Run a shell command in the repository."""
    print(f"[TOOL EXECUTOR] Running bash: {cmd}")
    import subprocess
    try:
        # Use a very short timeout and restrict commands for this test script
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return result.stdout + result.stderr
    except Exception as e:
        return f"Error executing bash: {e}"

@tool
def read_file(path: str) -> str:
    """Read a file from the repository."""
    print(f"[TOOL EXECUTOR] Reading file: {path}")
    try:
        with open(path, 'r') as f:
            return f.read()[:500] + "... (truncated)" # return only first 500 chars
    except Exception as e:
        return f"Error reading file: {e}"

tools = [execute_bash, read_file]

# ---------------------------------------------------------
# 4. Initialize the Executor Model
# ---------------------------------------------------------
# Use gemma4:31b which natively supports tool calling!
executor_model = ChatOllama(
    model="gemma4:31b", 
    temperature=0, 
    base_url="http://localhost:11434"
).bind_tools(tools)

# ---------------------------------------------------------
# 5. Define the Nodes
# ---------------------------------------------------------
def planner_node(state: WorkerState):
    """NIM (Llama 3 70B) evaluates the state and sets the next plan."""
    current_key = next(key_iterator)
    # Mask key for printing
    masked_key = f"{current_key[:4]}...{current_key[-4:]}" if len(current_key) > 8 else "mock-key"
    print(f"--- NIM BRAIN (PLANNER) using key {masked_key} ---")
    
    planner_model = ChatNVIDIA(
        model="meta/llama-3.3-70b-instruct",
        api_key=current_key,
        temperature=0.1,
    )
    
    sys_msg = SystemMessage(content=(
        "You are the BRAIN orchestrator. Review the messages "
        "and output a concise, 1-2 step plan for the local executor to follow. "
        "Do not execute tools yourself. You must rely on the executor. "
        "If the main goal requested by the user is achieved and verified, reply exactly with the word 'DONE' and nothing else."
    ))
    
    response = planner_model.invoke([sys_msg] + state["messages"])
    print(f"[PLAN OUT] {response.content}")
    return {"current_plan": response.content}

def executor_node(state: WorkerState):
    """Ollama (gemma4:31b) acts on the plan using tools."""
    print(f"--- OLLAMA EXECUTOR (gemma4:31b) ---")
    sys_msg = SystemMessage(content=(
        f"You are the EXECUTOR. Strictly follow this plan using your tools: \n{state['current_plan']}\n"
        "If you encounter an error, report it. When finished with the plan steps, summarize what you did."
    ))
    
    response = executor_model.invoke([sys_msg] + state["messages"])
    return {"messages": [response]}

tool_executor = ToolNode(tools)

# ---------------------------------------------------------
# 6. Define Routing Logic
# ---------------------------------------------------------
def should_continue(state: WorkerState) -> Literal["tools", "planner", "__end__"]:
    last_message = state["messages"][-1]
    
    if last_message.tool_calls:
        print(f"[ROUTER] Routing to 'tools' (Tools requested: {[tc['name'] for tc in last_message.tool_calls]})")
        return "tools"
    
    if state.get("current_plan", "").strip() == "DONE" or "DONE" in state.get("current_plan", ""):
        print("[ROUTER] Plan is DONE, ending execution.")
        return "__end__"
        
    print("[ROUTER] Routing back to 'planner' for next step.")
    return "planner"

# ---------------------------------------------------------
# 7. Build and Run the Graph
# ---------------------------------------------------------
workflow = StateGraph(WorkerState)

workflow.add_node("planner", planner_node)
workflow.add_node("executor", executor_node)
workflow.add_node("tools", tool_executor)

workflow.add_edge(START, "planner")
workflow.add_edge("planner", "executor")

workflow.add_conditional_edges(
    "executor",
    should_continue,
    {
        "tools": "tools",
        "planner": "planner",
        "__end__": END
    }
)

workflow.add_edge("tools", "executor")

app = workflow.compile()

if __name__ == "__main__":
    print("Starting Hybrid LangGraph Test...")
    initial_state = {
        "messages": [HumanMessage(content="Use the bash tool to check what version of python is installed, then read the README.md file in the current directory.")],
        "current_plan": ""
    }
    
    try:
        for event in app.stream(initial_state, {"recursion_limit": 20}):
            # Just iterating through the stream to drive the execution
            pass
        print("Execution complete.")
    except Exception as e:
        print(f"Execution failed: {e}")
