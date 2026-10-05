<#
.SYNOPSIS
  Installs a project-local toolchain into .toolchain\ (nothing system-wide):
    .toolchain\env          conda env: Python analysis stack, JDK 17, R + lme4
    .toolchain\android-sdk  Android SDK (command-line tools, platform, build tools)
    .toolchain\innosetup    Inno Setup, portable (builds the desktop app's installer)

.DESCRIPTION
  Requires conda (Miniforge/Anaconda) on PATH. Safe to re-run: each step is
  skipped if already done. Running sdkmanager accepts the Android SDK licences
  on your behalf (they are printed to the console).

  If you prefer Android Studio, you can skip the SDK part (-SkipAndroid) and
  open android\ in Android Studio instead.
#>
param(
  [switch]$SkipAndroid,
  [switch]$SkipConda,
  [switch]$SkipInno
)
$ErrorActionPreference = 'Stop'
# Ignore packages in the user's own Python folder (%APPDATA%\Python): otherwise pip counts them
# as installed and leaves them out of the toolchain, and the app breaks where they're missing.
$env:PYTHONNOUSERSITE = '1'
$Root = Split-Path -Parent $PSScriptRoot
$Tool = Join-Path $Root '.toolchain'
New-Item -ItemType Directory -Force $Tool | Out-Null

# Pinned so every lab builds the same thing.
$CmdlineToolsUrl = 'https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip'
$SdkPackages = @('platform-tools', 'platforms;android-35', 'build-tools;35.0.0')
$InnoUrl = 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe'

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
  # Feed the "y" answers from a file: Windows PowerShell 5.1 does not deliver
  # piped stdin to a .bat, so sdkmanager would silently decline every licence.
  $YesFile = Join-Path $Tool 'yes.txt'
  Set-Content -Encoding ascii $YesFile (@('y') * 50)
  Start-Process -FilePath $SdkManager -ArgumentList "`"--sdk_root=$Sdk`"", '--licenses' `
    -RedirectStandardInput $YesFile -NoNewWindow -Wait
  Remove-Item $YesFile
  if (-not (Test-Path (Join-Path $Sdk 'licenses\android-sdk-license'))) { throw "Android SDK licences were not accepted" }
  & $SdkManager "--sdk_root=$Sdk" @SdkPackages | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "sdkmanager failed" }
  if (-not (Test-Path (Join-Path $Sdk 'platform-tools\adb.exe'))) { throw "Android SDK packages were not installed" }

  # Tell Gradle where the SDK is.
  $LocalProps = Join-Path $Root 'android\local.properties'
  if (Test-Path (Split-Path $LocalProps)) {
    "sdk.dir=$($Sdk -replace '\\','\\')" | Set-Content -Encoding ascii $LocalProps
  }
}

if (-not $SkipInno) {
  $Inno = Join-Path $Tool 'innosetup'
  if (-not (Test-Path (Join-Path $Inno 'ISCC.exe'))) {
    Write-Host "[inno] downloading Inno Setup (portable: no registry entries, no uninstaller)"
    $Exe = Join-Path $Tool 'innosetup.exe'
    Invoke-WebRequest -Uri $InnoUrl -OutFile $Exe -UseBasicParsing
    Start-Process -FilePath $Exe -Wait -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER',
      '/PORTABLE=1', '/NOICONS', "/DIR=`"$Inno`""
    Remove-Item $Exe
    if (-not (Test-Path (Join-Path $Inno 'ISCC.exe'))) { throw "Inno Setup was not installed" }
  }
}

Write-Host ""
Write-Host "Done. Activate the toolchain in a new PowerShell with:"
Write-Host "  . .\scripts\env.ps1"
