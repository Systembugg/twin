from twin.llm.openai_compat import to_content_blocks

sample_text = '<function>ReadFile{"path":"aalu"}</function>'
blocks = to_content_blocks(sample_text, [])
print("BLOCKS PRODUCED:")
for b in blocks:
    print(b)
