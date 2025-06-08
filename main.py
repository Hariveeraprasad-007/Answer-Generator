
import os
from flask import Flask, request, render_template_string, jsonify
import PyPDF2
import re
import requests
import json
from io import BytesIO
from pptx import Presentation # Library for .pptx files

app = Flask(__name__)

# --- Configuration ---
# IMPORTANT: Set your Gemini API key here or, even better, as an environment variable.
# For example: export GEMINI_API_KEY="YOUR_API_KEY_HERE"
GEMINI_API_KEY = ''
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

# In-memory storage for uploaded content.
# In a production app, you'd use a more persistent storage solution (e.g., database, cloud storage).
QUESTION_BANK_CONTENT = ""
QUESTION_BANK_FILENAME = ""
SLIDE_CONTENTS = {} # Stores {filename: full_text_content}


# --- Helper Functions ---

def extract_text_from_pdf(pdf_file_stream):
    """
    Extracts text from a PDF file stream.
    
    Args:
        pdf_file_stream: A file-like object (BytesIO) of the PDF content.

    Returns:
        str: The concatenated text from all pages of the PDF.
    """
    text = ""
    try:
        reader = PyPDF2.PdfReader(pdf_file_stream)
        for page_num in range(len(reader.pages)):
            page = reader.pages[page_num]
            try:
                text += page.extract_text()
            except Exception as page_e:
                print(f"Warning: Could not extract text from page {page_num + 1}: {page_e}")
    except Exception as e:
        print(f"Error reading PDF stream: {e}")
    return text

def extract_text_from_pptx(pptx_file_stream):
    """
    Extracts text from a PowerPoint (.pptx) file stream.
    
    Args:
        pptx_file_stream: A file-like object (BytesIO) of the PPTX content.

    Returns:
        str: The concatenated text from all slides of the PPTX.
    """
    text = ""
    try:
        prs = Presentation(pptx_file_stream)
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text += shape.text + "\n"
    except Exception as e:
        print(f"Error reading PPTX stream: {e}")
    return text

