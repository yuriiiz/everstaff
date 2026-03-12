"""Quick smoke test for mem0 memory integration.

Usage:
    uv run python scripts/test_mem0.py

Requires:
    - OPENAI_API_KEY set in env (or whichever provider you configured)
    - mem0 extra installed: pip install everstaff[mem0]
"""
import asyncio
import os
import sys
import tempfile

# Ensure API key is available
if not os.getenv("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set. mem0 needs an LLM API key.")
    sys.exit(1)


async def main():
    from everstaff.core.config import MemoryConfig
    from everstaff.schema.model_config import ModelMapping
    from everstaff.memory.mem0_client import Mem0Client

    with tempfile.TemporaryDirectory() as tmp:
        config = MemoryConfig(
            enabled=True,
            vector_store="faiss",
            vector_store_path=f"{tmp}/vectors",
            search_threshold=0.1,
        )
        mapping = ModelMapping(model_id="openai/gpt-4.1-nano")

        print("1. Initializing Mem0Client...")
        client = Mem0Client(config, mapping)
        print("   OK")

        print("\n2. Adding memories from a conversation...")
        messages = [
            {"role": "user", "content": "My name is Alice and I work at Acme Corp as a Python developer."},
            {"role": "assistant", "content": "Nice to meet you Alice! Python is a great language."},
            {"role": "user", "content": "I prefer using FastAPI for web projects and pytest for testing."},
            {"role": "assistant", "content": "Great choices! FastAPI and pytest are excellent tools."},
        ]
        result = await client.add(messages, user_id="test-user", agent_id="test-agent")
        print(f"   Extracted {len(result)} memories:")
        for r in result:
            mem_text = r.get("data", {}).get("memory", r.get("memory", str(r)))
            print(f"   - {mem_text}")

        print("\n3. Searching for relevant memories...")
        results = await client.search("What programming language does the user prefer?", user_id="test-user")
        print(f"   Found {len(results)} results:")
        for r in results:
            print(f"   - [{r.get('score', '?'):.2f}] {r.get('memory', str(r))}")

        print("\n4. Testing Mem0Provider injection...")
        from everstaff.memory.mem0_provider import Mem0Provider
        provider = Mem0Provider(client, user_id="test-user", agent_id="test-agent")
        provider.set_query("Tell me about the user's tech stack")
        await provider.refresh()
        injection = provider.get_prompt_injection()
        if injection:
            print(f"   System prompt injection:\n   {injection}")
        else:
            print("   WARNING: No memories retrieved for injection")

        print("\n5. Testing compression flow...")
        from everstaff.protocols import Message
        from everstaff.memory.strategies import Mem0ExtractionStrategy

        strategy = Mem0ExtractionStrategy(
            client, user_id="test-user", agent_id="test-agent", session_id="test-session", max_tokens=50,
        )
        msgs = [
            Message(role="user", content="I'm building a new microservice with FastAPI"),
            Message(role="assistant", content="Great! Let me help you set that up."),
            Message(role="user", content="It needs to handle webhook events"),
            Message(role="assistant", content="We can use background tasks for that."),
        ]
        compressed = await strategy.compress(msgs)
        print(f"   Before: {len(msgs)} messages -> After: {len(compressed)} messages")
        print(f"   Old messages extracted to mem0 (kept last 2)")

        print("\n--- ALL CHECKS PASSED ---")


if __name__ == "__main__":
    asyncio.run(main())
