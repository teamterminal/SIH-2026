import os
import json
import io

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from pypdf import PdfReader
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()


# =========================================================
# OUTPUT SCHEMAS
# =========================================================

class NoteSection(BaseModel):
    topic: str
    points: list[str]


class MindMapNode(BaseModel):
    label: str
    children: list["MindMapNode"] = Field(default_factory=list)


class MindMap(BaseModel):
    root: str
    children: list[MindMapNode] = Field(default_factory=list)


class Flowchart(BaseModel):
    title: str
    steps: list[str]


class StudyMaterialOutput(BaseModel):
    title: str
    summary: str
    notes: list[NoteSection]
    mind_map: MindMap
    flowcharts: list[Flowchart]


# =========================================================
# GROQ
# =========================================================

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is not configured.")

groq_client = Groq(api_key=GROQ_API_KEY)

GROQ_MODEL = os.environ.get(
    "GROQ_MODEL",
    "openai/gpt-oss-20b"
)


# =========================================================
# PROMPT
# =========================================================

STUDY_MATERIAL_PROMPT = """
You are an expert educational content generator.

Analyze the supplied study material and create a concise exam-revision
study guide.

STRICT RULES:

1. Use ONLY information contained in the supplied document.
2. Do not add outside knowledge.
3. Do not invent facts.
4. Preserve important terminology from the document.
5. Create concise but useful revision notes.
6. Organize notes by topic.
7. Create a meaningful hierarchical mind map.
8. Create flowcharts ONLY when the document contains a meaningful
   process, sequence, workflow, procedure, algorithm, or step-by-step
   process.
9. If there is no meaningful process, return an empty flowcharts array.
10. Remove unnecessary repetition.
11. Keep the output compact.
12. Return ONLY valid JSON.
13. Do not use markdown.
14. Do not put JSON inside ``` blocks.

Required JSON structure:

{
  "title": "string",
  "summary": "string",
  "notes": [
    {
      "topic": "string",
      "points": ["string"]
    }
  ],
  "mind_map": {
    "root": "string",
    "children": [
      {
        "label": "string",
        "children": []
      }
    ]
  },
  "flowcharts": [
    {
      "title": "string",
      "steps": ["string"]
    }
  ]
}
"""


# =========================================================
# PDF EXTRACTION
# =========================================================

def extract_pdf_text(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))

        pages = []

        for page in reader.pages:
            page_text = page.extract_text() or ""

            if page_text.strip():
                pages.append(page_text)

        return "\n\n".join(pages)

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read PDF: {str(e)}"
        )


# =========================================================
# STUDY MATERIAL GENERATION
# =========================================================

@router.post(
    "/generate-study-material",
    response_model=StudyMaterialOutput
)
async def generate_study_material(
    file: UploadFile = File(...)
):
    # -----------------------------------------------------
    # Validate file
    # -----------------------------------------------------

    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported."
        )

    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="The uploaded PDF is empty."
        )

    try:
        # -------------------------------------------------
        # Extract PDF text
        # -------------------------------------------------

        text = extract_pdf_text(file_bytes)

        if not text.strip():
            raise HTTPException(
                status_code=400,
                detail="No readable text was found in the PDF."
            )

        # -------------------------------------------------
        # IMPORTANT:
        # Keep the input small enough for the free Groq
        # token-per-minute limit.
        #
        # ~20,000 characters is roughly 5K input tokens.
        # With a compact prompt + ~1.5K output tokens,
        # the request stays comfortably below 8K TPM.
        # -------------------------------------------------

        MAX_INPUT_CHARS = 20000

        if len(text) > MAX_INPUT_CHARS:
            text = text[:MAX_INPUT_CHARS]

        # -------------------------------------------------
        # Build prompt
        # -------------------------------------------------

        user_prompt = f"""
{STUDY_MATERIAL_PROMPT}

Here is the study material:

--- START DOCUMENT ---

{text}

--- END DOCUMENT ---
"""

        # -------------------------------------------------
        # Groq request
        # -------------------------------------------------

        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You generate compact educational study "
                        "materials and return valid JSON only."
                    )
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            temperature=0.2,
            max_completion_tokens=1500,
            response_format={
                "type": "json_object"
            }
        )

        # -------------------------------------------------
        # Extract response
        # -------------------------------------------------

        result = response.choices[0].message.content

        if not result:
            raise HTTPException(
                status_code=502,
                detail="Groq returned an empty response."
            )

        # -------------------------------------------------
        # Parse JSON
        # -------------------------------------------------

        try:
            parsed = json.loads(result)

        except json.JSONDecodeError as e:
            print("Groq returned invalid JSON:")
            print(result)

            raise HTTPException(
                status_code=502,
                detail=f"Groq returned invalid JSON: {str(e)}"
            )

        # -------------------------------------------------
        # Validate against schema
        # -------------------------------------------------

        return StudyMaterialOutput.model_validate(parsed)

    except HTTPException:
        raise

    except Exception as e:
        print(f"Groq study material error: {e}")

        error_text = str(e)

        # Friendly rate-limit message
        if "429" in error_text or "rate limit" in error_text.lower():
            raise HTTPException(
                status_code=429,
                detail=(
                    "Groq rate limit reached. "
                    "Please wait a short while and try again."
                )
            )

        raise HTTPException(
            status_code=502,
            detail=f"Groq API error: {error_text}"
        )
