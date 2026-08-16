# Runs from the Inno Setup installer with -NoProfile -ExecutionPolicy Bypass.
# Installs Ollama (if missing) and pulls the qwen3:4b chat model.
#
# Live-progress protocol with the installer:
#   $ProgressFile : "PCT|<0-100>" and "PHASE|<text>" lines, rewritten as the
#                   work advances so the installer can show a real progress
#                   bar with a percentage and a status message.
#   $PidFile      : this script's PID so the installer can kill it on cancel.
#   $LogFile      : plain-text log for debugging.
#   $DoneMarker   : created when everything finished successfully.
#   $ErrMarker    : created when something failed.

param(
    [string]$LogFile      = "$env:TEMP\ollama_setup.log",
    [string]$DoneMarker   = "$env:TEMP\ollama_done.ok",
    [string]$ErrMarker    = "$env:TEMP\ollama_error.err",
    [string]$ProgressFile = "$env:TEMP\ollama_progress.txt",
    [string]$PidFile      = "$env:TEMP\ollama_pid.txt"
)

$ErrorActionPreference = 'Stop'
$model = 'qwen3:4b'

# Make this script killable: the installer reads this file when the user
# clicks Cancel and terminates the process by PID.
Set-Content -Path $PidFile -Value $PID

function Write-ProgressState {
    param([int]$Pct, [string]$Phase)
    if ($Pct -gt 100) { $Pct = 100 }
    if ($Pct -lt 0) { $Pct = 0 }
    Set-Content -Path $ProgressFile -Value @("PCT|$Pct", "PHASE|$Phase")
    Add-Content -Path $LogFile -Value "[$Pct%] $Phase"
}

function Test-Ollama {
    return [bool](Get-Command ollama -ErrorAction SilentlyContinue)
}

