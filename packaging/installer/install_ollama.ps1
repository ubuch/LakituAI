# Runs from the Inno Setup installer with -NoProfile -ExecutionPolicy Bypass.
# Installs Ollama (if missing) and pulls the qwen3:4b chat model.
# Progress is streamed to $LogFile so the installer can display it; $DoneMarker
# and $ErrMarker signal completion to the installer (which polls for them).

param(
    [string]$LogFile     = "$env:TEMP\ollama_setup.log",
    [string]$DoneMarker = "$env:TEMP\ollama_done.ok",
    [string]$ErrMarker  = "$env:TEMP\ollama_error.err"
)

$ErrorActionPreference = 'Stop'
$model = 'qwen3:4b'

function Test-Ollama {
    return [bool](Get-Command ollama -ErrorAction SilentlyContinue)
}

function Install-Ollama {
    $setupPath = Join-Path $env:TEMP 'OllamaSetup.exe'
    Add-Content -Path $LogFile -Value "Downloading Ollama installer..."
    Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile $setupPath
    Add-Content -Path $LogFile -Value "Installing Ollama (silent)..."
    $proc = Start-Process -FilePath $setupPath -ArgumentList '/VERYSILENT', '/NORESTART' -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "Ollama installer failed with exit code $($proc.ExitCode)"
    }
    # Make ollama available in this session's PATH.
    $env:PATH = "$env:LOCALAPPDATA\Programs\Ollama;$env:ProgramFiles\Ollama;$env:PATH"
}

function Pull-Model {
    Add-Content -Path $LogFile -Value "Downloading chat model $model (this can take a while)..."
    & ollama pull $model 2>&1 | Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to pull model $model"
    }
}

try {
    Remove-Item -Path $DoneMarker, $ErrMarker -Force -ErrorAction SilentlyContinue
    if (-not (Test-Ollama)) {
        Install-Ollama
    } else {
        Add-Content -Path $LogFile -Value "Ollama already installed."
    }
    if (Test-Ollama) {
        Pull-Model
    }
    Add-Content -Path $LogFile -Value "Ollama setup complete."
    New-Item -ItemType File -Path $DoneMarker -Force | Out-Null
} catch {
    Add-Content -Path $LogFile -Value "ERROR: $($_.Exception.Message)"
    New-Item -ItemType File -Path $ErrMarker -Force | Out-Null
    exit 1
}
