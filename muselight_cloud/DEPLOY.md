# Muselight Credits: going live

Muselight Credits lets people pay you once instead of opening an account with every provider. The app keeps working exactly as before for people who use their own keys; Credits is one more "provider" in the list, and the Cheapest switch still picks whichever is cheaper.

```
Muselight app ──► your Credits server ──► fal (your key, never in the app)
                     ▲
          Paddle ────┘ (webhook: payment completed / refunded / charged back)
```

## What it costs to start

| Item | Cost |
|---|---|
| Paddle (merchant of record: takes cards/PayPal, handles sales tax & VAT, refunds, chargebacks) | No monthly fee; about 5% + $0.50 per top-up |
| Hosting (Railway, Fly.io, Render or a small VPS) | ~$5–7 a month |
| Domain | ~$15 a year |
| fal credit float (fal is prepaid; Paddle pays you out on a schedule) | $50–100, turn on fal's auto top-up |

So under about $150 to start, and you never pay for a run before the user has paid you.

## 1. Before anything: check you're allowed

- **fal's terms**: confirm reselling fal-powered generation inside your own app is allowed (most API providers allow "applications built on the API", but read fal's Terms of Service and ask fal support if unsure).
- **Paddle approval**: Paddle reviews your business and your website before going live. The site needs your product and pricing, **Terms of Service, Privacy Policy and Refund Policy**. Set `TERMS_URL` to your terms page so people accept them when they create an account.
- You are now the provider: users' content goes through your account. The server forces fal's safety filter on where a model has one; your terms should ban illegal content and say you can close accounts.

## 2. Paddle (start in the sandbox)

1. Create a sandbox account at sandbox-vendors.paddle.com.
2. **Catalog → Products → New product**: "Muselight credits", tax category *Standard digital goods*. Copy its id (`pro_…`) → `PADDLE_PRODUCT_ID`. No price is needed: the server sends the amount with each top-up.
3. **Developer tools → Authentication**: create an API key → `PADDLE_API_KEY`, and a client-side token → `PADDLE_CLIENT_TOKEN`.
4. **Checkout → Checkout settings → Default payment link**: `https://YOUR-SERVER/pay` (live accounts must approve the domain first).
5. **Developer tools → Notifications → New destination**: URL `https://YOUR-SERVER/v1/paddle`, events `transaction.completed`, `adjustment.created`, `adjustment.updated`. Copy its secret key (`pdl_ntfset_…`) → `PADDLE_WEBHOOK_SECRET`.

When everything works, repeat in the live dashboard and set `PADDLE_ENV=live`.

## 3. fal

- `FAL_KEY`: a normal API key.
- `FAL_ADMIN_KEY`: an **admin** key. Strongly recommended: the server reads what fal really billed for each run, raises a model's price if it cost more than estimated, and shows your true margin in the report.
- Turn on auto top-up in fal's billing page so your balance never runs dry.

## 4. Deploy the server

Any host that runs a Docker image and gives it a **persistent volume** works. The volume matters: balances live in `/data/credits.db`.

Railway example: new project → deploy from this repository, Dockerfile path `muselight_cloud/Dockerfile` → add a volume mounted at `/data` → add the variables below → add your domain (e.g. `credits.yourdomain.com`).

