with open('test_full_integration.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('''@test("PriceGuard blocks below-floor price")
def test_pg_below():
    stack = get_guardrail_stack()
    try:
        stack.price_guard.authoritative_check("prod_001", 1.0)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass''', '''@test("PriceGuard blocks below-floor price")
def test_pg_below():
    stack = get_guardrail_stack()
    res = stack.price_guard.authoritative_check("prod_001", 1.0)
    assert res.allowed == False''')

c = c.replace('''@test("PriceGuard allows above-floor price")
def test_pg_above():
    stack = get_guardrail_stack()
    stack.price_guard.authoritative_check("prod_001", 20000.0)''', '''@test("PriceGuard allows above-floor price")
def test_pg_above():
    stack = get_guardrail_stack()
    res = stack.price_guard.authoritative_check("prod_001", 20000.0)
    assert res.allowed == True''')

c = c.replace('''@test("PriceGuard blocks zero price")
def test_pg_zero():
    stack = get_guardrail_stack()
    try:
        stack.price_guard.authoritative_check("prod_001", 0.0)
        assert False
    except ValueError:
        pass''', '''@test("PriceGuard blocks zero price")
def test_pg_zero():
    stack = get_guardrail_stack()
    res = stack.price_guard.authoritative_check("prod_001", 0.0)
    assert res.allowed == False''')

c = c.replace('''@test("PriceGuard blocks negative price")
def test_pg_negative():
    stack = get_guardrail_stack()
    try:
        stack.price_guard.authoritative_check("prod_001", -10.0)
        assert False
    except ValueError:
        pass''', '''@test("PriceGuard blocks negative price")
def test_pg_negative():
    stack = get_guardrail_stack()
    res = stack.price_guard.authoritative_check("prod_001", -10.0)
    assert res.allowed == False''')

with open('test_full_integration.py', 'w', encoding='utf-8') as f:
    f.write(c)
