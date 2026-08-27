import time
import threading
from agentic_storefront_guardrails.inventory_lock import InventoryManager

def test_inventory_concurrent_race():
    inv = InventoryManager()
    inv.set_stock("TEST", 10)
    
    success_count = 0
    fail_count = 0
    
    # Barrier for 5 threads
    barrier = threading.Barrier(5)
    
    def worker():
        nonlocal success_count, fail_count
        barrier.wait() # Ensure all threads hit reserve exactly simultaneously
        try:
            inv.reserve("TEST", "neg", quantity=3)
            with threading.Lock():
                success_count += 1
        except RuntimeError:
            with threading.Lock():
                fail_count += 1

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    
    assert success_count == 3, f"Expected 3 successes, got {success_count}"
    assert fail_count == 2, f"Expected 2 failures, got {fail_count}"
    assert inv.available("TEST") == 1
    
    print("[PASS] True concurrent race condition (via Barrier) handled correctly")

if __name__ == "__main__":
    test_inventory_concurrent_race()
