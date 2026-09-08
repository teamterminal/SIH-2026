import io
import time

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from pypdf import PdfReader

from shared import call_llm_for_json


router = APIRouter()


# ============================================================
# OUTPUT MODELS
# ============================================================

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


# ============================================================
# CHUNK-LEVEL OUTPUT
# ============================================================

class ChunkOutput(BaseModel):
    title: str
    summary: str
    notes: list[NoteSection]
    concepts: list[str]
    processes: list[Flowchart]


# ============================================================
# PDF TEXT EXTRACTION
# ============================================================

def extract_pdf_text(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))

        pages = []

        for page in reader.pages:
            text = page.extract_text() or ""

            if text.strip():
                pages.append(text.strip())

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
# TEXT CHUNKING
# ============================================================

CHUNK_SIZE = 4500
CHUNK_OVERLAP = 300


def split_text_into_chunks(text: str) -> list[str]:
    chunks = []

    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + CHUNK_SIZE, text_length)

        # Try to end at a paragraph/newline instead of
        # cutting a sentence in the middle.
        if end < text_length:
            newline_pos = text.rfind("\n", start, end)

            if newline_pos > start + 2500:
                end = newline_pos

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= text_length:
            break

        start = max(end - CHUNK_OVERLAP, start + 1)

    return chunks


# ============================================================
# CHUNK PROMPT
# ============================================================

def build_chunk_prompt(chunk: str, chunk_number: int, total_chunks: int):
    system_prompt = """
You are an expert educational content generator.

Analyze ONLY the supplied study-material excerpt.

Rules:
1. Use only information present in the excerpt.
2. Do not add outside knowledge.
3. Extract the most important concepts.
4. Create concise revision notes.
5. Preserve important terminology.
6. Identify meaningful processes or procedures.
7. Do not invent a process if none exists.
8. Keep the response concise.
9. Return ONLY valid JSON.
""".strip()

    user_prompt = f"""
This is excerpt {chunk_number} of {total_chunks} from a larger study document.

Extract useful learning information from this excerpt.

Return EXACTLY this JSON:

{{
  "title": "Main topic of this excerpt",
  "summary": "Very concise summary",
  "notes": [
    {{
      "topic": "Topic",
      "points": [
        "Important point",
        "Important point"
      ]
    }}
  ],
  "concepts": [
    "Important concept",
    "Important concept"
  ],
  "processes": [
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

If there is no meaningful process, return:

"processes": []

EXCERPT:

{chunk}
""".strip()

    return system_prompt, user_prompt


# ============================================================
# FINAL SYNTHESIS PROMPT
# ============================================================

def build_final_prompt(chunk_results: list[ChunkOutput]):
    condensed_parts = []

    for index, result in enumerate(chunk_results, start=1):
        notes_text = "\n".join(
            f"- {note.topic}: " + "; ".join(note.points)
            for note in result.notes
        )

        concepts_text = ", ".join(result.concepts)

        processes_text = "\n".join(
            f"{process.title}: " + " → ".join(process.steps)
            for process in result.processes
        )

        condensed_parts.append(
            f"""
EXCERPT SUMMARY {index}

Title:
{result.title}

Summary:
{result.summary}

Notes:
{notes_text}

Concepts:
{concepts_text}

Processes:
{processes_text}
""".strip()
        )

    combined = "\n\n".join(condensed_parts)

    system_prompt = """
You are an expert educational content generator.

Create a final study guide from the supplied excerpt summaries.

STRICT RULES:
1. Use ONLY information contained in the supplied summaries.
2. Do not introduce outside facts.
3. Remove duplicate information.
4. Merge related topics.
5. Keep revision notes concise.
6. Preserve important terminology.
7. Create a clear hierarchical mind map.
8. Create flowcharts ONLY for meaningful processes or procedures.
9. Do not invent processes.
10. The final result should be useful for exam revision.
11. Return ONLY valid JSON.
""".strip()

    user_prompt = f"""
Combine the following excerpt summaries into ONE coherent study guide.

Return EXACTLY this JSON:

{{
  "title": "Short title",
  "summary": "Concise overview of the entire material",

  "notes": [
    {{
      "topic": "Topic",
      "points": [
        "Important revision point",
        "Important revision point"
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

If the material contains no meaningful process, use:

"flowcharts": []

EXCERPT SUMMARIES:

{combined}
""".strip()

    return system_prompt, user_prompt


# ============================================================
# API ENDPOINT
# ============================================================

@router.post(
    "/generate-study-material",
    response_model=StudyMaterialOutput
)
async def generate_study_material(
    file: UploadFile = File(...)
):
    # --------------------------------------------------------
    # Validate file
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Extract text
    # --------------------------------------------------------

    text = extract_pdf_text(file_bytes)

    # --------------------------------------------------------
    # Split into chunks
    # --------------------------------------------------------

    chunks = split_text_into_chunks(text)

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="No usable text was found in the PDF."
        )

    print(f"Study material PDF split into {len(chunks)} chunks.")

    # --------------------------------------------------------
    # Process each chunk
    # --------------------------------------------------------

    chunk_results = []

    for index, chunk in enumerate(chunks, start=1):

        print(
            f"Processing study-material chunk "
            f"{index}/{len(chunks)}..."
        )

        system_prompt, user_prompt = build_chunk_prompt(
            chunk,
            index,
            len(chunks)
        )

        result = call_llm_for_json(
            system_prompt,
            user_prompt,
            ChunkOutput
        )

        chunk_results.append(result)

        # Groq TPM protection.
        # Give the rate-limit window some breathing room
        # between requests.
        if index < len(chunks):
            time.sleep(12)

    # --------------------------------------------------------
    # Final synthesis
    # --------------------------------------------------------

    print("Creating final study guide...")

    system_prompt, user_prompt = build_final_prompt(
        chunk_results
    )

    final_result = call_llm_for_json(
        system_prompt,
        user_prompt,
        StudyMaterialOutput
    )

    return final_result
