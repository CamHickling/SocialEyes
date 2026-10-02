<#
.SYNOPSIS
  Installs a project-local toolchain into .toolchain\ (nothing system-wide):
    .toolchain\env          conda env: Python analysis stack, JDK 17, R + lme4
    .toolchain\android-sdk  Android SDK (command-line tools, platform, build tools)

.DESCRIPTION
  Requires conda (Miniforge/Anaconda) on PATH. Safe to re-run: each step is
  skipped if already done. Running sdkmanager accepts the Android SDK licences
  on your behalf (they are printed to the console).

  If you prefer Android Studio, you can skip the SDK part (-SkipAndroid) and
  open android\ in Android Studio instead.
#>
param(
  [switch]$SkipAndroid,
  [switch]$SkipConda
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Tool = Join-Path $Root '.toolchain'
New-Item -ItemType Directory -Force $Tool | Out-Null

# Pinned so every lab builds the same thing.
$CmdlineToolsUrl = 'https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip'
$SdkPackages = @('platform-tools', 'platforms;android-35', 'build-tools;35.0.0')

if (-not $SkipConda) {
  $EnvDir = Join-Path $Tool 'env'
  if (Test-Path (Join-Path $EnvDir 'python.exe')) {
    Write-Host "[conda] env exists, updating: $EnvDir"
    conda env update -p $EnvDir -f (Join-Path $Root 'environment.yml') --prune
  } else {
    Write-Host "[conda] creating env: $EnvDir"
    conda env create -p $EnvDir -f (Join-Path $Root 'environment.yml')
  }
  if ($LASTEXITCODE -ne 0) { throw "conda env create/update failed" }
}

if (-not $SkipAndroid) {
  $Sdk = Join-Path $Tool 'android-sdk'
  $Latest = Join-Path $Sdk 'cmdline-tools\latest'
  if (-not (Test-Path (Join-Path $Latest 'bin\sdkmanager.bat'))) {
    Write-Host "[android] downloading command-line tools"
    $Zip = Join-Path $Tool 'cmdline-tools.zip'
    Invoke-WebRequest -Uri $CmdlineToolsUrl -OutFile $Zip -UseBasicParsing
    $Tmp = Join-Path $Tool 'cmdline-tools-tmp'
    if (Test-Path $Tmp) { Remove-Item -Recurse -Force $Tmp }
    Expand-Archive -Path $Zip -DestinationPath $Tmp
    New-Item -ItemType Directory -Force (Split-Path $Latest) | Out-Null
    Move-Item (Join-Path $Tmp 'cmdline-tools') $Latest
    Remove-Item -Recurse -Force $Tmp, $Zip
  }

  # sdkmanager needs Java; use the JDK from the conda env.
  $Jdk = Join-Path $Tool 'env\Library'
  if (Test-Path (Join-Path $Jdk 'bin\java.exe')) { $env:JAVA_HOME = $Jdk }
  if (-not $env:JAVA_HOME) { throw "No JDK found. Run without -SkipConda or set JAVA_HOME to a JDK 17." }

  $SdkManager = Join-Path $Latest 'bin\sdkmanager.bat'
  Write-Host "[android] accepting licences and installing: $($SdkPackages -join ', ')"
  $yes = ('y' + [Environment]::NewLine) * 50
  $yes | & $SdkManager "--sdk_root=$Sdk" --licenses | Out-Host
  & $SdkManager "--sdk_root=$Sdk" @SdkPackages | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "sdkmanager failed" }

  # Tell Gradle where the SDK is.
  $LocalProps = Join-Path $Root 'android\local.properties'
  if (Test-Path (Split-Path $LocalProps)) {
    "sdk.dir=$($Sdk -replace '\\','\\')" | Set-Content -Encoding ascii $LocalProps
  }
}

Write-Host ""
Write-Host "Done. Activate the toolchain in a new PowerShell with:"
Write-Host "  . .\scripts\env.ps1"
