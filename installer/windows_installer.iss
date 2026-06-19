; windows_installer.iss — Inno Setup script for ManoMatika-ecosystem products.
;
; Packages PyInstaller's ONE-DIR output (the whole <product_name>-<version>\
; directory tree, not a single exe) into a Windows installer EXE.
;
; PRODUCT IDENTITY: the installed app name, exe name, shortcuts, and install
; directory are all the PRODUCT identity (e.g. ManoMatika), NOT the matika
; component. build.yml passes the recipe's product_name as MyAppName and the
; product version (application.version) as MyAppVersion.
;
; CORE/SUFFIX CONTRACT: MyAppVersion here is always BARE CORE (X.Y.Z) — the
; product version with any pre-release suffix (-dev / -rc.N) stripped, matching
; the bare core matika.spec emits. So the bundle dir / exe this script
; references (<product_name>-<bare-core>\ and <product_name>-<bare-core>.exe)
; match the spec's output even when the build runs at a pre-release TAG. Never
; embed a suffix into the bundle name, the exe name, or AppVersion.
;
; All variable inputs are supplied by build.yml via ISCC /D defines so this
; script carries NO hardcoded name/version/path — the recipe (via build.yml's
; recipe_info outputs) is the single source of truth:
;
;   /DMyAppName="<application.product_name>"     -> installed identity (e.g. ManoMatika)
;   /DMyAppVersion="<application.version>"       -> AppVersion + names the exe/dir
;   /DMyBundleDir="build\matika\dist\<product_name>-<version>"
;   /DMyOutputDir="."
;   /DMyOutputBaseName="<product_slug>-<version>-windows-x86_64"
;
; The bundle is one-dir: a folder containing <product_name>-<version>.exe plus
; its _internal\ tree (Python runtime, static/, templates/, locales/, menus/,
; migrations/, and every other data file the matika.spec COLLECT step bundled).
; Cloned applug assets that PyInstaller picked up are inside that tree too, so
; "include everything recursively" guarantees all plugin assets ship.

; ---- Fallback defaults (overridden by ISCC /D on the CI runner) -------------
#ifndef MyAppName
  #define MyAppName "ManoMatika"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef MyBundleDir
  #define MyBundleDir "build\matika\dist\" + MyAppName + "-" + MyAppVersion
#endif
#ifndef MyOutputDir
  #define MyOutputDir "."
#endif
#ifndef MyOutputBaseName
  #define MyOutputBaseName "manomatika-windows-x86_64"
#endif

; The executable inside the one-dir bundle, named by matika.spec as
; <product_name>-<version>.exe — i.e. MyAppName-MyAppVersion.exe.
#define MyAppExeName MyAppName + "-" + MyAppVersion + ".exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
; x64 PyInstaller output -> install as a native 64-bit app on 64-bit Windows.
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
OutputDir={#MyOutputDir}
OutputBaseFilename={#MyOutputBaseName}
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Recurse the ENTIRE one-dir bundle. This pulls in Matika-<ver>.exe, the
; _internal\ runtime tree, and all bundled data (static, templates, locales,
; menus, migrations) — i.e. every plugin asset PyInstaller collected.
Source: "{#MyBundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