function Download-File {
    param([string]$Url, [string]$Path)
    # Manual streamed download so the installer gets a real percentage.
    $req = [System.Net.HttpWebRequest]::Create($Url)
    $req.UserAgent = 'LakituAI-Installer/1.0'
    $req.Timeout = 30000
    $resp = $req.GetResponse()
    $in = $resp.GetResponseStream()
    $out = [System.IO.File]::Create($Path)
    $total = $resp.ContentLength
    $done = [long]0
    $lastPct = -1
    $buf = New-Object byte[] (64 * 1024)
    try {
        while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) {
            $out.Write($buf, 0, $n)
            $done += $n
            if ($total -gt 0) {
                $pct = [int](100.0 * $done / $total)
                if ($pct -ne $lastPct) {
                    $lastPct = $pct
                    $mb = [math]::Round($done / 1MB)
                    $mbTotal = [math]::Round($total / 1MB)
                    Write-ProgressState -Pct ([int]($pct * 0.30)) `
                        -Phase "Downloading the Ollama installer... $pct% ($mb MB / $mbTotal MB)"
                }
            }
        }
    } finally {
        $out.Close()
        $in.Close()
        $resp.Close()
    }
}

function Install-Ollama {
    $setupPath = Join-Path $env:TEMP 'OllamaSetup.exe'
    Download-File -Url 'https://ollama.com/download/OllamaSetup.exe' -Path $setupPath
    Write-ProgressState -Pct 30 -Phase 'Installing Ollama...'
    $proc = Start-Process -FilePath $setupPath -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru
    # The setup app can leave its window open after a successful install.
    # Wait with a generous timeout and only fail if Ollama is not actually
    # present afterwards, so a stuck window never hangs the installer forever.
    if (-not $proc.WaitForExit(10 * 60 * 1000)) {
        $proc.Kill()
        if (-not (Test-Ollama)) {
            throw 'Ollama installer did not finish within 10 minutes.'
        }
    } elseif ($proc.ExitCode -ne 0) {
        throw "Ollama installer failed with exit code $($proc.ExitCode)"
    }
    # Make ollama available in this session's PATH.
    $env:PATH = "$env:LOCALAPPDATA\Programs\Ollama;$env:ProgramFiles\Ollama;$env:PATH"
}

function Wait-OllamaServer {
    # First start can be slow (model registry init); give it up to ~3 minutes.
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/version' -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) {
                return $true
            }
        } catch { }
        Start-Sleep -Milliseconds 1000
    }
    return $false
}

function Pull-ModelViaApi {
    # Streams the pull progress from the local Ollama API (newline-delimited
    # JSON) so the installer can show a real percentage of the model download.
    # The API reports each model layer separately (digest -> total/completed),
    # so bytes are accumulated across layers to keep the overall progress
    # monotonic instead of resetting for every layer.
    $body = @{ model = $model; stream = $true } | ConvertTo-Json -Compress
    $req = [System.Net.HttpWebRequest]::Create('http://127.0.0.1:11434/api/pull')
    $req.Method = 'POST'
    $req.ContentType = 'application/json'
    $req.Timeout = 600000
    $req.ReadWriteTimeout = 300000
    $data = [System.Text.Encoding]::UTF8.GetBytes($body)
    $req.ContentLength = $data.Length
    $rs = $req.GetRequestStream()
    $rs.Write($data, 0, $data.Length)
    $rs.Close()
    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
    $gotSuccess = $false
    $accTotal = [long]0
    $accDone = [long]0
    $curTotal = [long]0
    $curDone = [long]0
    $lastPct = -1
    try {
        while (($line = $reader.ReadLine()) -ne $null) {
            $obj = $line | ConvertFrom-Json -ErrorAction SilentlyContinue
            if (-not $obj) { continue }
            if ($obj.status -eq 'pulling' -and $obj.total -gt 0) {
                if ($obj.total -ne $curTotal) {
                    # A new layer started: bank the finished layer's bytes.
                    $accTotal += $curTotal
                    $accDone += $curDone
                    $curTotal = [long]$obj.total
                }
                $curDone = [long]$obj.completed
                $pct = [int](100.0 * ($accDone + $curDone) / ($accTotal + $curTotal))
                if ($pct -gt $lastPct) {
                    $lastPct = $pct
                    Write-ProgressState -Pct (40 + [int]($pct * 0.60)) `
                        -Phase "Downloading the chat model ($model)... $pct%"
                }
            } elseif ($obj.status -eq 'success') {
                $gotSuccess = $true
            } elseif ($obj.status -eq 'error') {
                throw "Ollama model pull failed: $($obj.error)"
            }
        }
    } finally {
        $reader.Close()
        $resp.Close()
    }
    if (-not $gotSuccess) {
        throw "Failed to pull model $model"
    }
}

function Pull-Model {
    Write-ProgressState -Pct 40 -Phase 'Starting the Ollama server...'
    if (-not (Wait-OllamaServer)) {
        # The installer normally auto-starts the tray app; if the server is not
        # up yet, start it explicitly before pulling the model.
        Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
        if (-not (Wait-OllamaServer)) {
            throw 'The Ollama server did not start, so the chat model could not be downloaded.'
        }
    }
    Pull-ModelViaApi
    Write-ProgressState -Pct 100 -Phase 'Done.'
}

try {
    Remove-Item -Path $DoneMarker, $ErrMarker -Force -ErrorAction SilentlyContinue
    if (-not (Test-Ollama)) {
        Write-ProgressState -Pct 0 -Phase 'Starting...'
        Install-Ollama
    } else {
        Add-Content -Path $LogFile -Value 'Ollama already installed.'
        Write-ProgressState -Pct 35 -Phase 'Ollama already installed.'
    }
    if (Test-Ollama) {
        Pull-Model
    }
    Add-Content -Path $LogFile -Value 'Ollama setup complete.'
    New-Item -ItemType File -Path $DoneMarker -Force | Out-Null
} catch {
    Add-Content -Path $LogFile -Value "ERROR: $($_.Exception.Message)"
    New-Item -ItemType File -Path $ErrMarker -Force | Out-Null
    exit 1
}
