
@test("Trainer safely aborts without writing to disk on ImportError")
def test_trainer_import_error_fallback_closed():
    from unittest.mock import patch, MagicMock
    import self_improving_trainer
    import pathlib
    import sys

    # Capture original file content and modification time
    prompt_path = pathlib.Path(self_improving_trainer.PROMPT_PATH)
    original_text = prompt_path.read_text(encoding="utf-8")

    # Mock the imports so it skips LLM calls and we can test the exception paths
    with patch("self_improving_trainer.MerchantAI") as mock_merchant:
        mock_merchant.return_value.floor_price = 1000
        mock_merchant.return_value.retail_price = 2000
        mock_merchant.return_value.system_prompt = "test"
        
        with patch("self_improving_trainer.run_simulation", return_value=[{"role": "merchant", "message": "hello", "proposed_price": 2000, "accepted": False, "walk_away": False, "bundle_offer": None}]):
            with patch("self_improving_trainer.evaluator.evaluate") as mock_eval:
                mock_res = MagicMock()
                mock_res.total_score = 10
                mock_res.scores = []
                mock_eval.return_value = mock_res
                
                with patch("self_improving_trainer.evaluator.rewrite_prompt", return_value="New Leaky Prompt"):
                    with patch.dict(sys.modules, {"agentic_storefront_guardrails": None}):
                        try:
                            orig_iters = self_improving_trainer.MAX_ITERATIONS
                            self_improving_trainer.MAX_ITERATIONS = 1
                            self_improving_trainer.main()
                        finally:
                            self_improving_trainer.MAX_ITERATIONS = orig_iters

    new_text = prompt_path.read_text(encoding="utf-8")
    assert original_text == new_text, "Prompt was modified despite ImportError!"

@test("Trainer safely aborts without writing to disk on unexpected Exception")
def test_trainer_general_exception_fallback_closed():
    from unittest.mock import patch, MagicMock
    import self_improving_trainer
    import pathlib

    # Capture original file content and modification time
    prompt_path = pathlib.Path(self_improving_trainer.PROMPT_PATH)
    original_text = prompt_path.read_text(encoding="utf-8")

    with patch("self_improving_trainer.MerchantAI") as mock_merchant:
        mock_merchant.return_value.floor_price = 1000
        mock_merchant.return_value.retail_price = 2000
        mock_merchant.return_value.system_prompt = "test"
        
        with patch("self_improving_trainer.run_simulation", return_value=[]):
            with patch("self_improving_trainer.evaluator.evaluate") as mock_eval:
                mock_res = MagicMock()
                mock_res.total_score = 10
                mock_res.scores = []
                mock_eval.return_value = mock_res
                
                with patch("self_improving_trainer.evaluator.rewrite_prompt", return_value="New Leaky Prompt"):
                    with patch("agentic_storefront_guardrails.prompt_versioning.PromptRegistry.propose_candidate", side_effect=Exception("Simulated general Exception")):
                        try:
                            orig_iters = self_improving_trainer.MAX_ITERATIONS
                            self_improving_trainer.MAX_ITERATIONS = 1
                            if hasattr(self_improving_trainer.main, '_prompt_registry'):
                                delattr(self_improving_trainer.main, '_prompt_registry')
                            self_improving_trainer.main()
                        finally:
                            self_improving_trainer.MAX_ITERATIONS = orig_iters

    new_text = prompt_path.read_text(encoding="utf-8")
    assert original_text == new_text, "Prompt was modified despite Exception!"

