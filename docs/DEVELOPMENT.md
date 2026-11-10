# Developing SocialEyes

Material for people who build and release SocialEyes. Researchers using it only need the
[README](../README.md).

## Building the installer

Researchers who don't use a terminal get a normal Windows installer
(`SocialEyes-Setup-<version>.exe`). It installs per user (no administrator rights needed)
and bundles Python, the `socialeyes` package, adb, the phone app and the example study.
The installed app keeps studies and data in `Documents\SocialEyes` (`studies\`, `data\`,
`analysis_out\`); uninstalling removes the program only, never those folders. It needs the
Microsoft Edge WebView2 Runtime, which comes with Windows 11 and up-to-date Windows 10;
the installer checks for it and offers Microsoft's download page when it is missing.

```powershell
. .\scripts\env.ps1
python packaging\build.py          # release: needs the signing key (see [Release signing key](#release-signing-key))
python packaging\build.py --dev    # test build with this computer's debug-signed phone app
```

The installer is written to `packaging\out\`. A `--dev` installer is for testing on your
own machines only: its phone app is signed with this computer's debug key, so phones that
get it can't take the release app later without uninstalling it, which deletes its data.
`SocialEyes.exe --selftest report.json` checks the bundled parts (builder page, adb, phone
app, example study, window toolkit) without opening a window. `setup-toolchain.ps1`
installs PyInstaller and a portable Inno Setup (no registry entries) into `.toolchain\`.
The toolchain uses OpenBLAS rather than Intel MKL (`environment.yml`), which keeps about
600 MB of MKL libraries out of the installer; in an older toolchain run
`conda install -p .toolchain\env -c conda-forge "libblas=*=*openblas"`. The release phone
app is shrunk with R8 (`android/app/proguard-rules.pro`), from about 74 MB to about 5 MB.


## Release signing key

Phones can only update the app if every version is signed with the same key. Debug
builds use this computer's debug key, which is fine for development. For releases
(the desktop app's installer), create the project key **once**, keep it out of git
(`.gitignore` covers it) and back it up with its passwords somewhere safe. If it is
lost, phones can't install updates without uninstalling the app, which deletes its data.

```powershell
. .\scripts\env.ps1
keytool -genkeypair -v -keystore android\socialeyes-release.jks -alias socialeyes `
  -keyalg RSA -keysize 4096 -validity 10000
```

Then create `android\keystore.properties`:

```
storeFile=socialeyes-release.jks
storePassword=<the keystore password>
keyAlias=socialeyes
keyPassword=<the key password>
```

and build with `.\gradlew assembleRelease`. A phone that has a debug build can't be
updated to a release build in place (different keys): unload its sessions, uninstall
SocialEyes on the phone, then load again.


## Unlocking a test phone

To unlock a test phone from the computer, put its PIN in `phone-pin.local` in the project
root (git-ignored; never commit it) and run `.\scripts\unlock-phone.ps1`.
