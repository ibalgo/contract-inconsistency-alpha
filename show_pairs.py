import sqlite3
import json

db = sqlite3.connect("alphaagent.db")
db.row_factory = sqlite3.Row

query = """
SELECT
    m1.venue_id       AS kalshi_id,
    m1.title          AS kalshi_title,
    m1.yes_price      AS kalshi_yes,
    m2.venue_id       AS poly_id,
    m2.title          AS poly_title,
    m2.yes_price      AS poly_yes,
    round(cp.similarity_score, 3) AS sim,
    cp.matching_basis AS basis
FROM candidate_pairs cp
JOIN markets m1 ON cp.market_a_id = m1.id
JOIN markets m2 ON cp.market_b_id = m2.id
ORDER BY cp.similarity_score DESC
LIMIT 10
"""

rows = db.execute(query).fetchall()

print(f"Top 10 candidate pairs by similarity\n{'=' * 80}")
for i, r in enumerate(rows, 1):
    basis = json.loads(r["basis"] or "[]")
    kalshi_yes = f"{r['kalshi_yes']:.3f}" if r["kalshi_yes"] is not None else "N/A"
    poly_yes   = f"{r['poly_yes']:.3f}"   if r["poly_yes"]   is not None else "N/A"
    spread     = abs((r["kalshi_yes"] or 0) - (r["poly_yes"] or 0))

    print(f"\n#{i}  similarity={r['sim']}  spread={spread:.3f}")
    print(f"  Kalshi  [{kalshi_yes}]  {r['kalshi_id']}")
    print(f"           {r['kalshi_title']}")
    print(f"  Poly    [{poly_yes}]  {r['poly_id']}")
    print(f"           {r['poly_title']}")
    print(f"  Basis:   {', '.join(basis)}")
