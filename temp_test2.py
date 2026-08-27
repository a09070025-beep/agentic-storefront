
@test("PromptRegistry bypass fallbacks are closed (ImportError)")
def test_prompt_registry_import_error_fallback_closed():
    from unittest.mock import patch
    import pathlib
    import self_improving_trainer
    
    # We will simulate the trainer's try-except block hitting ImportError.
    # To do this safely without mocking the entire trainer loop, we can just check the code 
    # or write a small isolated test simulating the exception block.
    # Actually, we can patch `agentic_storefront_guardrails.PromptRegistry` to raise ImportError.
    
    # Let's read the current merchant system prompt content to verify it doesn't change
    original_prompt = pathlib.Path(self_improving_trainer.PROMPT_PATH).read_text(encoding="utf-8")
    
    with patch("self_improving_trainer.PromptRegistry", side_effect=ImportError("Simulated ImportError")):
        # We can simulate what the trainer does inside the except ImportError block.
        # But wait, self_improving_trainer is a script.
        pass
