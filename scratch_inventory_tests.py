import time
import threading
from agentic_storefront_guardrails.inventory_lock import InventoryManager

def test_inventory_over_quantity():
    inv = InventoryManager()
    inv.set_stock("TEST", 5)
    
    # Reserve 3
    inv.reserve("TEST", "neg1", quantity=3)
    
    # Try to reserve 3 more (should fail)
    try:
        inv.reserve("TEST", "neg2", quantity=3)
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "No stock available" in str(e)
        
    print("[PASS] Over-quantity correctly rejected")

def test_inventory_concurrent_race():
    inv = InventoryManager()
    inv.set_stock("TEST", 10)
    
    success_count = 0
    fail_count = 0
    
    def worker():
        nonlocal success_count, fail_count
        try:
            inv.reserve("TEST", "neg", quantity=3)
            success_count += 1
        except RuntimeError:
            fail_count += 1

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    
    # 5 threads * 3 qty = 15. Only 10 available.
    # Exactly 3 threads should succeed (9 items), 2 should fail.
    assert success_count == 3, f"Expected 3 successes, got {success_count}"
    assert fail_count == 2, f"Expected 2 failures, got {fail_count}"
    assert inv.available("TEST") == 1
    
    print("[PASS] Concurrent race conditions handled correctly")

def test_inventory_ttl_expiry():
    inv = InventoryManager()
    inv.set_stock("TEST", 5)
    
    # Reserve with 1 second TTL
    rid = inv.reserve("TEST", "neg1", quantity=3, ttl_seconds=1)
    assert inv.available("TEST") == 2
    
    # Wait for expiry
    time.sleep(1.1)
    
    # Any action that triggers _expire_locked (like checking available)
    assert inv.available("TEST") == 5, "Stock was not released after TTL expiry"
    
    print("[PASS] TTL expiry correctly releases full quantity")

if __name__ == "__main__":
    test_inventory_over_quantity()
    test_inventory_concurrent_race()
    test_inventory_ttl_expiry()