def parse_questions(full_text):
    """
    Parses the full extracted text from the PDF to identify and clean
    individual questions based on a defined pattern.

    Args:
        full_text (str): The complete text extracted from the PDF.

    Returns:
        list: A list of dictionaries, where each dict has 'id' and 'text' for a question.
    """
    questions = []
    
    # Updated regex to directly capture 'QB101 (b)' or 'QC101 (a)' as part of the ID,
    # if it appears in that format in the raw text.
    # It also accounts for the `,"(a)` and `,"(b)` structures that might follow the base ID
    # but lead the question content.
    question_block_pattern = re.compile(
        r'(Q[ABC]\d{3}(?:\s*\([ab]\))?)'     # Group 1: Captures Q ID (e.g., QA101, QB101 (b))
        r'(?:[^Q]*?)'                        # Non-greedily consume any characters until 'Questions', '(' or question text starts
        r'(?:Questions\s*|"\s*\([ab]\)\s*|)' # Optional 'Questions', OR '", (a)'/'", (b)' literal, followed by whitespace
        r'\s*(.*?)'                          # Group 2: Non-greedily captures the main question text content
        r'(?=\s*"\s*CO\s*|\s*Q[ABC]\d{3}(?:\s*\([ab]\))?|$)' # Positive Lookahead: asserts the end of the current question block
        ,re.DOTALL
    )

    matches = question_block_pattern.finditer(full_text)

    for match in matches:
        q_id = match.group(1).strip() # This will now capture QB101, QB101 (b), etc.
        raw_q_text = match.group(2).strip()

        # Further cleaning steps for the extracted question text:
        lines = raw_q_text.split('\n')
        cleaned_lines = []
        for line in lines:
            # Remove any leading/trailing quotes or commas that might be artifacts of extraction
            line = re.sub(r'^\s*["\s,]+|["\s,]+\s*$', '', line)
            
            # Remove specific diagram elements or extraneous table info if they appear as isolated lines
            excluded_patterns = [
                r'^\s*x\d+\s*$', r'^\s*w\d+\s*$', r'^\s*b\s*$', r'^\s*\+\s*$', r'^\s*y\s*$', r'^\s*1\s*$',
                r'^\s*Input\s*$', r'^\s*output\s*$', r'^\s*hidden\s+layer\s+\d+\s*$', r'^\s*softmax\s*$',
                r'^\s*Linear\s*$', r'^\s*CO\d\s*$', r'^\s*K\d\s*$', r'^\s*Knowledge\s+Level\s*$',
                r'^\s*\(Blooms\)\s*$', r'^\s*Difficulty\s+Level\s*$', r'^\s*\(1-5\)\s*$', r'^\s*Reg\. No\s*$',
                r'^\s*QP\s+Code\s*$', r'^\s*Time:\s*Three\s+hours\s*$', r'^\s*Maximum\s+marks:\s*\d+\s*$',
                r'^\s*Faculty\s+Name\s*$', r'^\s*Department\s+AIDS\s*$', r'^\s*Answer\s+All\s+Questions\s*$',
                r'^\s*PART\s+[A-C]\s*$', r'^\s*Q\.\s+No\s*$', r'^\s*\d+\s*$', r'^\s*\)\s*$', r'^\s*\.+$',
                r'^\s*,+\s*$', r'^\s*\(Or\)\s*$', r'^\s*marks\)\s*$', r'^\s*\(i+\)\s*$', r'^\s*\(a\)\s*',
                r'^\s*\(b\)\s*', r'^\s*CO\s*Knowledge\s*$', r'^\s*Level\s*$', r'^\s*\(Blooms\)\s*$',
                r'^\s*Difficulty\s*$', r'^\s*Level\s*$', r'^\s*\(1-5\)\s*$',
                r'^\s*Cement BlastFurnaceSlag FlyAsh\s*$', r'^\s*Water Superplasticizer\s*$',
                r'^\s*CoarseAggregate\s*$', r'^\s*FineAggregate\s*$', r'^\s*Age CompressiveStrength\s*$',
                r'^\s*\d+\.\d+\s*$', r'^\s*-\s*$', r'^\s*\(Case study/Comprehensive type Questions\)\s*$',
                r'^\s*\d+\s*x\s*\d+\s*=\s*\d+\s*marks\)\s*$', r'^\s*Q\.\s+No\s*$', r'^\s*Questions\s*$',
                r'^\s*CO\s*$', r'^\s*Knowledge\s*Level\s*$', r'^\s*\(Blooms\)\s*$', r'^\s*Difficulty\s*Level\s*$',
                r'^\s*\(1-5\)\s*$', r'^\s*Faculty Name\s*$', r'^\s*Department AIDS\s*$', r'^\s*Answer All Questions\s*$'
            ]
            
            should_exclude = False
            for pattern in excluded_patterns:
                if re.match(pattern, line.strip(), re.IGNORECASE):
                    should_exclude = True
                    break
            
            if not should_exclude:
                line = re.sub(r'\s*\bCO\d\b\s*|\s*\bK\d\b\s*', '', line)
                line = re.sub(r'\s*\(\d+\s*Marks?\)\s*', '', line)
                line = re.sub(r'^\s*\(i+\)\s*', '', line)
                line = re.sub(r'^\s*\(a\)\s*', '', line)
                line = re.sub(r'^\s*\(b\)\s*', '', line)
                line = re.sub(r'^\s*\d+\s*$', '', line).strip()
                
                if line.strip():
                    cleaned_lines.append(line.strip())

        final_q_text = '\n'.join(cleaned_lines).strip()
        final_q_text = re.sub(r'^\s*Questions\s*\n*', '', final_q_text).strip()
        
        if final_q_text:
            questions.append({'id': q_id, 'text': final_q_text})
            
    return questions

def find_relevant_content(query, all_slide_texts, top_n_snippets=3):
    """
    Finds relevant content snippets from all slide texts based on keywords in the query.
    Returns the concatenated content string and a list of unique filenames that contributed.

    Args:
        query (str): The question or search query.
        all_slide_texts (dict): Dictionary of {filename: text_content} for all slides.
        top_n_snippets (int): Number of top snippets to return.

    Returns:
        tuple: (str, list) - concatenated relevant text, and list of unique source filenames.
    """
    relevant_snippets_with_source = []
    query_words = set(re.findall(r'\b\w+\b', query.lower())) # Extract keywords

    for filename, text_content in all_slide_texts.items():
        paragraphs = re.split(r'\n{2,}', text_content) 
        
        scored_snippets = []
        for para in paragraphs:
            para_lower = para.lower()
            score = sum(1 for word in query_words if word in para_lower)
            if score > 0:
                # Store (score, paragraph text, source filename)
                scored_snippets.append((score, para.strip(), filename))
        
        # Sort by score (descending)
        scored_snippets.sort(key=lambda x: x[0], reverse=True)
        # Add top N snippets from this file
        relevant_snippets_with_source.extend(scored_snippets[:top_n_snippets])
    
    # Sort all collected snippets by score (descending) and take overall top N
    relevant_snippets_with_source.sort(key=lambda x: x[0], reverse=True)
    
    final_snippets_text = []
    unique_source_filenames = set()

    for score, snippet_text, source_filename in relevant_snippets_with_source[:top_n_snippets]:
        final_snippets_text.append(snippet_text)
        unique_source_filenames.add(source_filename)
    
    return "\n".join(final_snippets_text), list(unique_source_filenames)


