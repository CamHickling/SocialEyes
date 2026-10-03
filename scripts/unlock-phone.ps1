# Wakes and unlocks the test phone over USB, using the PIN in phone-pin.local
# (project root, git-ignored). The PIN is never printed.
#   .\scripts\unlock-phone.ps1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$PinFile = Join-Path $Root 'phone-pin.local'
$Adb = Join-Path $Root '.toolchain\android-sdk\platform-tools\adb.exe'

function Test-Locked { (& $Adb shell dumpsys window) -match 'isKeyguardShowing=true' }

if (-not (Test-Path $PinFile)) { throw "No $PinFile. Create it with the phone's PIN on its own line." }
$pin = Get-Content $PinFile | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') } | Select-Object -First 1
if (-not $pin -or $pin -notmatch '^\d{4,16}$') { throw "phone-pin.local needs the PIN (4-16 digits) on a line of its own." }

if ((& $Adb get-state 2>$null) -ne 'device') { throw "No phone found. Is it plugged in with USB debugging allowed?" }
if (-not (Test-Locked)) { Write-Host "Phone is already unlocked."; return }

# Wake, swipe up to the PIN pad, type the PIN, confirm.
$size = (& $Adb shell wm size) -replace '.*:\s*', '' -split 'x'
$w = [int]$size[0]; $h = [int]$size[1]
& $Adb shell input keyevent KEYCODE_WAKEUP
Start-Sleep -Milliseconds 500
& $Adb shell input swipe ([int]($w / 2)) ([int]($h * 0.85)) ([int]($w / 2)) ([int]($h * 0.25)) 250
Start-Sleep -Milliseconds 700
& $Adb shell input text $pin
& $Adb shell input keyevent KEYCODE_ENTER
Start-Sleep -Milliseconds 1200

if (Test-Locked) { throw "Still locked. Check the PIN in phone-pin.local (too many wrong tries locks the phone for a while)." }
Write-Host "Phone unlocked."
