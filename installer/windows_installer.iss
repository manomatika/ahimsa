; windows_installer.iss — Inno Setup script for Matika-based applications.
;
; Packages PyInstaller's ONE-DIR output (the whole Matika-<matika_version>\
; directory tree, not a single exe) into a Windows installer EXE.
;
; All variable inputs are supplied by build.yml via ISCC /D defines so this
; script carries NO hardcoded version or path — the recipe (via build.yml's
; recipe_info outputs) is the single source of truth:
;
;   /DMyAppName="<application.name>"
;   /DMyAppVersion="<application.version>"      -> AppVersion (dynamic)
;   /DMyMatikaVersion="<matika.version>"        -> names the bundle dir / exe
;   /DMyBundleDir="build\matika\dist\Matika-<matika_version>"
;   /DMyOutputDir="."
;   /DMyOutputBaseName="<slug>-<app_version>-windows-x86_64"
;
; The bundle is one-dir: a folder containing Matika-<matika_version>.exe plus
; its _internal\ tree (Python runtime, static/, templates/, locales/, menus/,
; migrations/, and every other data file the matika.spec COLLECT step bundled).
; Cloned applug assets that PyInstaller picked up are inside that tree too, so
; "include everything recursively" guarantees all plugin assets ship.

; ---- Fallback defaults (overridden by ISCC /D on the CI runner) -------------
#ifndef MyAppName
  #define MyAppName "Matika Application"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef MyMatikaVersion
  #define MyMatikaVersion "0.0.0"
#endif
#ifndef MyBundleDir
  #define MyBundleDir "build\matika\dist\Matika-" + MyMatikaVersion
#endif
#ifndef MyOutputDir
  #define MyOutputDir "."
#endif
#ifndef MyOutputBaseName
  #define MyOutputBaseName "matika-windows-x86_64"
#endif

; The executable inside the one-dir bundle, named by matika.spec as
; Matika-<matika_version>.exe.
#define MyAppExeName "Matika-" + MyMatikaVersion + ".exe"

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
