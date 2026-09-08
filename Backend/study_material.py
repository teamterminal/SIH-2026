import io

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from pypdf import PdfReader

from shared import call_llm_for_json


router = APIRouter()


# ============================================================
# Response schemas
# ============================================================

class NoteSection(BaseModel):
    topic: str
    points: list[str]


class MindMapNode(BaseModel):
    label: str
    children: list["MindMapNode"] = []


class MindMap(BaseModel):
    root: str
    children: list[MindMapNode]


class Flowchart(BaseModel):
    title: str
    steps: list[str]


class StudyMaterialOutput(BaseModel):
    title: str
    summary: str
    notes: list[NoteSection]
    mind_map: MindMap
    flowcharts: list[Flowchart]


# ============================================================
# PDF extraction
# ============================================================

def extract_pdf_text(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))

        pages = []

        for page in reader.pages:
            text = page.extract_text() or ""

            if text.strip():
                pages.append(text)

        full_text = "\n\n".join(pages).strip()

        if not full_text:
            raise HTTPException(
                status_code=400,
                detail="Could not extract readable text from this PDF."
            )

        return full_text

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read PDF: {str(e)}"
        )


# ============================================================
# Prompt
# ============================================================

def build_study_material_prompt(text: str) -> tuple[str, str]:

    system_prompt = """
You are an expert educational content generator.

Your job is to convert study material into concise,
high-quality learning resources.

STRICT RULES:

1. Use ONLY information contained in the supplied material.
2. Do not invent facts.
3. Do not add outside knowledge.
4. Keep notes short and useful for revision.
5. Preserve important terminology.
6. Organize related concepts together.
7. Create a meaningful hierarchical mind map.
8. Create flowcharts ONLY when the material contains
   a meaningful process, sequence, workflow, or procedure.
9. If there is no meaningful process, return an empty
   flowcharts array.
10. Return ONLY valid JSON.
"""


    user_prompt = f"""
Analyze the following study material.

Create:

1. A short title.
2. A concise summary.
3. Short revision notes organized by topic.
4. A hierarchical mind map.
5. Flowcharts for important processes, if present.

Return EXACTLY this JSON structure:

{{
  "title": "Short title",

  "summary": "A concise overview of the material",

  "notes": [
    {{
      "topic": "Topic name",
      "points": [
        "Important point",
        "Important point"
      ]
    }}
  ],

  "mind_map": {{
    "root": "Main topic",
    "children": [
      {{
        "label": "Major concept",
        "children": [
          {{
            "label": "Sub concept",
            "children": []
          }}
        ]
      }}
    ]
  }},

  "flowcharts": [
    {{
      "title": "Process name",
      "steps": [
        "Step 1",
        "Step 2",
        "Step 3"
      ]
    }}
  ]
}}

If no meaningful flowchart exists, use:

"flowcharts": []

STUDY MATERIAL:

{text}
""".strip()

    return system_prompt, user_prompt


# ============================================================
# Endpoint
# ============================================================

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

    text = extract_pdf_text(file_bytes)

    # Keep the first version simple.
    # We will add intelligent chunking later for large PDFs.
    text = text[:50000]

    system_prompt, user_prompt = build_study_material_prompt(text)

    result = call_llm_for_json(
        system_prompt,
        user_prompt,
        StudyMaterialOutput
    )

    return result