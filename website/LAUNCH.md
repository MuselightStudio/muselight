# Launching muselight.studio

What's here:

| Path | What it is |
|---|---|
| `index.html` | Landing page |
| `download.html` | Windows app download |
| `app/` | The web app: Muselight Credits only, no own provider accounts |
| `legal/` | Terms, Privacy, Refunds, Acceptable Use, Cookies |
| `assets/`, `favicon.ico` | Styles and icons |

The site is plain static files, so hosting is free. The only thing that costs money to run is the Credits server (`muselight_cloud/`), at about $5 a month.

```
muselight.studio        → Cloudflare Pages (this folder)          free
api.muselight.studio    → Railway (muselight_cloud/server.py)     ~$5/month
sign-in                 → Supabase Auth (email, Google, X)        free up to 50,000 users
                          Telegram login (checked by the server)  free
payments                → Paddle (merchant of record)             ~5% + $0.50 per top-up
Windows app download    → GitHub Releases                         free
```

Do the steps in this order. Everything starts in **sandbox / test mode**; you switch to live at step 10.

---

## 1. Business basics (UK sole trader)

1. **Register for Self Assessment with HMRC** as self-employed. Do it by 5 October after the end of the tax year (5 April) in which you start trading: gov.uk/register-for-self-assessment. You get £1,000 a year of trading income tax-free (the "trading allowance"). Above that, you pay tax on profit.
2. **Pay the ICO data protection fee.** You store people's emails, so it's needed. It costs £40–52 a year (tier 1) at ico.org.uk/fee.
3. **VAT**: Paddle is the merchant of record. It sells to your customers and handles VAT and sales tax worldwide. You only register for UK VAT yourself if your own turnover (what Paddle pays you) passes £90,000.
4. **Keep records**: Paddle's payout reports, plus receipts for hosting and ads. A spreadsheet is enough to start.
5. **An address for the legal pages**: UK consumer law requires a geographic address on the site. If you don't want your home address public, use a virtual office address (about £5–15 a month).
6. A separate bank account for the business isn't legally required as a sole trader, but it makes tax time much easier.

Consider a **limited company** later, once profit passes roughly £30–50k a year or you want to protect your personal assets. An accountant can tell you when.

## 2. Fill in the placeholders

Search the whole `website` folder for these and replace them:

| Placeholder | Replace with |
|---|---|
| `[Your full legal name]` | Your name (as a sole trader, you are the business) |
| `[Your business address]` | Your address or virtual office |
| `[Date you publish this]` | The launch date |
| `YOUR-GITHUB-NAME` (in `download.html`) | Your GitHub username |

They're highlighted in green on the legal pages so you can spot any you miss. Read the legal pages through once. They're a solid start for a UK business, but they aren't advice from a solicitor.

## 3. Put the site on Cloudflare Pages

1. Create a free Cloudflare account.
2. Add `muselight.studio` as a site and pick the free plan. Cloudflare shows you two nameservers.
3. In Namecheap, go to Domain List → muselight.studio → Nameservers → **Custom DNS**, and paste the two Cloudflare nameservers. The change takes from minutes up to a day.
4. In Cloudflare, go to Workers & Pages → Create → Pages → **Upload assets**, and upload the `website` folder. (Alternatively, connect a GitHub repository so every push deploys.)
5. Under Custom domains, add `muselight.studio` and `www.muselight.studio`. HTTPS is automatic.

## 4. Email: support@muselight.studio

In Cloudflare, go to Email → **Email Routing** (free) and forward `support@` (and `privacy@` if you like) to your Gmail. To reply *from* support@, set up "Send mail as" in Gmail through a free SMTP relay, or pay for Zoho Mail or Google Workspace later.

## 5. Sign-in with Supabase

1. Create a free Supabase project with the region set to London.
2. Under Authentication → URL Configuration:
   - **Site URL**: `https://muselight.studio/app/`
   - **Redirect URLs**: `https://muselight.studio/app/` and `http://localhost:8099/app/` (the second is for testing).
3. Under Authentication → Providers:
   - **Email**: leave "Confirm email" on, and minimum password length 8.
   - **Google**:
     1. In Google Cloud Console → APIs & Services → Credentials, create an OAuth client of type "Web application".
     2. Add Supabase's callback URL (shown on the provider page) as an authorised redirect URI.
     3. Paste the client ID and secret into Supabase.
     4. On the OAuth consent screen, set the app name Muselight, the logo, and links to the privacy policy and terms.
   - **X / Twitter (OAuth 2.0)**: in the X developer portal, create an app, enable OAuth 2.0, add the Supabase callback URL, request the email permission, and paste the keys into Supabase.
