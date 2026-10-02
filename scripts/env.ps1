# Dot-source to put the project-local toolchain on PATH for this shell:
#   . .\scripts\env.ps1
$Root = Split-Path -Parent $PSScriptRoot
$Tool = Join-Path $Root '.toolchain'
$EnvDir = Join-Path $Tool 'env'
$Sdk = Join-Path $Tool 'android-sdk'

if (Test-Path (Join-Path $EnvDir 'Library\bin\java.exe')) { $env:JAVA_HOME = Join-Path $EnvDir 'Library' }
if (Test-Path $Sdk) { $env:ANDROID_HOME = $Sdk; $env:ANDROID_SDK_ROOT = $Sdk }

$paths = @(
  $EnvDir,
  (Join-Path $EnvDir 'Scripts'),
  (Join-Path $EnvDir 'Library\bin'),
  (Join-Path $EnvDir 'Lib\R\bin\x64'),
  (Join-Path $Sdk 'platform-tools')
) | Where-Object { Test-Path $_ }
$env:PATH = ($paths -join ';') + ';' + $env:PATH
Write-Host "SocialEyes toolchain active (python, java, R, adb)."
