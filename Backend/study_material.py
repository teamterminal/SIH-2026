import os

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from pypdf import PdfReader
from mistralai.client import Mistral
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()


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


MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")

if not MISTRAL_API_KEY:
    raise RuntimeError("MISTRAL_API_KEY is not configured.")

mistral_client = Mistral(api_key=MISTRAL_API_KEY)

MISTRAL_MODEL = os.environ.get(
    "MISTRAL_MODEL",
    "mistral-small-latest"
)


STUDY_MATERIAL_PROMPT = """
You are an expert educational content generator.

Analyze the supplied study material and convert it into a concise
but useful study guide.

STRICT RULES:

1. Use ONLY information contained in the supplied document.
2. Do not add outside knowledge.
3. Do not invent facts.
4. Preserve important terminology from the document.
5. Create concise but useful revision notes.
6. Organize notes by topic.
7. Create a meaningful hierarchical mind map.
8. Create flowcharts ONLY when the document contains a meaningful
   process, sequence, workflow, procedure, algorithm, or
   step-by-step process.
9. If there is no meaningful process, return an empty flowcharts array.
10. Remove unnecessary repetition.
11. Make the output useful for exam revision.
12. Return ONLY valid JSON matching the requested structure.

The required JSON structure is:

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


def extract_pdf_text(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(file_bytes)
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


@router.post(
    "/generate-study-material",
    response_model=StudyMaterialOutput
)
async def generate_study_material(
    file: UploadFile = File(...)
):
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
        text = extract_pdf_text(file_bytes)

        if not text.strip():
            raise HTTPException(
                status_code=400,
                detail="No readable text was found in the PDF."
            )

        # Keep the same practical limit used by the previous version.
        text = text[:50000]

        user_prompt = f"""
{STUDY_MATERIAL_PROMPT}

Here is the PDF content:

--- START PDF CONTENT ---

{text}

--- END PDF CONTENT ---
"""

        response = mistral_client.chat.complete(
            model=MISTRAL_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            response_format={
                "type": "json_object"
            },
            temperature=0.3
        )

        result = response.choices[0].message.content

        if not result:
            raise HTTPException(
                status_code=502,
                detail="Mistral returned an empty response."
            )

        return StudyMaterialOutput.model_validate_json(result)

    except HTTPException:
        raise

    except Exception as e:
        print(f"Mistral study material error: {e}")

        raise HTTPException(
            status_code=502,
            detail=f"Mistral API error: {str(e)}"
        )
