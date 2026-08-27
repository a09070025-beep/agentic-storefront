with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('''@test("PriceGuard blocks below-floor price")
def test_pg_below():
    stack = get_guardrail_stack()
    assert stack.price_guard.authoritative_check("prod_001", 1.0) == False''', '''@test("PriceGuard blocks below-floor price")
def test_pg_below():
    stack = get_guardrail_stack()
    try:
        stack.price_guard.authoritative_check("prod_001", 1.0)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass''')

c = c.replace('''@test("PriceGuard allows above-floor price")
def test_pg_above():
    stack = get_guardrail_stack()
    # prod_001 floor is probably around 17000
    assert stack.price_guard.authoritative_check("prod_001", 20000.0) == True''', '''@test("PriceGuard allows above-floor price")
def test_pg_above():
    stack = get_guardrail_stack()
    stack.price_guard.authoritative_check("prod_001", 20000.0)''')

c = c.replace('''@test("PriceGuard blocks zero price")
def test_pg_zero():
    stack = get_guardrail_stack()
    assert stack.price_guard.authoritative_check("prod_001", 0.0) == False''', '''@test("PriceGuard blocks zero price")
def test_pg_zero():
    stack = get_guardrail_stack()
    try:
        stack.price_guard.authoritative_check("prod_001", 0.0)
        assert False
    except ValueError:
        pass''')

c = c.replace('''@test("PriceGuard blocks negative price")
def test_pg_negative():
    stack = get_guardrail_stack()
    assert stack.price_guard.authoritative_check("prod_001", -10.0) == False''', '''@test("PriceGuard blocks negative price")
def test_pg_negative():
    stack = get_guardrail_stack()
    try:
        stack.price_guard.authoritative_check("prod_001", -10.0)
        assert False
    except ValueError:
        pass''')

c = c.replace('stack.price_guard.check_price("prod_001", 10.0)', 'stack.price_guard.check_price_tool("prod_001", 10.0)')

with open('test_full_integration.py', 'w', encoding='utf-8') as f:
    f.write(c)
