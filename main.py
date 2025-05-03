from fastapi import FastAPI, HTTPException
import requests
import os
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict
import httpx
import logging
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI API Configuration
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Judge0 API Configuration (Compiler)
JUDGE0_API_URL = "https://judge0-ce.p.rapidapi.com/submissions"
JUDGE0_HEADERS = {
  	"x-rapidapi-key": "301672c4bamsh972d06a1d1de8bap1b473ajsn0dcda6e5ef99",
	"x-rapidapi-host": "judge0-ce.p.rapidapi.com",
	"Content-Type": "application/json"
}

# In-memory storage for ongoing executions
executions: Dict[str, Dict] = {}

class CodeRequest(BaseModel):
    language_id: int
    source_code: Optional[str] = None  # Optional to allow input-only requests
    stdin: Optional[str] = None
    execution_id: Optional[str] = None  
    
class ErrorExplainRequest(BaseModel):
    error_message: str

class TranslateRequest(BaseModel):
    source_code: str
    target_language: str

class DebugRequest(BaseModel):
    source_code: str

class SearchRequest(BaseModel):
    query: str

async def make_openai_request(payload: dict):
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
         async with httpx.AsyncClient(timeout=30.0) as client:  # Increase timeout
            response = await client.post(OPENAI_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logging.error(f"OpenAI API request failed: {e}")
        return {"error": "OpenAI API request failed"}
    except httpx.ReadTimeout as e:
        logging.error("OpenAI API request timed out")
        return {"error": "OpenAI API request timed out"}
    return {"error": "OpenAI API request failed"}
    
# API Endpoints
@app.get("/")
def read_root():
    return {"message": "Compiler API is running"}

@app.post("/run_code/")
async def run_code(request: CodeRequest):
    try:
        if request.execution_id and request.execution_id in executions:
            # Continue previous execution with new input
            execution = executions[request.execution_id]
            source_code = execution["source_code"]
            stdin = execution["stdin"] + "\n" + (request.stdin or "")
        else:
            # New execution
            execution_id = str(uuid.uuid4())
            source_code = request.source_code
            stdin = request.stdin or ""
            executions[execution_id] = {
                "source_code": source_code,
                "stdin": stdin
            }
        
        # Submit code execution request
        submission_response = requests.post(
            f"{JUDGE0_API_URL}?base64_encoded=false&wait=true",
            json={"source_code": source_code, "language_id": request.language_id, "stdin": stdin},
            headers=JUDGE0_HEADERS
        )
        submission_response.raise_for_status()
        result = submission_response.json()

        output = result.get("stdout", "")
        error = result.get("stderr", "")

        # Check if the program is requesting more input
        requires_input = "input" in output.lower() or output.endswith(": ")  # Simple check

        if requires_input:
            execution_id = request.execution_id or str(uuid.uuid4())
            executions[execution_id] = {"source_code": source_code, "stdin": stdin}
        else:
            execution_id = None

        return {
            "output": output,
            "error": error,
            "requires_input": requires_input,
            "execution_id": execution_id
        }
    except requests.exceptions.RequestException as e:
        logging.error(f"Judge0 connection error: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Judge0 connection error: {str(e)}")

@app.post("/explain_error/")
async def explain_error(request: ErrorExplainRequest):
    payload = {
        "model": "gpt-4-turbo",
        "messages": [
            {"role": "system", "content": "Explain this error in simple terms:"},
            {"role": "user", "content": request.error_message}
        ]
    }
    result = await make_openai_request(payload)
    return {"explanation": result["choices"][0]["message"]["content"]}

@app.post("/translate_code/")
async def translate_code(request: TranslateRequest):
    logging.info(f"Received translation request: {request}")
    payload = {
        "model": "gpt-4-turbo",
        "messages": [
            {
                "role": "system",
                "content": f"You are a code translator. Convert the following {request.source_code[:20]}... code from its current language to {request.target_language}. Ensure syntax is correct and no comments or explanations are included in the output."
            },
            {"role": "user", "content": request.source_code}
        ]
    }
    result = await make_openai_request(payload)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    logging.info(f"Translation result: {result}")
    return {"translated_code": result["choices"][0]["message"]["content"]}


@app.post("/debug/")
async def debug_code(request: DebugRequest):
    payload = {
        "model": "gpt-4-turbo",
        "messages": [
            {"role": "system", "content": "You are an AI code optimizer. Fix syntax errors and improve efficiency."},
            {"role": "user", "content": request.source_code}
        ]
    }
    result = await make_openai_request(payload)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return {"optimized_code": result["choices"][0]["message"]["content"]}


@app.post("/chatgpt_search/")
async def chatgpt_search(request: SearchRequest):
    payload = {
        "model": "gpt-4-turbo",
        "messages": [
            {"role": "system", "content": "Provide only valid and executable code in response, without any explanation."},
            {"role": "user", "content": request.query}
        ]
    }
    result = await make_openai_request(payload)

    # Ensure only code is returned
    return {"code": result.get("choices", [{}])[0].get("message", {}).get("content", "Error fetching code")}
