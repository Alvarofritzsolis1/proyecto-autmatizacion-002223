# GALANT — OCR en Windows sin servidor de pago
# Ejecutar en PowerShell desde la carpeta raíz del repositorio:
# .\worker\iniciar_ocr_windows.ps1
# Configurar SUPABASE_URL y SUPABASE_SECRET_KEY en variables del entorno del
# equipo antes de ejecutar. Nunca pegar ni subir esas claves a GitHub.
param(
    [switch]$Once
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root
if (-not $env:SUPABASE_URL -or -not $env:SUPABASE_SECRET_KEY) {
    Write-Error "Falta SUPABASE_URL o SUPABASE_SECRET_KEY en las variables privadas de Windows. No copies claves al repositorio."
    exit 1
}
$python = Get-Command py -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "Instala Python 3.12 y habilita el comando 'py' antes de iniciar GALANT."
    exit 1
}
$tesseract = Get-Command tesseract -ErrorAction SilentlyContinue
if (-not $tesseract) {
    Write-Error "No encuentro Tesseract OCR en PATH. Instálalo y agrega su carpeta a PATH de Windows."
    exit 1
}
$venv = Join-Path $root ".venv"
$exe = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $exe)) {
    & py -3.12 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno Python 3.12" }
}
& $exe -m pip install -r (Join-Path $root "worker\requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Falló la instalación de dependencias Python" }
Write-Host "GALANT OCR — conectado al proyecto configurado. El equipo debe permanecer encendido para procesar archivos."
if ($Once) {
    & $exe worker\worker.py --once
} else {
    & $exe worker\worker.py
}
if ($LASTEXITCODE -ne 0) { throw "El trabajador OCR terminó con un error" }
