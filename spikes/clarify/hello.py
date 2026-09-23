from typing import Literal
import logging
import os
from pathlib import Path

from google import genai
from pydantic import BaseModel

logging.getLogger("google_genai.models").setLevel(logging.ERROR)

# Load .env without extra dependency
for line in Path(".env").read_text().splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


class ParseRule(BaseModel):
    pattern: Literal["at_most_once", "never_after", "must_precede", "within_time"] | None = None
    event: str
    per: str
    supported: bool
    unsupported_reason: str | None


client = genai.Client() # read Gemini_api_key
response = client.models.generate_content(
    model="gemini-3.6-flash",
    # contents="Rule: A customer must not be charged twice for the same order.",
    contents="Rule: Every order must have an invoice.",
    config={"response_mime_type": "application/json", "response_schema": ParseRule},
)

print(response.text)
print(response.parsed)