def generate_answer_with_gemini(question_id, question_text, context):
    """
    Calls the Gemini API to generate an elaborated answer, adjusting length based on question type.

    Args:
        question_id (str): The ID of the question (e.g., 'QA101').
        question_text (str): The full text of the question.
        context (str): Relevant text gathered from slides.

    Returns:
        str: The generated answer.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_GEMINI_API_KEY":
        return "ERROR: Gemini API key not configured. Please set GEMINI_API_KEY."

    # Determine question type and target length based on the ID prefix
    q_id_prefix = question_id.split(' ')[0][:2].upper() # e.g., 'QA', 'QB', 'QC'
    target_lines = 0
    if q_id_prefix == 'QA': # Part A: 2 marks
        target_lines = 4
    elif q_id_prefix == 'QB': # Part B: 13 marks
        target_lines = 100
    elif q_id_prefix == 'QC': # Part C: 15 marks
        target_lines = 130
    else:
        target_lines = 50 # Default if prefix not matched

    chat_history = []
    
    # Construct the prompt carefully, including length and image/diagram directives
    prompt = f"""
    You are an AI assistant specialized in deep learning concepts, explaining them in an academic style.
    
    Given the following context from academic slides:
    ```
    {context if context else "No specific relevant information found in the provided slides. Use general deep learning knowledge."}
    ```

    Based on the question: '{question_text}'

    Please provide a detailed and elaborated answer. Aim for approximately {target_lines} lines in your answer.
    Ensure you use the provided context and expand on it. If the question asks for code implementations or
    requires a network diagram, flow chart, or any other figure, please describe conceptually what such a
    diagram or code would entail, explaining its purpose and key elements, as if it were present in a slide.
    Focus on providing a comprehensive academic-style answer suitable for a study document.
    Format your answer using Markdown (e.g., bolding, bullet points, LaTeX for formulas for mathematical expressions).
    """
    
    chat_history.append({"role": "user", "parts": [{"text": prompt}]})
    
    payload = {"contents": chat_history}
    
    try:
        response = requests.post(GEMINI_API_URL, headers={"Content-Type": "application/json"}, json=payload)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        
        result = response.json()
        
        if result.get("candidates") and result["candidates"][0].get("content") and result["candidates"][0]["content"].get("parts"):
            return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            print(f"Unexpected API response structure: {result}")
            return "Could not generate answer. Unexpected API response structure."
            
    except requests.exceptions.RequestException as e:
        print(f"API Request failed: {e}")
        return f"Could not connect to Gemini API: {e}"
    except json.JSONDecodeError:
        print(f"Failed to decode JSON from API response: {response.text}")
        return "Failed to decode API response."
    except Exception as e:
        print(f"An unexpected error occurred during API call: {e}")
        return f"An unexpected error occurred: {e}"


# --- Flask Routes ---

@app.route('/')
def index():
    """Renders the main HTML page for uploading files and generating answers."""
    return render_template_string(HTML_TEMPLATE)

@app.route('/upload_question_bank', methods=['POST'])
def upload_question_bank():
    """Handles the upload of a single PDF question bank file."""
    global QUESTION_BANK_CONTENT, QUESTION_BANK_FILENAME

    if 'file' not in request.files:
        print("Backend: No 'file' part in request for QB upload.")
        return jsonify({"status": "error", "message": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        print("Backend: Empty filename for QB upload.")
        return jsonify({"status": "error", "message": "No selected file"}), 400
    
    if not file.filename.lower().endswith('.pdf'):
        print(f"Backend: Invalid file type for QB upload: {file.filename}")
        return jsonify({"status": "error", "message": "Question Bank must be a PDF file."}), 400

    print(f"Backend: Attempting to extract text from QB: {file.filename}")
    file_stream = BytesIO(file.read())
    text_content = extract_text_from_pdf(file_stream)

    if text_content:
        QUESTION_BANK_CONTENT = text_content
        QUESTION_BANK_FILENAME = file.filename
        print(f"Backend: Successfully processed QB: {file.filename}")
        return jsonify({
            "status": "success",
            "message": f"Question Bank '{file.filename}' uploaded and processed successfully.",
            "filename": file.filename
        })
    else:
        QUESTION_BANK_CONTENT = ""
        QUESTION_BANK_FILENAME = ""
        print(f"Backend: Failed to extract text from QB: {file.filename}")
        return jsonify({"status": "error", "message": f"Could not process Question Bank '{file.filename}'."}), 400


@app.route('/upload_slides', methods=['POST'])
def upload_slides():
    """Handles PDF and PPTX lecture slide file uploads."""
    global SLIDE_CONTENTS # Make sure to access the global dictionary

    if 'files[]' not in request.files:
        print("Backend: No 'files[]' part in request for slides upload.")
        return jsonify({"status": "error", "message": "No files part"}), 400
    
    files = request.files.getlist('files[]')
    if not files:
        print("Backend: No selected files for slides upload.")
        return jsonify({"status": "error", "message": "No selected file"}), 400

    SLIDE_CONTENTS.clear() # Clear previous slide uploads
    uploaded_slide_filenames = []
    processed_count = 0

    for file in files:
        if file.filename == '':
            continue
        
        filename_lower = file.filename.lower()
        text_content = ""

        if filename_lower.endswith('.pdf'):
            print(f"Backend: Extracting text from PDF slide: {file.filename}")
            file_stream = BytesIO(file.read())
            text_content = extract_text_from_pdf(file_stream)
        elif filename_lower.endswith('.pptx'):
            print(f"Backend: Extracting text from PPTX slide: {file.filename}")
            file_stream = BytesIO(file.read())
            text_content = extract_text_from_pptx(file_stream)
        else:
            print(f"Backend: Skipping unsupported file type: {file.filename}")
            continue # Skip unsupported file types

        if text_content:
            SLIDE_CONTENTS[file.filename] = text_content
            uploaded_slide_filenames.append(file.filename)
            processed_count += 1
            print(f"Backend: Successfully processed slide: {file.filename}")
        else:
            print(f"Backend: Warning: Could not extract text from slide {file.filename}")
    
    if processed_count > 0:
        return jsonify({
            "status": "success",
            "message": f"Successfully uploaded and processed {processed_count} lecture slide(s) (PDF/PPTX).",
            "uploaded_files": uploaded_slide_filenames
        })
    else:
        print("Backend: No supported PDF/PPTX lecture slides processed.")
        return jsonify({"status": "error", "message": "No supported PDF/PPTX lecture slides processed."}), 400


@app.route('/get_questions', methods=['POST'])
def get_questions():
    """
    Extracts and returns the list of questions from the uploaded PDF question bank.
    This is a precursor to answer generation, allowing frontend to display total count.
    """
    if not QUESTION_BANK_CONTENT:
        print("Backend: No Question Bank content found for get_questions.")
        return jsonify({"status": "error", "message": "Please upload a PDF Question Bank first."}), 400
    
    questions = parse_questions(QUESTION_BANK_CONTENT)

    if not questions:
        print(f"Backend: No questions extracted from '{QUESTION_BANK_FILENAME}'.")
        return jsonify({"status": "error", "message": f"No questions extracted from '{QUESTION_BANK_FILENAME}'. Please check its format."}), 400
    
    print(f"Backend: Returning {len(questions)} questions from '{QUESTION_BANK_FILENAME}'.")
    return jsonify({"status": "success", "questions": questions, "filename": QUESTION_BANK_FILENAME})


@app.route('/generate_single_answer', methods=['POST'])
def generate_single_answer():
    """
    Generates a single answer for a given question ID and text.
    Called repeatedly by the frontend to show progress.
    """
    data = request.get_json()
    q_id = data.get('q_id')
    q_text = data.get('q_text')

    if not q_id or not q_text:
        print("Backend: Missing question ID or text for generate_single_answer.")
        return jsonify({"status": "error", "message": "Missing question ID or text."}), 400

    if not SLIDE_CONTENTS:
        print("Backend: Lecture slides not uploaded for generate_single_answer.")
        return jsonify({"status": "error", "message": "Lecture slides not uploaded. Cannot generate answer."}), 400

    # Find relevant context from ALL uploaded slides (PDFs and PPTXs)
    context_str, slide_sources = find_relevant_content(q_text, SLIDE_CONTENTS)

    if not context_str:
        context_str = "No specific relevant information found in the provided slides."
        print(f"Backend: No specific context found for '{q_id}'.")
    
    # Generate answer using Gemini API
    print(f"Backend: Generating answer for '{q_id}'...")
    generated_answer = generate_answer_with_gemini(q_id, q_text, context_str)
    
    if "ERROR:" in generated_answer or "Could not generate answer" in generated_answer:
        print(f"Backend: Error generating answer for '{q_id}': {generated_answer}")
        return jsonify({"status": "error", "message": generated_answer, "q_id": q_id})
    
    print(f"Backend: Successfully generated answer for '{q_id}'.")
    return jsonify({"status": "success", "q_id": q_id, "answer": generated_answer, "slide_sources": slide_sources})


# --- HTML Template ---

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Answer Generator</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {
            font-family: 'Inter', sans-serif;
            background-color: #f8f8f8;
            color: #333;
        }
        .container {
            max-width: 960px;
            margin: 0 auto;
            padding: 2rem;
        }
        textarea {
            font-family: monospace; /* For displaying Markdown */
            min-height: 400px; /* Make it large enough */
        }
        .spinner {
            border: 4px solid rgba(0, 0, 0, 0.1);
            width: 20px; /* Smaller spinner for uploads */
            height: 20px;
            border-radius: 50%;
            border-left-color: #007bff;
            animation: spin 1s ease infinite;
            display: none; /* Hidden by default */
            vertical-align: middle;
            margin-left: 0.5rem;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        #progressContainer {
            margin-top: 1rem;
            font-size: 0.9em;
            color: #555;
        }
        #progressBar {
            width: 0%;
            height: 10px;
            background-color: #4CAF50; /* Green */
            border-radius: 5px;
            transition: width 0.3s ease-in-out;
            margin-top: 0.5rem;
        }
    </style>
</head>
<body class="bg-gray-100 flex flex-col items-center py-8">
    <div class="container bg-white shadow-lg rounded-xl p-8 mb-8">
        <h1 class="text-4xl font-bold text-center text-blue-800 mb-6">AI Answer Generator</h1>
        <p class="text-center text-gray-600 mb-8">Upload your PDF question bank and lecture slides (PDFs/PPTXs) to generate elaborated answers.</p>

        <div class="mb-8 p-6 border border-blue-200 rounded-lg bg-blue-50">
            <h2 class="text-2xl font-semibold text-blue-700 mb-4">1. Upload Question Bank (PDF Only)</h2>
            <form id="uploadQbForm" enctype="multipart/form-data" class="space-y-4">
                <input type="file" name="file" id="qbFileInput" accept=".pdf" 
                       class="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 
                              file:rounded-full file:border-0 file:text-sm file:font-semibold
                              file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer">
                <button type="submit" 
                        class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 px-4 rounded-lg 
                               shadow-md transition duration-300 ease-in-out">
                    Upload Question Bank
                </button>
            </form>
            <div id="qbUploadStatus" class="mt-4 text-center text-sm"></div>
            <div id="qbUploadSpinner" class="spinner mx-auto" style="display: none;"></div>
            <p id="uploadedQbFilename" class="mt-2 text-sm text-gray-700"></p>
        </div>

        <div class="mb-8 p-6 border border-purple-200 rounded-lg bg-purple-50">
            <h2 class="text-2xl font-semibold text-purple-700 mb-4">2. Upload Lecture Slides (PDFs or PPTXs)</h2>
            <form id="uploadSlidesForm" enctype="multipart/form-data" class="space-y-4">
                <input type="file" name="files[]" id="slidesFileInput" multiple accept=".pdf,.pptx" 
                       class="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 
                              file:rounded-full file:border-0 file:text-sm file:font-semibold
                              file:bg-purple-50 file:text-purple-700 hover:file:bg-purple-100 cursor-pointer">
                <button type="submit" 
                        class="w-full bg-purple-600 hover:bg-purple-700 text-white font-bold py-3 px-4 rounded-lg 
                               shadow-md transition duration-300 ease-in-out">
                    Upload Slides
                </button>
            </form>
            <div id="slidesUploadStatus" class="mt-4 text-center text-sm"></div>
            <div id="slidesUploadSpinner" class="spinner mx-auto" style="display: none;"></div>
            <ul id="uploadedSlidesList" class="mt-4 text-sm text-gray-700 list-disc list-inside"></ul>
        </div>

        <div class="mb-8 p-6 border border-green-200 rounded-lg bg-green-50">
            <h2 class="text-2xl font-semibold text-green-700 mb-4">3. Generate Answers</h2>
            <button id="generateBtn" 
                    class="w-full bg-green-600 hover:bg-green-700 text-white font-bold py-3 px-4 rounded-lg 
                           shadow-md transition duration-300 ease-in-out">
                Generate Answers for All Questions
            </button>
            <div id="generateStatus" class="mt-4 text-center text-sm text-red-600"></div>
            <div id="generationSpinner" class="spinner mx-auto mt-4" style="display: none;"></div>
            <div id="progressContainer" style="display: none;">
                <p id="progressText">Starting...</p>
                <p id="currentSlideSourcesText" class="text-xs text-gray-500 mt-1"></p> <!-- New line for slide sources -->
                <div class="w-full bg-gray-200 rounded-full h-2.5 dark:bg-gray-700 mt-2">
                    <div id="progressBar" class="bg-green-600 h-2.5 rounded-full" style="width: 0%"></div>
                </div>
                <p id="estimatedTime" class="mt-2 text-xs text-gray-500"></p>
            </div>
        </div>

        <div class="p-6 border border-gray-300 rounded-lg bg-gray-50">
            <h2 class="text-2xl font-semibold text-gray-700 mb-4">Generated Answer Document (Markdown)</h2>
            <textarea id="answerOutput" readonly 
                      class="w-full p-4 border border-gray-300 rounded-lg bg-white text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"></textarea>
            <button id="copyBtn" class="mt-4 bg-gray-200 hover:bg-gray-300 text-gray-800 font-bold py-2 px-4 rounded-lg shadow-sm transition duration-300 ease-in-out">
                Copy to Clipboard
            </button>
            <p class="mt-2 text-sm text-gray-600">
                You can paste the copied Markdown text into any word processor (e.g., Microsoft Word, Google Docs) to convert it to a document format.
            </p>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const uploadQbForm = document.getElementById('uploadQbForm');
            const qbFileInput = document.getElementById('qbFileInput');
            const qbUploadStatus = document.getElementById('qbUploadStatus');
            const qbUploadSpinner = document.getElementById('qbUploadSpinner'); 
            const uploadedQbFilename = document.getElementById('uploadedQbFilename');

            const uploadSlidesForm = document.getElementById('uploadSlidesForm');
            const slidesFileInput = document.getElementById('slidesFileInput');
            const slidesUploadStatus = document.getElementById('slidesUploadStatus');
            const slidesUploadSpinner = document.getElementById('slidesUploadSpinner'); 
            const uploadedSlidesList = document.getElementById('uploadedSlidesList');

            const generateBtn = document.getElementById('generateBtn');
            const generateStatus = document.getElementById('generateStatus');
            const generationSpinner = document.getElementById('generationSpinner'); 
            const progressContainer = document.getElementById('progressContainer');
            const progressText = document.getElementById('progressText');
            const currentSlideSourcesText = document.getElementById('currentSlideSourcesText'); 
            const progressBar = document.getElementById('progressBar');
            const estimatedTime = document.getElementById('estimatedTime');
            const answerOutput = document.getElementById('answerOutput');
            const copyBtn = document.getElementById('copyBtn');

            // --- Upload Question Bank ---
            uploadQbForm.addEventListener('submit', async function(e) {
                e.preventDefault();
                console.log('QB Upload button clicked.');
                qbUploadStatus.textContent = 'Uploading and processing...';
                qbUploadStatus.className = 'mt-4 text-center text-sm text-gray-700';
                qbUploadSpinner.style.display = 'block'; // Show spinner
                uploadedQbFilename.textContent = '';
                answerOutput.value = '';
                generateStatus.textContent = '';
                generationSpinner.style.display = 'none'; // Ensure other spinners are hidden
                progressContainer.style.display = 'none'; 
                currentSlideSourcesText.textContent = ''; // Clear slide sources

                const formData = new FormData();
                if (qbFileInput.files.length === 0) {
                    qbUploadStatus.textContent = 'Please select a PDF file for the Question Bank.';
                    qbUploadStatus.className = 'mt-4 text-center text-sm text-red-600';
                    qbUploadSpinner.style.display = 'none'; 
                    console.warn('No file selected for QB upload.');
                    return;
                }
                formData.append('file', qbFileInput.files[0]);
                console.log('QB File selected:', qbFileInput.files[0].name);

                try {
                    const response = await fetch('/upload_question_bank', {
                        method: 'POST',
                        body: formData
                    });
                    console.log('QB Upload response status:', response.status);
                    const data = await response.json();
                    console.log('QB Upload response data:', data);
                    
                    qbUploadStatus.textContent = data.message;
                    if (data.status === 'success') {
                        uploadedQbFilename.textContent = `File: ${data.filename}`;
                        qbUploadStatus.className = 'mt-4 text-center text-sm text-green-600';
                    } else {
                        qbUploadStatus.className = 'mt-4 text-center text-sm text-red-600';
                    }
                } catch (error) {
                    console.error('Error during QB upload fetch:', error);
                    qbUploadStatus.textContent = 'An error occurred during Question Bank upload. Please check console for details.';
                    qbUploadStatus.className = 'mt-4 text-center text-sm text-red-600';
                } finally {
                    qbUploadSpinner.style.display = 'none'; 
                }
            });

            // --- Upload Lecture Slides ---
            uploadSlidesForm.addEventListener('submit', async function(e) {
                e.preventDefault();
                console.log('Slides Upload button clicked.');
                slidesUploadStatus.textContent = 'Uploading and processing...';
                slidesUploadStatus.className = 'mt-4 text-center text-sm text-gray-700';
                slidesUploadSpinner.style.display = 'block'; 
                uploadedSlidesList.innerHTML = '';
                answerOutput.value = '';
                generateStatus.textContent = '';
                generationSpinner.style.display = 'none'; 
                progressContainer.style.display = 'none'; 
                currentSlideSourcesText.textContent = ''; // Clear slide sources

                const formData = new FormData();
                if (slidesFileInput.files.length === 0) {
                    slidesUploadStatus.textContent = 'Please select at least one PDF or PPTX file for slides.';
                    slidesUploadStatus.className = 'mt-4 text-center text-sm text-red-600';
                    slidesUploadSpinner.style.display = 'none'; 
                    console.warn('No files selected for slides upload.');
                    return;
                }

                for (let i = 0; i < slidesFileInput.files.length; i++) {
                    formData.append('files[]', slidesFileInput.files[i]);
                    console.log(`Slide file selected: ${slidesFileInput.files[i].name}`);
                }

                try {
                    const response = await fetch('/upload_slides', {
                        method: 'POST',
                        body: formData
                    });
                    console.log('Slides Upload response status:', response.status);
                    const data = await response.json();
                    console.log('Slides Upload response data:', data);
                    
                    slidesUploadStatus.textContent = data.message;
                    if (data.status === 'success') {
                        data.uploaded_files.forEach(filename => {
                            const li = document.createElement('li');
                            li.textContent = filename;
                            uploadedSlidesList.appendChild(li);
                        });
                        slidesUploadStatus.className = 'mt-4 text-center text-sm text-green-600';
                    } else {
                        slidesUploadStatus.className = 'mt-4 text-center text-sm text-red-600';
                    }
                } catch (error) {
                    console.error('Error during Slides upload fetch:', error);
                    slidesUploadStatus.textContent = 'An error occurred during slides upload. Please check console for details.';
                    slidesUploadStatus.className = 'mt-4 text-center text-sm text-red-600';
                } finally {
                    slidesUploadSpinner.style.display = 'none'; 
                }
            });

            // --- Generate Answers (New Multi-step Process) ---
            generateBtn.addEventListener('click', async function() {
                generateStatus.textContent = '';
                answerOutput.value = '';
                generationSpinner.style.display = 'block'; 
                progressContainer.style.display = 'block'; 
                progressBar.style.width = '0%';
                progressText.textContent = 'Fetching questions from Question Bank...';
                currentSlideSourcesText.textContent = ''; // Clear slide sources at start of generation
                estimatedTime.textContent = '';
                console.log('Generate Answers button clicked. Starting question fetch.');

                let questions = [];
                try {
                    // Step 1: Get all questions
                    const qbResponse = await fetch('/get_questions', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        }
                    });
                    console.log('Get Questions response status:', qbResponse.status);
                    const qbData = await qbResponse.json();
                    console.log('Get Questions response data:', qbData);

                    if (qbData.status === 'success') {
                        questions = qbData.questions;
                        if (questions.length === 0) {
                            generateStatus.textContent = 'No questions found in the uploaded Question Bank.';
                            generateStatus.className = 'mt-4 text-center text-sm text-red-600';
                            generationSpinner.style.display = 'none';
                            progressContainer.style.display = 'none';
                            return;
                        }
                        const avg_time_per_q = 20; // seconds, average for LLM call
                        const total_estimated_time_seconds = questions.length * avg_time_per_q;
                        const minutes = Math.floor(total_estimated_time_seconds / 60);
                        const seconds = total_estimated_time_seconds % 60;

                        progressText.textContent = `Found ${questions.length} questions. Starting answer generation...`;
                        estimatedTime.textContent = `Estimated total time: ~${minutes}m ${seconds}s (approx. ${avg_time_per_q}s per question)`;
                    } else {
                        generateStatus.textContent = qbData.message;
                        generateStatus.className = 'mt-4 text-center text-sm text-red-600';
                        generationSpinner.style.display = 'none';
                        progressContainer.style.display = 'none';
                        return;
                    }
                } catch (error) {
                    console.error('Error fetching questions from backend:', error);
                    generateStatus.textContent = 'An error occurred while fetching questions. Please ensure Question Bank is uploaded and server is running.';
                    generateStatus.className = 'mt-4 text-center text-sm text-red-600';
                    generationSpinner.style.display = 'none';
                    progressContainer.style.display = 'none';
                    return;
                }

                // Step 2: Generate answers for each question sequentially
                let generatedAnswersCount = 0;
                // Clear previous output and add main title
                answerOutput.value = "# Generated Answer Document\\n\\n"; 
                answerOutput.value += `This document contains answers for questions extracted from **${uploadedQbFilename.textContent.replace('File: ', '')}**, elaborated using information from all uploaded lecture slides and the Gemini API.\\n\\n---\\n\\n`;

                for (let i = 0; i < questions.length; i++) {
                    const q = questions[i];
                    progressText.textContent = `Generating answer for Q. ${i + 1} of ${questions.length}: ${q.id}...`;
                    progressBar.style.width = `${((i + 1) / questions.length) * 100}%`;
                    currentSlideSourcesText.textContent = 'Reading from slides: ...'; // Placeholder before fetch

                    try {
                        console.log(`Requesting answer for Q. ${q.id}`);
                        const answerResponse = await fetch('/generate_single_answer', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({ q_id: q.id, q_text: q.text })
                        });
                        console.log(`Answer response status for ${q.id}:`, answerResponse.status);
                        const answerData = await answerResponse.json();
                        console.log(`Answer response data for ${q.id}:`, answerData);

                        if (answerData.status === 'success') {
                            answerOutput.value += `## Question ID: ${q.id}\\n`;
                            answerOutput.value += `**Question:** ${q.text}\\n\\n`;
                            answerOutput.value += `**Answer:**\\n${answerData.answer}\\n\\n`;
                            answerOutput.value += "---\\n\\n";
                            answerOutput.scrollTop = answerOutput.scrollHeight; // Scroll to bottom
                            generatedAnswersCount++;
                            currentSlideSourcesText.textContent = `Reading from slides: ${answerData.slide_sources.join(', ') || 'N/A'}`;
                        } else {
                            answerOutput.value += `## Question ID: ${q.id}\\n`;
                            answerOutput.value += `**Question:** ${q.text}\\n\\n`;
                            answerOutput.value += `**Answer:** Failed to generate answer: ${answerData.message || 'Unknown error'}\\n\\n`;
                            answerOutput.value += "---\\n\\n";
                            answerOutput.scrollTop = answerOutput.scrollHeight;
                            console.error(`Error for Q. ${q.id}: ${answerData.message}`);
                            currentSlideSourcesText.textContent = `Reading from slides: Error or N/A`;
                        }
                    } catch (error) {
                        console.error(`Network error during single answer generation for Q. ${q.id}:`, error);
                        answerOutput.value += `## Question ID: ${q.id}\\n`;
                        answerOutput.value += `**Question:** ${q.text}\\n\\n`;
                        answerOutput.value += `**Answer:** Network error during generation. Please check console for details. (Likely API key issue or server unreachable)\\n\\n`;
                        answerOutput.value += "---\\n\\n";
                        answerOutput.scrollTop = answerOutput.scrollTop = answerOutput.scrollHeight; 
                        currentSlideSourcesText.textContent = `Reading from slides: Network Error`;
                    }
                }

                generationSpinner.style.display = 'none'; // Hide generation spinner
                progressBar.style.width = '100%'; // Ensure progress bar is full
                progressText.textContent = `All ${questions.length} answers generated!`;
                currentSlideSourcesText.textContent = ''; // Clear final slide sources
                estimatedTime.textContent = ''; // Clear estimated time
                generateStatus.textContent = 'Process completed successfully!';
                generateStatus.className = 'mt-4 text-center text-sm text-green-600';
                console.log('All answers generation process completed.');
            });

            // --- Copy to Clipboard ---
            copyBtn.addEventListener('click', function() {
                answerOutput.select();
                try {
                    document.execCommand('copy');
                    alert('Answer document copied to clipboard!'); 
                } catch (err) {
                    console.error('Failed to copy text: ', err);
                    alert('Failed to copy text. Please manually copy from the textbox.');
                }
            });
        });
    </script>
</body>
</html>
"""
if __name__ == '__main__':
    # For development, run in debug mode. In production, use a WSGI server.
    app.run(debug=True)
