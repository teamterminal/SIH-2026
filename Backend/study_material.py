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
    title: str = ""
    summary: str = ""
    notes: list[NoteSection] = Field(default_factory=list)
    mind_map: MindMap = Field(
        default_factory=lambda: MindMap(root="")
    )
    flowcharts: list[Flowchart] = Field(default_factory=list)


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
Create a compact exam-revision study guide from the document below.

SOURCE RULE:
Use ONLY information present in the document.
Do not add outside facts or knowledge.

IMPORTANT:
The notes must EXPLAIN concepts.
Do not simply list topic names.

NOTES:
- Select the 6-8 most important topics.
- Each topic must have exactly 2-3 short explanatory points.
- Each point should normally be one sentence.
- Keep each point under approximately 20 words.
- Include definitions, key concepts, classifications, formulas,
  rules, examples, and relationships when present in the document.
- Never use a topic name alone as a point.

SUMMARY:
Write 2-4 short sentences summarizing the most important ideas.

MIND MAP:
Create a simple hierarchical mind map.
Use the main subject as the root.
Use important topics as children.
Use smaller concepts as grandchildren when useful.

FLOWCHARTS:
Only create a flowchart if the document contains a real process,
procedure, sequence, workflow, or algorithm.
Otherwise return an empty array.

OUTPUT:
Return ONLY one valid JSON object.
Do not use markdown.
Do not use ``` blocks.
Do not add explanations before or after the JSON.

The JSON object MUST have EXACTLY these top-level keys:

"title"
"summary"
"notes"
"mind_map"
"flowcharts"

The structure MUST be:

{
  "title": "short title",
  "summary": "2-4 sentence summary",
  "notes": [
    {
      "topic": "topic name",
      "points": [
        "short explanatory point",
        "short explanatory point"
      ]
    }
  ],
  "mind_map": {
    "root": "main subject",
    "children": [
      {
        "label": "important topic",
        "children": [
          {
            "label": "important sub-concept",
            "children": []
          }
        ]
      }
    ]
  },
  "flowcharts": []
}

IMPORTANT:
Always include ALL FIVE top-level keys.
Even when there are no flowcharts, output:
"flowcharts": []
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

        MAX_INPUT_CHARS = 10000

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
            "role": "user",
            "content": user_prompt
        }
    ],
    temperature=0.2,
    max_completion_tokens=1500,
    reasoning_effort="low",
    include_reasoning=False,
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "study_material",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string"
                    },
                    "summary": {
                        "type": "string"
                    },
                    "notes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "topic": {
                                    "type": "string"
                                },
                                "points": {
                                    "type": "array",
                                    "items": {
                                        "type": "string"
                                    }
                                }
                            },
                            "required": [
                                "topic",
                                "points"
                            ],
                            "additionalProperties": False
                        }
                    },
                    "mind_map": {
                        "type": "object",
                        "properties": {
                            "root": {
                                "type": "string"
                            },
                            "children": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {
                                            "type": "string"
                                        },
                                        "children": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "label": {
                                                        "type": "string"
                                                    },
                                                    "children": {
                                                        "type": "array",
                                                        "items": {}
                                                    }
                                                },
                                                "required": [
                                                    "label",
                                                    "children"
                                                ],
                                                "additionalProperties": False
                                            }
                                        }
                                    },
                                    "required": [
                                        "label",
                                        "children"
                                    ],
                                    "additionalProperties": False
                                }
                            }
                        },
                        "required": [
                            "root",
                            "children"
                        ],
                        "additionalProperties": False
                    },
                    "flowcharts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string"
                                },
                                "steps": {
                                    "type": "array",
                                    "items": {
                                        "type": "string"
                                    }
                                }
                            },
                            "required": [
                                "title",
                                "steps"
                            ],
                            "additionalProperties": False
                        }
                    }
                },
                "required": [
                    "title",
                    "summary",
                    "notes",
                    "mind_map",
                    "flowcharts"
                ],
                "additionalProperties": False
            }
        }
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
