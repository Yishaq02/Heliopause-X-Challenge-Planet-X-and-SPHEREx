# Regenera docs/API_SPHEREx.pdf a partir de docs/API_SPHEREx.html
# Uso: powershell -ExecutionPolicy Bypass -File docs\build_pdf.ps1

$ErrorActionPreference = "Stop"

$docs = Split-Path -Parent $MyInvocation.MyCommand.Path
$html = Join-Path $docs "API_SPHEREx.html"
$pdf  = Join-Path $docs "API_SPHEREx.pdf"

if (-not (Test-Path -LiteralPath $html)) {
    throw "No se encontro el HTML fuente: $html"
}

$candidatos = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
)

$navegador = $candidatos | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $navegador) {
    throw "No se encontro Chrome ni Edge. Instala uno de los dos para generar el PDF."
}

$url = "file:///" + ($html -replace '\\', '/')

& $navegador --headless=new --disable-gpu --no-pdf-header-footer `
    --run-all-compositor-stages-before-draw --virtual-time-budget=4000 `
    --print-to-pdf="$pdf" "$url"

Start-Sleep -Seconds 1

if (-not (Test-Path -LiteralPath $pdf)) {
    throw "La conversion fallo: no se genero $pdf"
}

$info = Get-Item -LiteralPath $pdf
Write-Host ("PDF generado: {0} ({1:N0} bytes)" -f $info.FullName, $info.Length)
