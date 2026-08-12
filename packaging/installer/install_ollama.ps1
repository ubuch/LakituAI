# Runs from the Inno Setup installer with -NoProfile -ExecutionPolicy Bypass.
# Installs Ollama (if missing) and pulls the qwen3:4b chat model.

$ErrorActionPreference = 'Stop'
$model = 'qwen3:4b'

function Test-Ollama {
    return [bool](Get-Command ollama -ErrorAction SilentlyContinue)
}

function Install-Ollama {
    $setupPath = Join-Path $env:TEMP 'OllamaSetup.exe'
    Write-Output "Downloading Ollama installer..."
    Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile $setupPath
    Write-Output "Installing Ollama (silent)..."
    $proc = Start-Process -FilePath $setupPath -ArgumentList '/VERYSILENT', '/NORESTART' -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "Ollama installer failed with exit code $($proc.ExitCode)"
    }
    # Add Ollama to PATH for this session if it is not already there.
    $env:PATH = "$env:LOCALAPPDATA\Programs\Ollama;" + $env:PATH
    $env:PATH = "$env:ProgramFiles\Ollama;" + $env:PATH
}

function Pull-Model {
    Write-Output "Downloading chat model $model (this can take a while)..."
    & ollama pull $model
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to pull model $model"
    }
}

try {
    if (-not (Test-Ollama)) {
        Install-Ollama
    } else {
        Write-Output "Ollama already installed."
    }
    if (Test-Ollama) {
        Pull-Model
    }
    Write-Output "Ollama setup complete."
} catch {
    Write-Output "WARN: $($_.Exception.Message)"
    exit 1
}