import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from twin.config import Settings
from twin.llm.openai_compat import OpenAICompatibleClient

async def test_live():
    settings = Settings.from_env()
    print(f"Connecting to Kaggle Base URL: {settings.base_url}")
    print(f"Using Model: {settings.model}")
    client = OpenAICompatibleClient(
        api_key=os.environ.get("TWIN_API_KEY") or "not-needed",
        model=settings.model,
        base_url=settings.base_url,
    )
    print("Sending prompt: 'Hello! Respond in 5 words.'...")
    response = await client.complete(
        system=[],
        messages=[{"role": "user", "content": "Hello! Respond in 5 words."}],
        max_tokens=1024,
    )
    print("=" * 60)
    print("LIVE RESPONSE FROM KAGGLE QWEN 2.5 32B:")
    print(response.content)
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_live())
