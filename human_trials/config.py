import uuid
import datetime
import subprocess

# Generate unique session ID
SESSION_ID = str(uuid.uuid4())[:8]

# Get experiment date and Git commit hash
DATE = datetime.datetime.now().strftime("%Y-%m-%d")
COMMIT_HASH = (
    subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode("utf-8")
)

# List of available models for tournament style
BIG_LIST_OF_MODELS = [
    "ollama/llama3.2:latest",
]

# Default game configuration
DEFAULT_GAME_ARGS = {
    "game_config": "FIVE_MEMBER_GAME",
    "include_human": True,  # Set to True for human players
    "test": False,
    "personality": False,
    "agent_config": {
        "Impostor": "LLM",
        "Crewmate": "LLM",
        "IMPOSTOR_LLM_CHOICES": ["ollama/llama3.2:latest"],
        "CREWMATE_LLM_CHOICES": ["ollama/llama3.2:latest"],
    },
    "UI": False,
    "Streamlit": False,  # Set to False for command line
    "tournament_style": "random",  # Default tournament style
}

# Configuration dictionary
CONFIG = {
    "session_id": SESSION_ID,
    "date": DATE,
    "commit_hash": COMMIT_HASH,
    "experiment_name": "human_trials",
    "logs_path": "logs",
    "game_args": DEFAULT_GAME_ARGS,
}

