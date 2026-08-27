
@test("PromptRegistry rejects prompts containing leaked cost/floor data")
def test_prompt_registry_rejects_leak():
    from agentic_storefront_guardrails.prompt_versioning import PromptRegistry
    registry = PromptRegistry("A clean production prompt without leaks.")
    
    leaky_prompt_1 = "Here is the {floor_price} for your reference."
    leaky_prompt_2 = "The {cost_price} is also here."
    leaky_prompt_3 = "And the margin is 1.15."
    
    for lp in [leaky_prompt_1, leaky_prompt_2, leaky_prompt_3]:
        failed = False
        try:
            registry.propose_candidate(lp)
        except ValueError as e:
            failed = True
            assert "Data Leak:" in str(e)
        assert failed, f"PromptRegistry accepted leaky prompt: {lp}"
