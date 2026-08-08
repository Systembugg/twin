# DOCX Generation Skill Cheatsheet (python-docx)

## CRITICAL GOTCHAS & RULES
1. **Never write raw binary text to `.docx` files!** Always write a Python generator script (e.g. `make_doc.py`) and run `python make_doc.py` in Bash to compile the Word Document.
2. **Document Structure & Paragraphs:**
   - Use `doc.add_heading('Title', level=0)` for main title.
   - Use `doc.add_heading('Section', level=1)` for major sections.
   - Add bold/italic styling via `run = p.add_run('text'); run.bold = True`.
3. **Verification Step:**
   - Always verify the generated `.docx` file by reopening it: `python -c "import docx; doc=docx.Document('output.docx'); print('DOCX Validated:', len(doc.paragraphs))"`

## VERIFIED WORKING TEMPLATE SCRIPT
```python
from docx import Document
from docx.shared import Inches, Pt, RGBColor

doc = Document()
doc.add_heading("Project Overview & Documentation", level=0)

p = doc.add_paragraph("This document provides a comprehensive technical overview.")
run = p.add_run(" Note: Key metrics are highlighted below.")
run.bold = True

doc.add_heading("1. Key Deliverables", level=1)
table = doc.add_table(rows=1, cols=3)
hdr_cells = table.rows[0].cells
hdr_cells[0].text = "Item"
hdr_cells[1].text = "Owner"
hdr_cells[2].text = "Status"

doc.save("output.docx")
print("Successfully generated output.docx")
```
