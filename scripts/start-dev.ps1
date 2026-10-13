param([string]$JavaHome = '')
$ErrorActionPreference = 'Stop'
$launchCreated = $false
$launchMutex = [Threading.Mutex]::new($true, 'Local\MaxCraftDevLauncher', [ref]$launchCreated)
if (-not $launchCreated) { $launchMutex.Dispose(); throw 'MaxCraft Minecraft is already starting or running.' }
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not $JavaHome) {
    $candidate = Get-ChildItem (Join-Path $projectRoot '.runtime/jdk25') -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($candidate) { $JavaHome = $candidate.FullName } elseif ($env:JAVA_HOME) { $JavaHome = $env:JAVA_HOME }
}
if (-not $JavaHome -or -not (Test-Path (Join-Path $JavaHome 'bin/java.exe'))) {
    throw 'JDK 25 is required. Run with -JavaHome C:\path\to\jdk-25 or install into .runtime/jdk25.'
}
$env:JAVA_HOME = $JavaHome
$env:MAXCRAFT_ROOT = $projectRoot
$env:SKYCRAFT_USERNAME = 'MaxCrafter'
$env:GRADLE_USER_HOME = Join-Path $projectRoot '.runtime/gradle'
$env:PATH = (Join-Path $JavaHome 'bin') + ';' + $env:PATH
# Java ignores the Windows user proxy used by browsers/PowerShell. Apply only
# an existing loopback proxy, without copying credentials or changing settings.
$proxySettings = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
if ($proxySettings.ProxyEnable -and $proxySettings.ProxyServer -match '^(?:http://)?(127\.0\.0\.1|localhost):(\d+)$') {
    $proxyHostName = $Matches[1]
    $proxyPortNumber = $Matches[2]
    $env:JAVA_TOOL_OPTIONS = "$env:JAVA_TOOL_OPTIONS -Dhttp.proxyHost=$proxyHostName -Dhttp.proxyPort=$proxyPortNumber -Dhttps.proxyHost=$proxyHostName -Dhttps.proxyPort=$proxyPortNumber"
}
& python (Join-Path $PSScriptRoot 'prepare-dev.py')
if ($LASTEXITCODE -ne 0) { throw 'Backend preparation failed' }
Push-Location (Join-Path $projectRoot '.runtime/SkyCraft/fabric')
try {
    & .\gradlew.bat --no-daemon --console=plain --init-script (Join-Path $PSScriptRoot 'maxcraft.gradle') runClient
    if ($LASTEXITCODE -ne 0) { throw "Minecraft backend exited with code $LASTEXITCODE" }
} finally { Pop-Location; $launchMutex.ReleaseMutex(); $launchMutex.Dispose() }

