import PyPDF2
import os
import sys

pdf_dir = r"d:\HACKATHONS\India Innovates\Synapse\Execution plans-stuff"
output_dir = r"d:\HACKATHONS\India Innovates\Synapse\extracted_text"
os.makedirs(output_dir, exist_ok=True)

pdf_files = [f for f in os.listdir(pdf_dir) if f.endswith('.pdf')]
pdf_files.sort()

for pdf_file in pdf_files:
    pdf_path = os.path.join(pdf_dir, pdf_file)
    txt_name = pdf_file.replace('.pdf', '.txt')
    txt_path = os.path.join(output_dir, txt_name)
    
    try:
        reader = PyPDF2.PdfReader(pdf_path)
        text = ""
        for page_num, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text += f"\n--- Page {page_num+1} ---\n"
                text += page_text
        
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(text)
        
        print(f"Extracted: {pdf_file} -> {txt_name} ({len(text)} chars)")
    except Exception as e:
        print(f"Error extracting {pdf_file}: {e}")

print("\nDone!")
