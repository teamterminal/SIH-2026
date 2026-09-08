import os

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
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


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not configured.")

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.7-flash"
)


STUDY_MATERIAL_PROMPT = """
You are an expert educational content generator.

Analyze the supplied PDF and convert it into a concise study guide.

STRICT RULES:

1. Use ONLY information contained in the supplied PDF.
2. Do not add outside knowledge.
3. Do not invent facts.
4. Preserve important terminology from the document.
5. Create concise but useful revision notes.
6. Organize notes by topic.
7. Create a meaningful hierarchical mind map.
8. Create flowcharts ONLY when the document contains a
   meaningful process, sequence, workflow, procedure,
   algorithm, or step-by-step process.
9. If there is no meaningful process, return an empty
   flowcharts array.
10. Remove unnecessary repetition.
11. Make the output useful for exam revision.
12. Return structured JSON matching the provided schema.
"""


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
        pdf_part = types.Part.from_bytes(
            data=file_bytes,
            mime_type="application/pdf"
        )

        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                STUDY_MATERIAL_PROMPT,
                pdf_part
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=StudyMaterialOutput,
                temperature=0.3
            )
        )

        if not response.text:
            raise HTTPException(
                status_code=502,
                detail="Gemini returned an empty response."
            )

        return StudyMaterialOutput.model_validate_json(
            response.text
        )

    except HTTPException:
        raise

    except Exception as e:
        print(f"Gemini study material error: {e}")

        raise HTTPException(
            status_code=502,
            detail=f"Gemini API error: {str(e)}"
        )
