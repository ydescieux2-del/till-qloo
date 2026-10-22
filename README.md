# Till for Qloo: what fits your neighborhood, and can you afford it?

**Live demo:** https://till-production-20b7.up.railway.app (Chrome for the microphone; live Qloo Insights data)

> "Could my bakery run a Sunday brunch that fits this neighborhood, and can it afford it?"
>
> "Sunday brunch fits Highland Park's taste for casual, walkable, afternoon spots, and it's affordable but tight: your
> lowest cash point would drop from about 11.2 thousand to about 8 thousand dollars. It breaks even at roughly 34
> guests a week at 14 dollars each."
>
> "What could my bakery launch?" ... "Can I afford the kids' cookie class?"
>
> "Yes, comfortably: the kids' cookie class costs about 350 dollars to start and 133 a week, and your lowest cash
> point only drops from 11.2 thousand to 10.1 thousand dollars."

Small business owners make two bets every time they try something new: **will my neighborhood want it**, and
**will my cash survive it**. Till answers both in one conversation. **Qloo's taste graph** answers the first: which
places the local audience loves, what those places share, and what comparable spots charge. **Till's deterministic
cash engine** answers the second, running the idea's cost through a 13-week forecast of the owner's real books.

Till is an **MCP server** (spec 2025-11-25, Streamable HTTP) with a web client that has a microphone, speech
output, and an MCP Apps card host. Any MCP-capable assistant can use the tools.

## The judging test: why this doesn't work without Qloo

Without Qloo, an agent asked "what should my bakery launch?" can only guess from stereotypes, and any cost it
attaches is invented. In Till, every idea's **local fit** score is the share of neighborhood affinity (Qloo
`query.affinity` on places in that neighborhood, for that audience) carried by places tagged with the idea's
themes, and the **price per guest** comes from the median Qloo price level of comparable places nearby. Remove Qloo
and every fit score is 0, the price falls back to a generic default, and Till says it can't rank ideas rather
than guessing. That case is a unit test (`test_without_qloo_signal_nothing_is_recommended`).

## Tools

| Tool | Ask it | What happens |
|---|---|---|
| `neighborhood_taste` | "What does Highland Park love?" | Qloo Insights: places in the neighborhood ranked by affinity for the audience (age bands, optional audience ids), rolled up into the tastes they share |
| `launch_ideas` | "What could my bakery launch?" | Menu, product, and event ideas ranked 0 to 100 by local fit from the same Qloo signal |
| `price_the_idea` | "Can we afford the brunch?" | Qloo finds comparable places (for example `urn:tag:dining_options:place:brunch`) and their price level; the engine prices the idea and runs it through the 13-week forecast: comfortable, tight, or not yet, plus guests a week to break even |
| `morning_brief`, `cash_snapshot`, `cash_forecast`, `unusual_charges`, `review_charge`, `can_i_afford`, `spending_change`, `set_cash_alert`, `import_books`, `forget_business` | "How are we doing?" | Till's cash tools: balance, forecast, duplicate and jumped charges, affordability, memory across sessions |

**The language model never computes a number.** Money math lives in `till/engine.py` (stdlib only):
`price_per_cover`, `price_idea`, `affordability`, `forecast`. Taste aggregation and ranking live in
`till/taste.py`, also deterministic. The model's job is to pick tools, chain them, and talk.

## Run it (2 minutes)

```bash
git clone <this repo> till-qloo && cd till-qloo
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m till.server
# MCP endpoint  http://127.0.0.1:8765/mcp
# Demo page     http://127.0.0.1:8765/      (Chrome for the microphone)
```

Copy `env.example` to `.env` and set any of:

- `QLOO_API_KEY`: your Qloo hackathon key. Calls go to `https://hackathon.api.qloo.com/v2/insights` with the
  `X-Api-Key` header. **Without a key Till runs in mock mode**: a synthetic fixture shaped like the documented
  Insights response, with fictional places. Every taste card and spoken answer then says "demo data until the
  Qloo key is set", and the header shows the Qloo status.
- `ANTHROPIC_API_KEY`: Claude chooses and chains the tools. Without it, a built-in keyword router does.
- `ELEVENLABS_API_KEY`: spoken answers in an ElevenLabs voice instead of the browser voice.

Connect it to any MCP client, for example Claude Code:

```bash
claude mcp add --transport http till http://127.0.0.1:8765/mcp
```

Container: `docker build -t till-qloo . && docker run -p 8080:8080 -e QLOO_API_KEY=... till-qloo`.

### Deploy and live check

- `railway.json` (primary host, Dockerfile build, health check `/agent/status`) and `render.yaml` (fallback, Render
  free web service). `scripts/deploy_railway.sh` prints its plan; `--run` deploys.
- `.github/workflows/keepwarm.yml` pings the demo every 10 minutes once the repo variable `DEMO_URL` is set, so a
  free host that sleeps never shows a judge a cold start.
- `scripts/live_check.py` makes five real Qloo requests (taste, ideas, a location-filter control, comparable-place
  pricing, tag lookup) and flags any difference from the mock fixture. It prints only; nothing is saved.

### Tests

```bash
.venv/bin/python tests/test_engine.py                                  # cash engine
.venv/bin/python tests/test_qloo.py                                    # Qloo client + the three taste tools (no network)
.venv/bin/python tests/test_protocol.py http://127.0.0.1:8765/mcp      # raw JSON-RPC over Streamable HTTP, every tool
```

`test_qloo.py` also checks the exact live request (base URL, `X-Api-Key` header, query parameters) with a fake
HTTP layer, and that a live error is reported, never silently replaced by mock data.

## How it's built

```
voice / text ──> demo page = MCP client ──Streamable HTTP──> Till MCP server
                 │ agent loop (Claude, optional)              ├─ qloo.py    Insights client: live or mock, in-memory cache
                 └ MCP Apps host <── ui://till/card.html      ├─ taste.py   taste profile, idea ranking, local price level
                                                              ├─ engine.py  cash math: forecast, affordability, idea pricing
                                                              └─ memory.py  SQLite: alerts, reviews, briefs
```

Qloo requests used (all `GET /v2/insights`, `filter.type=urn:entity:place`):

- taste and ideas: `filter.location.query=<neighborhood>`, `signal.demographics.age`, optional
  `signal.demographics.audiences`, `take=30`
- comparable places for pricing: the same plus `filter.tags=<idea tag>`, `take=20`

## Data

All business data is synthetic (the fictional Sunrise Bakery, with planted problems). The mock Qloo fixture
(`till/fixtures/mock_insights_places.json`) is invented and labeled as such in every entity; it is not Qloo data.
Live Qloo responses are cached in server memory only and never written to disk or this repo, per the hackathon
data-use rules. Idea costs in `till/taste.py` are planning assumptions the owner can change.

Till is a tool for owners, not a licensed advisor, and it does not give tax or investment advice.

## License

MIT, Copyright (c) 2026 Descieux Digital LLC. See `LICENSE`.
