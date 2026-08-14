"""Persona Extraction & Behavioral Analysis Engine.

This engine reads raw unstructured data (emails, chat logs, code reviews) from
the `sample_data/` folder and performs a deep psychological analysis to build
an automated Digital Twin `persona.json` file.
"""

import os
import glob
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Load the main project's .env file
load_dotenv(Path(__file__).parent.parent / ".env")

SYSTEM_PROMPT = """You are a master psychological profiler and behavioral analyst for an AI systems company.
Your job is to read raw data (chats, emails, code) from a human subject and build a highly accurate "Digital Twin" persona.

You must deeply analyze the subject's:
1. TONE & EMOTION: Are they aggressive, impatient, sarcastic, polite, or stoic? How do they react to failure or stress? (e.g., Anger triggers, situational responses).
2. FORMATTING HABITS: Do they use proper capitalization? Punctuation? Do they make specific typos? Do they use emojis or shorthand (e.g., "u", "pls", "wbu")?
3. DECISION MAKING: What do they prioritize? (Speed, security, cost, aesthetics?)
4. COMMUNICATION STYLE & IDENTITY: When asked 'who are you?', the twin MUST identify as '[Name]++, the Digital Twin of [Name]'. NEVER claim to be Claude, ChatGPT, Anthropic, or OpenAI.

You must output a strictly valid JSON object representing their Persona. 
DO NOT output any markdown blocks (no ```json), ONLY the raw JSON object.

The JSON MUST follow this exact schema:
{
    "name": "Digital Twin",
    "summary": "A 2-3 sentence deep psychological summary of how this person behaves.",
    "instructions": [
        "Rule 1 defining their exact formatting/typo style",
        "Rule 2 defining their emotional/anger triggers",
        "Rule 3: When asked 'who are you?', state 'I am [Name]++, the Digital Twin of [Name]'. Never say you are an AI assistant from Anthropic/OpenAI.",
        "Rule 4 defining what they prioritize"
    ],
    "samples": [
        {"context": "casual banter", "text": "exact verbatim sample message from input"},
        {"context": "technical inquiry", "text": "another verbatim sample message from input"}
    ]
}
"""

async def run_analyzer():
    print("=" * 65)
    print("BEHAVIORAL ANALYZER ENGINE")
    print("=" * 65)
    
    # 1. Read all sample data
    data_dir = Path(__file__).parent / "sample_data"
    files = glob.glob(str(data_dir / "*.txt"))
    
    if not files:
        print("X No sample data found! Please put some .txt files in analyzer_engine/sample_data/")
        return
        
    print(f"Found {len(files)} raw data files. Ingesting...")
    
    combined_data = ""
    for f in files:
        with open(f, "r", encoding="utf-8") as file:
            combined_data += f"\n--- Document: {os.path.basename(f)} ---\n"
            combined_data += file.read() + "\n"
            
    print(f"Total raw data ingested: {len(combined_data)} characters.")
    print("Analyzing psychological profile and behavioral triggers...")
    
    # 2. Call the LLM
    api_key = os.environ.get("TWIN_API_KEY")
    base_url = os.environ.get("TWIN_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("TWIN_ANALYSIS_MODEL") or os.environ.get("TWIN_MODEL", "gpt-4o")
    
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    
    user_prompt = f"Analyze the following raw data from the subject and generate their JSON persona profile:\n\n{combined_data}"
    
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2, # Low temperature for analytical precision
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Clean up markdown if the AI mistakenly included it
        if result_text.startswith("```json"):
            result_text = result_text[7:-3].strip()
        elif result_text.startswith("```"):
            result_text = result_text[3:-3].strip()
            
        # Parse to ensure it's valid JSON
        persona_json = json.loads(result_text)
        
        # 3. Save the output
        output_path = Path(__file__).parent / "output_persona.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(persona_json, f, indent=4)
            
        print("\nANALYSIS COMPLETE!")
        print(f"Digital Twin Persona saved to: {output_path}")
        print("\n--- Profile Summary ---")
        print(persona_json.get("summary", ""))
        
    except Exception as e:
        print(f"\nAnalysis Failed: {e}")

if __name__ == "__main__":
    asyncio.run(run_analyzer())
