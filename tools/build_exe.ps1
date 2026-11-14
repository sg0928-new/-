# Build the single-file PrivacyGuard.exe (Windows only).
#
#   pip install pyinstaller
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
#
# Output: dist\PrivacyGuard.exe  (~65 MB, bundles Python, Tk, OpenCV + Haar cascades)

param(
    [string]$Python = "python",
    [switch]$Console          # keep a console window (useful for debugging a build)
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $root
try {
    if (-not (Test-Path -LiteralPath "assets\icon.ico")) {
        & $Python tools\make_icon.py
    }

    $mode = if ($Console) { "--console" } else { "--windowed" }
    & $Python -m PyInstaller `
        --noconfirm --clean --onefile $mode `
        --name PrivacyGuard `
        --icon "assets\icon.ico" `
        --version-file "assets\version_info.txt" `
        --collect-data cv2 `
        --hidden-import PIL.ImageTk `
        --hidden-import PIL._tkinter_finder `
        --add-data "assets\icon.png;assets" `
        launch.py

    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    $exe = Get-Item -LiteralPath "dist\PrivacyGuard.exe"
    $hash = (Get-FileHash -LiteralPath $exe.FullName -Algorithm SHA256).Hash
    "build ok: {0}  {1:N1} MB" -f $exe.FullName, ($exe.Length / 1MB)
    "sha256:   $hash"
}
finally {
    Pop-Location
}
