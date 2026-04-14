#Requires -RunAsAdministrator
<#
.SYNOPSIS
    FaxNode – Vollautomatischer Windows-Installer
.DESCRIPTION
    Installiert alle Abhaengigkeiten und richtet FaxNode als Windows-Dienst ein.
    Muss als Administrator ausgefuehrt werden.
#>

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Beschleunigt Invoke-WebRequest

$REPO = "https://github.com/toxicshepherd/faxnode.git"
$INSTALL_DIR = "C:\FaxNode"
$TOOLS_DIR = "$INSTALL_DIR\tools"
$PORT = 9741

# --- Hilfsfunktionen ---

function Write-Step($num, $total, $msg) {
    Write-Host ""
    Write-Host "  [$num/$total] $msg" -ForegroundColor Cyan
}

function Test-Command($cmd) {
    return [bool](Get-Command $cmd -ErrorAction SilentlyContinue)
}

function Install-WithWinget($id, $name) {
    if (Test-Command "winget") {
        Write-Host "         Installiere $name via winget..."
        winget install $id --silent --accept-package-agreements --accept-source-agreements 2>$null
        # PATH aktualisieren
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                     [System.Environment]::GetEnvironmentVariable("Path", "User")
        return $true
    }
    return $false
}

function Install-WithDownload($url, $installer, $args, $name) {
    Write-Host "         Lade $name herunter..."
    $dlPath = "$TOOLS_DIR\$installer"
    Invoke-WebRequest -Uri $url -OutFile $dlPath -UseBasicParsing
    Write-Host "         Installiere $name..."
    Start-Process -FilePath $dlPath -ArgumentList $args -Wait -NoNewWindow
    # PATH aktualisieren
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                 [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# --- Banner ---

Write-Host ""
Write-Host "  ===============================" -ForegroundColor Green
Write-Host "       FaxNode Installer" -ForegroundColor Green
Write-Host "       Windows Edition" -ForegroundColor Green
Write-Host "  ===============================" -ForegroundColor Green
Write-Host ""

# Verzeichnisse vorbereiten
New-Item -ItemType Directory -Path $TOOLS_DIR -Force | Out-Null
New-Item -ItemType Directory -Path "$INSTALL_DIR\data" -Force | Out-Null
New-Item -ItemType Directory -Path "$INSTALL_DIR\static\thumbnails" -Force | Out-Null

$TOTAL_STEPS = 10

# --- 1. Python ---

Write-Step 1 $TOTAL_STEPS "Python pruefen..."
if (Test-Command "python") {
    $pyVer = python --version 2>&1
    Write-Host "         $pyVer vorhanden." -ForegroundColor Green
} else {
    Write-Host "         Python nicht gefunden. Wird installiert..."
    $installed = Install-WithWinget "Python.Python.3.12" "Python 3.12"
    if (-not $installed) {
        $pyUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
        Install-WithDownload $pyUrl "python-installer.exe" "/quiet InstallAllUsers=1 PrependPath=1" "Python 3.12"
    }
    if (-not (Test-Command "python")) {
        Write-Host "  FEHLER: Python konnte nicht installiert werden." -ForegroundColor Red
        exit 1
    }
    Write-Host "         Python installiert." -ForegroundColor Green
}

# --- 2. Git ---

Write-Step 2 $TOTAL_STEPS "Git pruefen..."
if (Test-Command "git") {
    Write-Host "         Git vorhanden." -ForegroundColor Green
} else {
    Write-Host "         Git nicht gefunden. Wird installiert..."
    $installed = Install-WithWinget "Git.Git" "Git"
    if (-not $installed) {
        $gitUrl = "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.2/Git-2.47.1.2-64-bit.exe"
        Install-WithDownload $gitUrl "git-installer.exe" "/VERYSILENT /NORESTART" "Git"
    }
    if (-not (Test-Command "git")) {
        Write-Host "  FEHLER: Git konnte nicht installiert werden." -ForegroundColor Red
        exit 1
    }
    Write-Host "         Git installiert." -ForegroundColor Green
}

# --- 3. Tesseract OCR ---

Write-Step 3 $TOTAL_STEPS "Tesseract OCR pruefen..."
$tesseractPaths = @(
    "${env:ProgramFiles}\Tesseract-OCR\tesseract.exe",
    "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe"
)
$tesseractFound = $false
foreach ($p in $tesseractPaths) {
    if (Test-Path $p) {
        $tesseractFound = $true
        $tesseractDir = Split-Path $p
        if ($env:Path -notlike "*$tesseractDir*") {
            $env:Path += ";$tesseractDir"
            [System.Environment]::SetEnvironmentVariable("Path",
                [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";$tesseractDir", "Machine")
        }
        break
    }
}
if ($tesseractFound) {
    Write-Host "         Tesseract vorhanden." -ForegroundColor Green
} else {
    Write-Host "         Tesseract nicht gefunden. Wird installiert..."
    $installed = Install-WithWinget "UB-Mannheim.TesseractOCR" "Tesseract OCR"
    if (-not $installed) {
        $tessUrl = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.5.0.20241111/tesseract-ocr-w64-setup-5.5.0.20241111.exe"
        Install-WithDownload $tessUrl "tesseract-installer.exe" "/S" "Tesseract OCR"
    }
    # Deutschen Sprachpack pruefen
    foreach ($p in $tesseractPaths) {
        $tessDir = Split-Path $p
        $tessData = "$tessDir\tessdata\deu.traineddata"
        if (Test-Path $tessDir) {
            if (-not (Test-Path $tessData)) {
                Write-Host "         Lade deutsches Sprachpaket..."
                $deuUrl = "https://github.com/tesseract-ocr/tessdata/raw/main/deu.traineddata"
                Invoke-WebRequest -Uri $deuUrl -OutFile $tessData -UseBasicParsing
            }
            if ($env:Path -notlike "*$tessDir*") {
                $env:Path += ";$tessDir"
                [System.Environment]::SetEnvironmentVariable("Path",
                    [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";$tessDir", "Machine")
            }
            break
        }
    }
    Write-Host "         Tesseract installiert." -ForegroundColor Green
}

# --- 4. Poppler ---

Write-Step 4 $TOTAL_STEPS "Poppler (PDF-Werkzeuge) herunterladen..."
$popplerDir = "$TOOLS_DIR\poppler"
if (Test-Path "$popplerDir\Library\bin\pdfinfo.exe") {
    Write-Host "         Poppler vorhanden." -ForegroundColor Green
} else {
    $popplerUrl = "https://github.com/oschwartz10612/poppler-windows/releases/download/v24.08.0-0/Release-24.08.0-0.zip"
    $popplerZip = "$TOOLS_DIR\poppler.zip"
    Write-Host "         Lade Poppler herunter..."
    Invoke-WebRequest -Uri $popplerUrl -OutFile $popplerZip -UseBasicParsing
    Expand-Archive -Path $popplerZip -DestinationPath $TOOLS_DIR -Force
    # Der entpackte Ordner heisst poppler-xx.xx.x
    $extracted = Get-ChildItem "$TOOLS_DIR\poppler-*" -Directory | Select-Object -First 1
    if ($extracted) {
        if (Test-Path $popplerDir) { Remove-Item $popplerDir -Recurse -Force }
        Rename-Item $extracted.FullName $popplerDir
    }
    Remove-Item $popplerZip -Force -ErrorAction SilentlyContinue
    Write-Host "         Poppler installiert." -ForegroundColor Green
}
# Umgebungsvariable setzen
[System.Environment]::SetEnvironmentVariable("POPPLER_PATH", "$popplerDir\Library\bin", "Machine")
$env:POPPLER_PATH = "$popplerDir\Library\bin"

# --- 5. SumatraPDF (PDF-Drucker) ---

Write-Step 5 $TOTAL_STEPS "SumatraPDF (PDF-Drucker) pruefen..."
$sumatraPath = "$TOOLS_DIR\SumatraPDF.exe"
# Auch in Program Files suchen (falls via winget installiert)
$sumatraSearchPaths = @(
    $sumatraPath,
    "${env:ProgramFiles}\SumatraPDF\SumatraPDF.exe",
    "${env:LocalAppData}\SumatraPDF\SumatraPDF.exe"
)
$sumatraFound = $false
foreach ($p in $sumatraSearchPaths) {
    if (Test-Path $p) {
        $sumatraPath = $p
        $sumatraFound = $true
        break
    }
}
if ($sumatraFound) {
    Write-Host "         SumatraPDF vorhanden: $sumatraPath" -ForegroundColor Green
} else {
    Write-Host "         SumatraPDF nicht gefunden. Wird installiert..."
    $installed = $false
    if (Test-Command "winget") {
        Write-Host "         Installiere via winget..."
        winget install SumatraPDF.SumatraPDF --silent --accept-package-agreements --accept-source-agreements 2>$null
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                     [System.Environment]::GetEnvironmentVariable("Path", "User")
        # Installierten Pfad finden
        foreach ($p in $sumatraSearchPaths) {
            if (Test-Path $p) {
                $sumatraPath = $p
                $installed = $true
                break
            }
        }
    }
    if (-not $installed) {
        # Fallback: Portable EXE von GitHub Releases herunterladen
        $dlUrls = @(
            "https://github.com/nickelc/sumatrapdf-releases/releases/download/3.6.1/SumatraPDF-3.6.1-64.exe",
            "https://github.com/nickelc/sumatrapdf-binaries/releases/download/3.5.2/SumatraPDF-3.5.2-64.exe"
        )
        $dlSuccess = $false
        foreach ($url in $dlUrls) {
            try {
                Invoke-WebRequest -Uri $url -OutFile "$TOOLS_DIR\SumatraPDF.exe" -UseBasicParsing -ErrorAction Stop
                $sumatraPath = "$TOOLS_DIR\SumatraPDF.exe"
                $dlSuccess = $true
                break
            } catch {
                continue
            }
        }
        if (-not $dlSuccess) {
            Write-Host "         WARNUNG: SumatraPDF konnte nicht installiert werden." -ForegroundColor Yellow
            Write-Host "         Bitte manuell installieren: winget install SumatraPDF.SumatraPDF" -ForegroundColor Yellow
            Write-Host "         Auto-Druck ist ohne SumatraPDF nicht verfuegbar." -ForegroundColor Yellow
            $sumatraPath = ""
        }
    }
    if ($sumatraPath) {
        Write-Host "         SumatraPDF installiert: $sumatraPath" -ForegroundColor Green
    }
}
if ($sumatraPath) {
    [System.Environment]::SetEnvironmentVariable("SUMATRA_PATH", $sumatraPath, "Machine")
    $env:SUMATRA_PATH = $sumatraPath
}

# --- 6. NSSM (Service Manager) ---

Write-Step 6 $TOTAL_STEPS "NSSM (Service Manager) herunterladen..."
$nssmPath = "$TOOLS_DIR\nssm.exe"
if (Test-Path $nssmPath) {
    Write-Host "         NSSM vorhanden." -ForegroundColor Green
} else {
    $nssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
    $nssmZip = "$TOOLS_DIR\nssm.zip"
    Write-Host "         Lade NSSM herunter..."
    Invoke-WebRequest -Uri $nssmUrl -OutFile $nssmZip -UseBasicParsing
    Expand-Archive -Path $nssmZip -DestinationPath "$TOOLS_DIR\nssm-tmp" -Force
    Copy-Item "$TOOLS_DIR\nssm-tmp\nssm-2.24\win64\nssm.exe" $nssmPath -Force
    Remove-Item "$TOOLS_DIR\nssm-tmp" -Recurse -Force
    Remove-Item $nssmZip -Force -ErrorAction SilentlyContinue
    Write-Host "         NSSM installiert." -ForegroundColor Green
}

# --- 7. FaxNode herunterladen ---

Write-Step 7 $TOTAL_STEPS "FaxNode herunterladen..."
if (Test-Path "$INSTALL_DIR\.git") {
    Write-Host "         Aktualisiere..."
    git -C $INSTALL_DIR pull -q 2>$null
} else {
    # Falls INSTALL_DIR existiert aber kein Git-Repo ist, Inhalte behalten
    if (-not (Test-Path $INSTALL_DIR)) {
        git clone -q $REPO $INSTALL_DIR
    } else {
        $tempDir = "$INSTALL_DIR-clone-tmp"
        git clone -q $REPO $tempDir
        # Git-Dateien in bestehenden Ordner kopieren
        Copy-Item "$tempDir\*" $INSTALL_DIR -Recurse -Force
        Copy-Item "$tempDir\.git" "$INSTALL_DIR\.git" -Recurse -Force
        Remove-Item $tempDir -Recurse -Force
    }
}
Write-Host "         Fertig." -ForegroundColor Green

# --- 8. Python-Umgebung ---

Write-Step 8 $TOTAL_STEPS "Python-Umgebung einrichten..."
$venvDir = "$INSTALL_DIR\venv"
if (-not (Test-Path "$venvDir\Scripts\python.exe")) {
    python -m venv $venvDir
}
& "$venvDir\Scripts\python.exe" -m pip install --upgrade pip -q 2>$null
& "$venvDir\Scripts\pip.exe" install -r "$INSTALL_DIR\requirements-win.txt" -q
Write-Host "         Fertig." -ForegroundColor Green

# --- 9. SSL-Zertifikate ---

Write-Step 9 $TOTAL_STEPS "SSL-Zertifikate generieren..."
$certDir = "$INSTALL_DIR\certs"
if ((Test-Path "$certDir\server.crt") -and (Test-Path "$certDir\server.key")) {
    Write-Host "         Zertifikate vorhanden." -ForegroundColor Green
} else {
    & "$venvDir\Scripts\python.exe" -c "
import sys; sys.path.insert(0, '$($INSTALL_DIR.Replace('\','\\'))')
from compat.certs import ensure_certs
ensure_certs('$($certDir.Replace('\','\\'))')
"
    Write-Host "         Fertig." -ForegroundColor Green
}

# --- 10. Firewall + Windows-Dienst ---

Write-Step 10 $TOTAL_STEPS "Firewall und Windows-Dienst einrichten..."

# Firewall-Regel
$fwRule = Get-NetFirewallRule -DisplayName "FaxNode" -ErrorAction SilentlyContinue
if (-not $fwRule) {
    New-NetFirewallRule -DisplayName "FaxNode" -Direction Inbound `
        -Protocol TCP -LocalPort $PORT -Action Allow -Profile Any | Out-Null
    Write-Host "         Firewall-Regel erstellt (Port $PORT)." -ForegroundColor Green
} else {
    Write-Host "         Firewall-Regel vorhanden." -ForegroundColor Green
}

# Bestehenden Dienst stoppen (ignoriere Fehler bei Erstinstallation)
$ErrorActionPreference = "SilentlyContinue"
& $nssmPath stop FaxNode 2>&1 | Out-Null
& $nssmPath remove FaxNode confirm 2>&1 | Out-Null
$ErrorActionPreference = "Stop"

# Neuen Dienst einrichten
$pythonExe = "$venvDir\Scripts\python.exe"
& $nssmPath install FaxNode $pythonExe "$INSTALL_DIR\wsgi.py"
& $nssmPath set FaxNode AppDirectory $INSTALL_DIR
& $nssmPath set FaxNode DisplayName "FaxNode – Digitale Faxverwaltung"
& $nssmPath set FaxNode Description "FaxNode Server fuer digitalen Faxempfang und -verwaltung"
& $nssmPath set FaxNode Start SERVICE_AUTO_START
& $nssmPath set FaxNode AppStdout "$INSTALL_DIR\data\faxnode.log"
& $nssmPath set FaxNode AppStderr "$INSTALL_DIR\data\faxnode.log"
& $nssmPath set FaxNode AppRotateFiles 1
& $nssmPath set FaxNode AppRotateBytes 5242880
& $nssmPath set FaxNode AppEnvironmentExtra "POPPLER_PATH=$env:POPPLER_PATH" "SUMATRA_PATH=$env:SUMATRA_PATH"

# Dienst starten
& $nssmPath start FaxNode
Write-Host "         FaxNode-Dienst gestartet." -ForegroundColor Green

# --- Fertig ---

$IP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -ne "127.0.0.1" -and
    $_.IPAddress -notlike "169.254.*" -and
    $_.IPAddress -notlike "25.*" -and
    $_.IPAddress -notlike "172.25.*" -and
    $_.InterfaceAlias -notmatch "Loopback|Hamachi|vEthernet|Bluetooth|VirtualBox|VMware"
} | Sort-Object -Property InterfaceMetric | Select-Object -First 1).IPAddress
if (-not $IP) { $IP = "localhost" }

Write-Host ""
Write-Host "  ======================================" -ForegroundColor Green
Write-Host "  FaxNode laeuft!" -ForegroundColor Green
Write-Host ""
Write-Host "  Oeffne im Browser:" -ForegroundColor White
Write-Host "  https://${IP}:${PORT}" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Windows-Clients: FaxNode-Setup.exe" -ForegroundColor White
Write-Host "  installieren und starten." -ForegroundColor White
Write-Host "  Der Server wird automatisch gefunden." -ForegroundColor White
Write-Host "  ======================================" -ForegroundColor Green
Write-Host ""

# Browser oeffnen
Start-Process "https://${IP}:${PORT}"