| Variable | Value |
|---|---|
| `FAL_KEY`, `FAL_ADMIN_KEY` | from fal |
| `PADDLE_API_KEY`, `PADDLE_CLIENT_TOKEN`, `PADDLE_WEBHOOK_SECRET`, `PADDLE_PRODUCT_ID` | from Paddle |
| `PADDLE_ENV` | `sandbox`, later `live` |
| `PUBLIC_URL` | `https://credits.yourdomain.com` |
| `ADMIN_TOKEN` | a long random string (for the report) |
| `TERMS_URL` | your terms page |
| `MARKUP` | `0.10`: over the market price (fal's list price) |
| `MIN_MARGIN` | `0.25`: over your real cost, at least |
| `SOURCES` | optional, e.g. `fal,atlas,kling`: limit which sources are used (default: every one with a key set) |
| source keys | any of the keys in "Buying from the cheapest source" below |
| `MIN_TOPUP` / `MAX_TOPUP` | `10` / `500` |
| `NEW_ACCOUNT_DAYS` / `NEW_ACCOUNT_DAILY_TOPUP` | `7` / `100` (limits what a stolen card can do) |

On first start the server fetches fal's price list (about a minute) and refreshes it daily. Check `https://credits.yourdomain.com/health`.

**Backups**: copy `/data/credits.db` somewhere daily (most hosts offer volume snapshots). It is the record of what every user has paid for.

## 5. Point the app at it

In `providers/muselight.py` set `SERVER = "https://credits.yourdomain.com"`, rebuild the exe, and the **Credits** pill appears in the header. (To test without rebuilding, set the `MUSELIGHT_CLOUD_URL` environment variable.)

Test the whole loop in the sandbox with Paddle's test card `4242 4242 4242 4242`, any future date, any CVC.

## Buying from the cheapest source

The models on sale are fal's catalogue (what users see and the price they compare against), but each run is **bought wherever it's cheapest** among the sources this server has a key for. The app's price comparison finds the same model at each source and translates the settings; a source that can't take the run's settings faithfully is skipped, and if the chosen source fails, the run is done on fal instead at the price already quoted.

Add a source by setting its key on the server (restart, and its catalogue loads within a minute):

| Source | Key(s) |
|---|---|
| Atlas Cloud | `ATLASCLOUD_API_KEY` |
| WaveSpeedAI | `WAVESPEED_API_KEY` |
| Runware | `RUNWARE_API_KEY` |
| Replicate | `REPLICATE_API_TOKEN` |
| Kie.ai / PiAPI / Segmind | `KIE_API_KEY` / `PIAPI_API_KEY` / `SEGMIND_API_KEY` |
| DeepInfra / Together / SiliconFlow | `DEEPINFRA_API_KEY` / `TOGETHER_API_KEY` / `SILICONFLOW_API_KEY` |
| **Model makers, direct** | |
| Kling AI | `KLING_ACCESS_KEY` + `KLING_SECRET_KEY` |
| BytePlus (Seedream, Seedance) | `ARK_API_KEY` |
| Alibaba Model Studio (Wan) | `DASHSCOPE_API_KEY` |
| Google (Veo, Imagen, Gemini images) | `GEMINI_API_KEY` |
| OpenAI (GPT Image) / xAI (Grok Imagine) | `OPENAI_API_KEY` / `XAI_API_KEY` |
| Black Forest Labs (FLUX) / MiniMax (Hailuo) | `BFL_API_KEY` / `MINIMAX_API_KEY` |
| Luma / Runway / Ideogram / Recraft / Stability | `LUMAAI_API_KEY` / `RUNWAYML_API_SECRET` / `IDEOGRAM_API_KEY` / `RECRAFT_API_TOKEN` / `STABILITY_API_KEY` |

Each source is one more balance to keep topped up and one more set of terms to check for reselling. Start with fal + Atlas Cloud (cheaper than fal on about half the models they share, mostly video at around half price), and add others when the numbers below say so.

## Pricing: competitive and still profitable

Each run's price is the higher of:

- **the market price**: fal's list price + `MARKUP` (10%), so you're never far above what people would pay elsewhere, and
- **your cost + `MIN_MARGIN`** (25%), so a run never sells too close to cost.

Where you buy cheaper than fal, the market price wins and the difference is yours: FLUX schnell bought at Atlas for $0.02 sells for $0.055 (fal's $0.05 + 10%), keeping $0.035. Where fal is the cheapest source, you charge fal's price + 25%.

A $20 top-up: Paddle keeps about $1.50 (fees fall as a share on bigger top-ups); the user spends $20 of credit. If your sources average 85% of fal's price, that $20 costs you about $15.50 → **about $3–4 (15–20%) left** for hosting, ads and you. The more of your volume goes through cheaper sources, the more is left.

## When to go direct to the model maker

Going direct is just adding that maker's key above; the server then buys from it whenever it's cheapest. It's worth doing for one model when:

**monthly spend on that model × (aggregator price − direct price) > the cost of another account** (keeping a balance topped up, any minimum purchase, their sign-up checks, and lower rate limits on new accounts).

In practice: once a model reaches about **$500–1,000 a month** of your spend, check the maker's own API price. With about $25 of spending per active user a month and a third of it on your most popular video model, that's around **60–100 paying users**. Do it for your top two or three models, keep the aggregators as the fallback, and read each maker's terms on resale first.

## Making sure you don't lose money

- **Prepaid only.** No balance, no run. The price is quoted first and taken before the run starts; failed and cancelled runs are refunded automatically.
- **Self-correcting prices.** Each run's real cost is read (fal with the admin key; most other sources report it in their reply). A source model that cost more than estimated gets its future cost raised to match (the worst of its last 20 runs), so the quotes cover it.
- **Fraud brakes.** New accounts can top up at most `NEW_ACCOUNT_DAILY_TOPUP` a day for their first week; a chargeback takes the credit back and freezes the account.
- **Your weekly check.** `python server.py report` (or `GET /v1/admin/report` with `Authorization: Bearer ADMIN_TOKEN`) shows top-ups, Paddle fees, refunds and chargebacks, what runs were charged against fal's real cost, the margin, and **credit_owed_to_users** (money you've taken that users haven't spent yet: keep at least that much available).

## Ads budget rule of thumb

Only spend on ads what a customer earns you. If the average customer tops up $40 over their lifetime at an 18% margin, they're worth about $7; an ad channel that costs more than ~$7 per paying customer loses money. Start with free channels (TikTok/Instagram posts of what Muselight makes, Reddit, YouTube tutorials), then put a small fixed budget behind whatever converts.

## Support commands (run on the server)

- `python server.py report [days]`: the money report.
- `python server.py token <account id or email>`: a new sign-in code for someone who lost their PC (the email is the one they paid with).
- `python server.py credit <account id> <usd> <note>`: goodwill credit or a manual correction (negative to take back).
- `python server.py prices`: refresh fal's price list now.
