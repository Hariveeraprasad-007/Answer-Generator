import PyPDF2
import re

def extract_text_from_pdf(pdf_path):
    """
    Extracts text from each page of a PDF document.
    
    Args:
        pdf_path (str): The path to the PDF file.

    Returns:
        str: The concatenated text from all pages of the PDF.
    """
    text = ""
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                # Extract text, handling potential errors for specific pages
                try:
                    text += page.extract_text()
                except Exception as page_e:
                    print(f"Warning: Could not extract text from page {page_num + 1}: {page_e}")
    except FileNotFoundError:
        print(f"Error: PDF file not found at {pdf_path}")
    except Exception as e:
        print(f"Error reading PDF: {e}")
    return text

def parse_questions(full_text):
    """
    Parses the full extracted text from the PDF to identify and clean
    individual questions based on a defined pattern.

    Args:
        full_text (str): The complete text extracted from the PDF.

    Returns:
        dict: A dictionary where keys are question IDs (e.g., 'QA101')
              and values are the cleaned question texts.
    """
    questions = {}
    
    # This regex is designed to capture:
    # 1. The Question ID, potentially including (a) or (b) like QB101 (b)
    # 2. Non-greedily consume any characters that could be part of the header/metadata
    #    between the Q ID and the actual question content.
    # 3. Non-greedily capture the question text itself.
    # 4. Stop when it encounters a pattern indicating the end of a question.
    
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
            # This regex needs to be carefully tuned based on the exact PDF extraction artifacts.
            # Adding more specific patterns to exclude, common in the context of diagrams or table headers.
            excluded_patterns = [
                r'^\s*x\d+\s*$',        # e.g., "x0"
                r'^\s*w\d+\s*$',        # e.g., "wo", "w1", "w2"
                r'^\s*b\s*$',           # e.g., "b"
                r'^\s*\+\s*$',          # e.g., "+"
                r'^\s*y\s*$',           # e.g., "y"
                r'^\s*1\s*$',           # e.g., "1" (often seen near diagrams)
                r'^\s*Input\s*$',       # "Input"
                r'^\s*output\s*$',      # "output"
                r'^\s*hidden\s+layer\s+\d+\s*$', # "hidden layer 1", "hidden layer 2"
                r'^\s*softmax\s*$',     # "softmax"
                r'^\s*Linear\s*$',      # "Linear"
                r'^\s*CO\d\s*$',        # Isolated CO numbers (e.g., "CO1")
                r'^\s*K\d\s*$',         # Isolated K numbers (e.g., "K3")
                r'^\s*Knowledge\s+Level\s*$',
                r'^\s*\(Blooms\)\s*$',
                r'^\s*Difficulty\s+Level\s*$',
                r'^\s*\(1-5\)\s*$',
                r'^\s*Reg\. No\s*$',
                r'^\s*QP\s+Code\s*$',
                r'^\s*Time:\s*Three\s+hours\s*$',
                r'^\s*Maximum\s+marks:\s*\d+\s*$',
                r'^\s*Faculty\s+Name\s*$',
                r'^\s*Department\s+AIDS\s*$',
                r'^\s*Answer\s+All\s+Questions\s*$',
                r'^\s*PART\s+[A-C]\s*$',
                r'^\s*Q\.\s+No\s*$',
                r'^\s*\d+\s*$',         # Isolated numbers (e.g., page numbers or single digits)
                r'^\s*\)\s*$',          # Isolated closing parenthesis
                r'^\s*\.+$',            # Lines with just dots or similar artifacts
                r'^\s*,+\s*$',          # Lines with just commas
                r'^\s*\(Or\)\s*$',      # Lines with just "(Or)"
                r'^\s*marks\)\s*$',     # isolated "marks)" from (X marks)
                r'^\s*\(i+\)\s*$',       # (i), (ii), (iii) markers
                r'^\s*\(a\)\s*$',       # (a), (b) markers for sub-questions when they are standalone on a line
                r'^\s*\(b\)\s*$',
                r'^\s*CO\s*Knowledge\s*$',
                r'^\s*Level\s*$',
                r'^\s*\(Blooms\)\s*$',
                r'^\s*Difficulty\s*$',
                r'^\s*Level\s*$',
                r'^\s*\(1-5\)\s*$',
                r'^\s*Cement BlastFurnaceSlag FlyAsh\s*$', # Specific table headers
                r'^\s*Water Superplasticizer\s*$',
                r'^\s*CoarseAggregate\s*$',
                r'^\s*FineAggregate\s*$',
                r'^\s*Age CompressiveStrength\s*$',
                r'^\s*\d+\.\d+\s*$', # isolated numbers like 676.0
                r'^\s*-\s*$',       # isolated hyphens
                r'^\s*\(Case study/Comprehensive type Questions\)\s*$', # Part C header
                r'^\s*\d+\s*x\s*\d+\s*=\s*\d+\s*marks\)\s*$', # e.g., (1 x 15 15 marks)
                r'^\s*Q\.\s+No\s*$',
                r'^\s*Questions\s*$',
                r'^\s*CO\s*$',
                r'^\s*Knowledge\s*Level\s*$',
                r'^\s*\(Blooms\)\s*$',
                r'^\s*Difficulty\s*Level\s*$',
                r'^\s*\(1-5\)\s*$',
                r'^\s*Faculty Name\s*$',
                r'^\s*Department AIDS\s*$',
                r'^\s*Answer All Questions\s*$'
            ]
            
            should_exclude = False
            for pattern in excluded_patterns:
                if re.match(pattern, line.strip(), re.IGNORECASE):
                    should_exclude = True
                    break
            
            if not should_exclude:
                # Remove any remaining CO/K codes if they are embedded within a line
                line = re.sub(r'\s*\bCO\d\b\s*|\s*\bK\d\b\s*', '', line)
                # Remove (X Marks) directly from the text if they are not the only thing on a line
                line = re.sub(r'\s*\(\d+\s*Marks?\)\s*', '', line)
                # Remove (i), (ii), (iii), (a), (b) if they start a line, but only if they are not meant to be part of the ID
                # The primary capture of (a)/(b) for the ID should happen in the regex
                # This ensures we don't accidentally remove them if they're *part* of the question text.
                line = re.sub(r'^\s*\(i+\)\s*', '', line)
                # For (a) and (b), only remove if they are standalone markers, as they are now captured in the ID.
                # If they appear mid-sentence, they should generally stay unless explicitly filtered by context.
                line = re.sub(r'^\s*\(a\)\s*', '', line)
                line = re.sub(r'^\s*\(b\)\s*', '', line)
                line = re.sub(r'^\s*\d+\s*$', '', line).strip() # Remove isolated numbers
                
                if line.strip(): # Add non-empty, non-whitespace lines
                    cleaned_lines.append(line.strip())

        # Join the cleaned lines back, ensuring proper formatting
        final_q_text = '\n'.join(cleaned_lines).strip()
        
        # Remove any leading "Questions" that might have slipped through at the very start
        final_q_text = re.sub(r'^\s*Questions\s*\n*', '', final_q_text).strip()
        
        # Ensure the final text is not empty before adding
        if final_q_text:
            questions[q_id] = final_q_text
            
    return questions

# --- Main execution part ---
# Assuming you have the PDF file saved as '19AI413-QR APR 2025.pdf'
pdf_file_path = '19AI413-QR APR 2025.pdf'
extracted_content = extract_text_from_pdf(pdf_file_path)

if extracted_content:
    questions_from_pdf = parse_questions(extracted_content)

    print("Extracted Questions:")
    # Print each question with a clear separator
    for q_id, q_text in questions_from_pdf.items():
        print(f"--- {q_id} ---")
        print(q_text)
        print("-" * 20) # A separator line
else:
    print("Failed to extract content from PDF. Please check the file path and content.")
