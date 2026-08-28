# Agentic Storefront Pitch Data

## Framing A: Honest Upsell Comparison (Apples-to-Apples)
- **Scenarios:** 26 (where budget >= list price)
- **Methodology:** BOTH conditions must show conversion checked against the buyer's budget. Since budget >= list by construction, both convert 100%.
- **Fixed-Price AOV:** Rs. 365.00
- **Upsell Engine AOV:** Rs. 365.00
- **AOV Uplift:** 0.00%

## Framing B: Negotiation Converts Budget-Constrained Buyers
- **Scenarios:** 12 (where floor <= budget < list price)
- **Methodology:** Budget is explicitly truncated to a 100-paise boundary: `(floor + list) // 200 * 100`.
- **Fixed-Price Conversion:** 0/12 (0%) because list price always exceeds budget.
- **Agentic Negotiation Conversion:** 10/12 (83.3%). 2 walked away.

### Caveat
*Important note: These figures were calculated applying strict budget checks to both fixed-price and AI conditions identically. They do not rely on unconditional conversion assumptions.*

