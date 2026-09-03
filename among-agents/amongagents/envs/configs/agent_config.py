OLLAMA_MODEL = "ollama/llama3.2:latest"

IMPOSTOR_LLM = {
    "Impostor": "LLM",
    "Crewmate": "Random",
    "IMPOSTOR_LLM_CHOICES": [OLLAMA_MODEL],
}

CREWMATE_LLM = {
    "Impostor": "Random",
    "Crewmate": "LLM",
    "CREWMATE_LLM_CHOICES": [OLLAMA_MODEL],
}

ALL_RANDOM = {"Impostor": "Random", "Crewmate": "Random"}

ALL_LLM = {
    "Impostor": "LLM",
    "Crewmate": "LLM",
    "CREWMATE_LLM_CHOICES": [OLLAMA_MODEL],
    "IMPOSTOR_LLM_CHOICES": [OLLAMA_MODEL],
    }