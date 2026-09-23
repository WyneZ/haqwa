from ast import pattern
import os
from pathlib import Path

from google import genai
from pydantic import BaseModel  

# Load .env without extra dependency
for line in Path(".env").read_text().splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


class ParseRule(BaseModel):
    pattern: str
    event: str
    per: str


client = genai.Client() # read Gemini_api_key
response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents="Rule: A customer must not be charged twice for the same order.",
    config={"response_mime_type": "application/json", "response_schema": ParseRule},
)

print(response.text)
print(response.parsed)


