# Runs from the LakituAI uninstaller (elevated) to fully remove Ollama.
# It is safe to run even when Ollama is not installed: every step is guarded
# and missing items are simply skipped. Removes the service, running
# processes, program files, per-user app data, downloaded models and the PATH
# entries that the installer added.

$ErrorActionPreference = 'SilentlyContinue'

$ProgramsDir = Join-Path $env:LOCALAPPDATA 'Programs\Ollama'
$AppDataDir = Join-Path $env:LOCALAPPDATA 'Ollama'
$ModelsDir = Join-Path $env:USERPROFILE '.ollama'

# 1. Stop the Ollama server and any running app/tray process.
Get-Process -Name 'ollama' -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process -Name 'ollama app' -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue

# 2. Remove the background service if it exists.
if (Get-Service -Name 'ollama' -ErrorAction SilentlyContinue) {
    Stop-Service -Name 'ollama' -Force -ErrorAction SilentlyContinue
    sc.exe delete ollama | Out-Null
}

# 3. Run Ollama's own uninstaller when present, then clean up leftovers
#    (also covers the case where the uninstaller is already gone).
$Uninstaller = Join-Path $ProgramsDir 'uninstall.exe'
if (Test-Path $Uninstaller) {
    Start-Process -FilePath $Uninstaller -ArgumentList '/S' -Wait
}
Remove-Item -Recurse -Force $ProgramsDir -ErrorAction SilentlyContinue

# 4. Remove per-user app data and downloaded models.
Remove-Item -Recurse -Force $AppDataDir -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $ModelsDir -ErrorAction SilentlyContinue

# 5. Remove the Ollama PATH entries added by the installer.
function Remove-OllamaPathEntry([string]$Scope) {
    $Current = [Environment]::GetEnvironmentVariable('Path', $Scope)
    if (-not $Current) { return }
    $Filtered = ($Current -split ';') |
        Where-Object { $_ -and $_ -notlike '*\Programs\Ollama*' }
    $New = $Filtered -join ';'
    if ($New -ne $Current) {
        [Environment]::SetEnvironmentVariable('Path', $New, $Scope)
    }
}
Remove-OllamaPathEntry 'User'
Remove-OllamaPathEntry 'Machine'
