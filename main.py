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

app.add\_middleware(
CORSMiddleware,
allow\_origins=\["*"],
allow\_credentials=True,
allow\_methods=\["*"],
allow\_headers=\["\*"],
)

# OpenAI API Configuration

OPENAI\_API\_URL = "[https://api.openai.com/v1/chat/completions](https://api.openai.com/v1/chat/completions)"
OPENAI\_API\_KEY = os.getenv("OPENAI\_API\_KEY")

# Judge0 API Configuration (Compiler)

JUDGE0\_API\_URL = "[https://judge0-ce.p.rapidapi.com/submissions](https://judge0-ce.p.rapidapi.com/submissions)"
JUDGE0\_HEADERS = {
"x-rapidapi-key": "301672c4bamsh972d06a1d1de8bap1b473ajsn0dcda6e5ef99",
"x-rapidapi-host": "judge0-ce.p.rapidapi.com",
"Content-Type": "application/json"
}

# In-memory storage for ongoing executions

executions: Dict\[str, Dict] = {}

class CodeRequest(BaseModel):
language\_id: int
source\_code: Optional\[str] = None  # Optional to allow input-only requests
stdin: Optional\[str] = None
execution\_id: Optional\[str] = None

class ErrorExplainRequest(BaseModel):
error\_message: str

class TranslateRequest(BaseModel):
source\_code: str
target\_language: str

class DebugRequest(BaseModel):
source\_code: str

class SearchRequest(BaseModel):
query: str

async def make\_openai\_request(payload: dict):
headers = {
"Authorization": f"Bearer {OPENAI\_API\_KEY}",
"Content-Type": "application/json"
}
try:
async with httpx.AsyncClient(timeout=30.0) as client:  # Increase timeout
response = await client.post(OPENAI\_API\_URL, json=payload, headers=headers)
response.raise\_for\_status()
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
def read\_root():
return {"message": "Compiler API is running"}

@app.post("/run\_code/")
async def run\_code(request: CodeRequest):
try:
if request.execution\_id and request.execution\_id in executions:
\# Continue previous execution with new input
execution = executions\[request.execution\_id]
source\_code = execution\["source\_code"]
stdin = execution\["stdin"] + "\n" + (request.stdin or "")
else:
\# New execution
execution\_id = str(uuid.uuid4())
source\_code = request.source\_code
stdin = request.stdin or ""
executions\[execution\_id] = {
"source\_code": source\_code,
"stdin": stdin
}

```
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
```

@app.post("/explain\_error/")
async def explain\_error(request: ErrorExplainRequest):
payload = {
"model": "gpt-4-turbo",
"messages": \[
{"role": "system", "content": "Explain this error in simple terms:"},
{"role": "user", "content": request.error\_message}
]
}
result = await make\_openai\_request(payload)
return {"explanation": result\["choices"]\[0]\["message"]\["content"]}

@app.post("/translate\_code/")
async def translate\_code(request: TranslateRequest):
logging.info(f"Received translation request: {request}")
payload = {
"model": "gpt-4-turbo",
"messages": \[
{
"role": "system",
"content": f"You are a code translator. Convert the following {request.source\_code\[:20]}... code from its current language to {request.target\_language}. Ensure syntax is correct and no comments or explanations are included in the output."
},
{"role": "user", "content": request.source\_code}
]
}
result = await make\_openai\_request(payload)

```
if "error" in result:
    raise HTTPException(status_code=500, detail=result["error"])

logging.info(f"Translation result: {result}")
return {"translated_code": result["choices"][0]["message"]["content"]}
```

@app.post("/debug/")
async def debug\_code(request: DebugRequest):
payload = {
"model": "gpt-4-turbo",
"messages": \[
{"role": "system", "content": "You are an AI code optimizer. Fix syntax errors and improve efficiency."},
{"role": "user", "content": request.source\_code}
]
}
result = await make\_openai\_request(payload)

```
if "error" in result:
    raise HTTPException(status_code=500, detail=result["error"])

return {"optimized_code": result["choices"][0]["message"]["content"]}
```

@app.post("/chatgpt\_search/")
async def chatgpt\_search(request: SearchRequest):
payload = {
"model": "gpt-4-turbo",
"messages": \[
{"role": "system", "content": "Provide only valid and executable code in response, without any explanation."},
{"role": "user", "content": request.query}
]
}
result = await make\_openai\_request(payload)

return {"code": result.get("choices", [{}])[0].get("message", {}).get("content", "Error fetching code")}
