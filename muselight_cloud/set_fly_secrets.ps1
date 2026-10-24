# Asks for each secret with hidden typing and stores it on Fly.io (nothing is saved on this PC). Safe to run again:
# press Enter to skip a key (one already on Fly is kept). Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File .\muselight_cloud\set_fly_secrets.ps1
$fly = Join-Path $PSScriptRoot "..\.flyctl\flyctl.exe"
$have = @(& $fly secrets list --app muselight-api --json | ConvertFrom-Json | ForEach-Object { if ($_.Name) { $_.Name } else { $_.name } })
$asks = @(
  "Muselight itself",
  @("PADDLE_API_KEY",        "Paddle sandbox API key (Developer tools > Authentication > API keys)"),
  @("PADDLE_CLIENT_TOKEN",   "Paddle sandbox client-side token (same page)"),
  @("PADDLE_WEBHOOK_SECRET", "Paddle webhook secret (Developer tools > Notifications > ... > Edit > Secret key)"),
  @("SUPABASE_ANON_KEY",     "Supabase anon / publishable key (Project settings > API keys)"),
  @("TELEGRAM_BOT_TOKEN",    "Telegram bot token from @BotFather"),
  @("FAL_KEY",               "fal.ai key (fal.ai/dashboard/keys)"),
  @("FAL_ADMIN_KEY",         "fal.ai ADMIN key, so the server sees what each run really cost"),
  "Suppliers to buy runs from: the more you add, the closer your prices sit to the market's middle",
  @("ATLASCLOUD_API_KEY",    "Atlas Cloud (atlascloud.ai)"),
  @("WAVESPEED_API_KEY",     "WaveSpeedAI (wavespeed.ai)"),
  @("RUNWARE_API_KEY",       "Runware (runware.ai)"),
  @("DEEPINFRA_API_KEY",     "DeepInfra (deepinfra.com)"),
  @("SEGMIND_API_KEY",       "Segmind (segmind.com)"),
  @("REPLICATE_API_TOKEN",   "Replicate (replicate.com)"),
  @("KIE_API_KEY",           "Kie.ai (kie.ai)"),
  @("PIAPI_API_KEY",         "PiAPI (piapi.ai)"),
  "Model makers direct: worth it once you spend roughly `$500-1,000 a month on one of their models",
  @("BFL_API_KEY",           "Black Forest Labs, FLUX (bfl.ai)"),
  @("KLING_ACCESS_KEY",      "Kling access key (klingai.com)"),
  @("KLING_SECRET_KEY",      "Kling secret key"),
  @("MINIMAX_API_KEY",       "MiniMax, Hailuo (minimax.io)"),
  @("ARK_API_KEY",           "BytePlus ModelArk, Seedance and Seedream (byteplus.com)"),
  @("DASHSCOPE_API_KEY",     "Alibaba DashScope, Wan and Qwen (alibabacloud.com)"),
  @("GEMINI_API_KEY",        "Google, Veo and Imagen (aistudio.google.com)"),
  @("OPENAI_API_KEY",        "OpenAI, GPT Image (platform.openai.com)"),
  @("XAI_API_KEY",           "xAI, Grok Imagine (console.x.ai)"),
  @("LUMAAI_API_KEY",        "Luma (lumalabs.ai)"),
  @("RUNWAYML_API_SECRET",   "Runway (dev.runwayml.com)"),
  @("IDEOGRAM_API_KEY",      "Ideogram (ideogram.ai)"),
  @("RECRAFT_API_TOKEN",     "Recraft (recraft.ai)"),
  @("STABILITY_API_KEY",     "Stability AI (platform.stability.ai)")
)
Write-Host "Press Enter to skip any key." -ForegroundColor Cyan
$set = @()
foreach ($a in $asks) {
  if ($a -is [string]) { Write-Host "`n$a" -ForegroundColor Cyan; continue }
  $kept = if ($have -contains $a[0]) { " [on Fly already: Enter keeps it]" } else { "" }
  $s = Read-Host -AsSecureString "$($a[1])$kept"
  $v = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
  if ($v) { $set += "$($a[0])=$v" }
}
$bot = Read-Host "`nTelegram bot username, e.g. MuselightBot (Enter to skip)"
if ($bot) { $set += "TELEGRAM_BOT_NAME=$bot" }
$admin = $null
if (-not ($have -contains "ADMIN_TOKEN")) {
  $admin = -join ((1..40) | ForEach-Object { [char[]]"abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789" | Get-Random })
  $set += "ADMIN_TOKEN=$admin"
}
if (-not (($set -match "^FAL_KEY=") -or ($have -contains "FAL_KEY"))) { Write-Host "The fal.ai key is required; nothing was saved." -ForegroundColor Red; exit 1 }
if (-not $set) { Write-Host "Nothing new to save."; exit 0 }
& $fly secrets set --app muselight-api --stage @set
if ($LASTEXITCODE -eq 0) {
  Write-Host "`nSaved $($set.Count) secrets on Fly.io." -ForegroundColor Green
  if ($admin) { Write-Host "Your admin token (for the earnings report), keep it in your password manager: $admin" }
}
