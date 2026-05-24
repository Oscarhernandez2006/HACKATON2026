# Lanza Chrome con CDP remoto habilitado para que el microservicio
# pueda conectarse y consultar ADRES usando tu sesión real (pasa el
# reCAPTCHA Enterprise invisible porque el bot opera como tú).
#
# Uso:
#   .\scripts\launch_chrome_adres.ps1
#
# Después:
#   1. En el Chrome que abre, navega a https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx
#   2. Haz UNA consulta cualquiera para calentar la sesión y resolver el captcha invisible
#   3. Deja Chrome abierto en segundo plano
#   4. Usa el dashboard normalmente — las consultas ADRES ahora pasarán por este Chrome

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profile = Join-Path $env:USERPROFILE "chrome-adres-profile"
$port = 9222

if (-not (Test-Path $chrome)) {
    Write-Host "❌ Chrome no encontrado en $chrome" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $profile)) { New-Item -ItemType Directory -Path $profile | Out-Null }

# Verificar si el puerto ya está en uso
$inUse = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue) -ne $null
if ($inUse) {
    Write-Host "⚠️  Puerto $port ya está en uso. Probablemente Chrome CDP ya está activo." -ForegroundColor Yellow
    Write-Host "    Si tienes problemas, cierra todas las ventanas de Chrome y vuelve a ejecutar." -ForegroundColor Yellow
    exit 0
}

Write-Host "🚀 Lanzando Chrome con CDP en puerto $port" -ForegroundColor Cyan
Write-Host "   Profile: $profile" -ForegroundColor Gray
Write-Host ""
Write-Host "📋 Próximos pasos:" -ForegroundColor Cyan
Write-Host "   1. En el Chrome que se abrirá, navega a:" -ForegroundColor White
Write-Host "      https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx" -ForegroundColor Yellow
Write-Host "   2. Haz UNA consulta cualquiera para calentar el captcha invisible" -ForegroundColor White
Write-Host "   3. Deja Chrome ABIERTO" -ForegroundColor White
Write-Host "   4. Vuelve al dashboard y prueba 'Validar afiliación' — ahora pasará por este Chrome real" -ForegroundColor White
Write-Host ""

Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=$port",
    "--user-data-dir=$profile",
    "--no-first-run",
    "--no-default-browser-check",
    "https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx"
)

Write-Host "✅ Chrome lanzado. Endpoint CDP: http://localhost:$port" -ForegroundColor Green