4. Under Authentication → Emails → SMTP, the built-in mailer is limited to a few emails an hour. Before launch, connect a free Resend or Brevo account (send from `no-reply@muselight.studio`) so confirmation emails always arrive.
5. Under Project Settings → API, copy the **Project URL** and the **anon public key** for step 7.

## 6. Telegram login

1. In Telegram, message **@BotFather** → `/newbot` → name it e.g. *Muselight* with username *MuselightBot*. Copy the **bot token**.
2. Send BotFather `/setdomain`, pick the bot, and enter `muselight.studio`.

## 7. Deploy the Credits server on Railway

Follow `muselight_cloud/DEPLOY.md` (fal, Paddle and backups are explained there). In short:

1. Create a new Railway project and deploy it from a GitHub repository of this project, with Dockerfile path `muselight_cloud/Dockerfile`.
2. Add a **volume** mounted at `/data`. That's where every balance lives, so turn on backups.
3. Set the variables:

```
FAL_KEY=...                 FAL_ADMIN_KEY=...
PADDLE_API_KEY=...          PADDLE_CLIENT_TOKEN=...      PADDLE_WEBHOOK_SECRET=...
PADDLE_PRODUCT_ID=pro_...   PADDLE_ENV=sandbox           (live at step 10)
PUBLIC_URL=https://api.muselight.studio
ALLOWED_ORIGINS=https://muselight.studio,https://www.muselight.studio
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=...
TELEGRAM_BOT_TOKEN=...      TELEGRAM_BOT_NAME=MuselightBot
TERMS_URL=https://muselight.studio/legal/terms.html
ADMIN_TOKEN=<a long random string, for /v1/admin/report>
DATA_DIR=/data
```

4. In Railway, add the custom domain `api.muselight.studio`. In Cloudflare DNS, add the CNAME record that Railway gives you, with the proxy (orange cloud) **off** so Railway can issue the certificate.
5. Check that `https://api.muselight.studio/v1/config` shows your Supabase URL and bot name.

## 8. Paddle

1. Create Paddle **sandbox** and live accounts, then **Checkout → Website approval**: add `muselight.studio`. Paddle reviews the site, so the legal pages and placeholders must be complete, and the Refunds page must be visible.
2. Notifications: add the webhook `https://api.muselight.studio/v1/paddle` with the events `transaction.completed`, `adjustment.created` and `adjustment.updated`.
3. Do a test top-up in the sandbox with Paddle's test card `4242 4242 4242 4242`. Check the balance appears on the site.

## 9. Windows app

1. In `providers/muselight.py`, set `SERVER = "https://api.muselight.studio"` and rebuild the exe (`build_exe.bat`).
2. On GitHub, create a repository `muselight` → **Releases** → new release → attach `Muselight.exe`. The download link in `download.html` always points to the latest release.
3. Windows shows a SmartScreen warning for new unsigned apps, and `download.html` explains it. A code-signing certificate removes it, at about £60–300 a year, or about $10 a month through Azure Trusted Signing once you're eligible. Worth it once people are paying.

## 10. Go live

1. Set `PADDLE_ENV=live` and switch to the live Paddle keys on Railway.
2. Do one real £10 top-up yourself, then refund it from Paddle. This checks the refund path freezes and settles correctly.
3. Submit the site to Google Search Console (`sitemap.xml` is in this folder).

---

## Sign-in options you asked about

- **Email and password, Google, X, Telegram**: built and ready, and they appear on the sign-in page once steps 5–7 are done. Until they're set up, the page only offers "I have a sign-in code" (the code from the Windows app).
- **Sign in with ChatGPT**: OpenAI's program is in a limited rollout behind a waitlist (developers.openai.com/siwc/quickstart). Apply now; once you're accepted it can be added the same way as Google.
- **Sign in with Claude**: Anthropic doesn't offer a third-party sign-in, and using Claude subscription logins in other apps is against its terms. There's no legitimate way to add it today.

## Testing locally

```bash
python -m http.server 8099 --bind 127.0.0.1
```

Open http://localhost:8099/. The web app talks to a Credits server at `http://127.0.0.1:8080` when opened from localhost. You can point it at another server with `?api=https://...`.
