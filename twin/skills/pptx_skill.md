# PPTX Generation Skill Cheatsheet (python-pptx)

## CRITICAL GOTCHAS & RULES
1. **Never write raw binary text to `.pptx` files!** Always write a Python generator script (e.g. `make_ppt.py`) and run `python make_ppt.py` in Bash to compile the PowerPoint file.
2. **Slide Layout IDs:**
   - `prs.slide_layouts[0]` = Title Slide (Title + Subtitle)
   - `prs.slide_layouts[1]` = Content Slide (Title + Content)
   - `prs.slide_layouts[6]` = Blank Slide (Ideal for custom positions, shapes, tables, charts)
3. **Margins & Measurements:**
   - Always import `Inches, Pt, RGBColor` from `pptx.util` and `pptx.dml.color`.
4. **Verification Step:**
   - Always verify the generated `.pptx` file by reopening it: `python -c "import pptx; prs=pptx.Presentation('output.pptx'); print('PPT Validated:', len(prs.slides))"`

## VERIFIED WORKING TEMPLATE SCRIPT
```python
import sys
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor

prs = Presentation()
prs.slide_width = Inches(13.33)  # 16:9 Widescreen
prs.slide_height = Inches(7.5)

# Slide 1: Title
blank_layout = prs.slide_layouts[6]
slide = prs.slides.add_slide(blank_layout)

txBox = slide.shapes.add_textbox(Inches(1.0), Inches(2.0), Inches(11.33), Inches(2.0))
tf = txBox.text_frame
tf.word_wrap = True

p = tf.paragraphs[0]
p.text = "Executive Summary & Report"
p.font.size = Pt(40)
p.font.bold = True
p.font.color.rgb = RGBColor(15, 23, 42)

prs.save("output.pptx")
print("Successfully generated output.pptx")
```
