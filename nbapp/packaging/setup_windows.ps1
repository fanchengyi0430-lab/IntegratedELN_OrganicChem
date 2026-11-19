# One-time setup for a Windows x64 source download. A portable release is already populated.
$ErrorActionPreference = 'Stop'
$packageDir = $PSScriptRoot
$appDir = Split-Path -Parent $packageDir
$downloads = Join-Path $packageDir '_downloads'
$runtime = Join-Path $appDir 'runtime\python.exe'
$lock = $null
$staging = $null

function Test-PythonArchive($path, $pin) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    $stream = [IO.File]::OpenRead($path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return $stream.Length -eq $pin.size -and
            [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') -eq $pin.sha256
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

try {
    [IO.Directory]::CreateDirectory($downloads) | Out-Null
    try {
        $lock = [IO.File]::Open((Join-Path $downloads 'setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch [IO.IOException] {
        throw "Cannot start setup in $downloads. If another setup is running, wait for it to finish and reopen Start Notebook.bat."
    }

    if (-not ((Test-Path -LiteralPath $runtime) -and (Test-Path -LiteralPath (Join-Path $appDir 'runtime\RUNTIME.json')))) {
        $pin = Get-Content -LiteralPath (Join-Path $packageDir 'windows_python.json') -Raw | ConvertFrom-Json
        $archive = Join-Path $downloads $pin.filename
        $staging = [IO.Directory]::CreateDirectory((Join-Path $downloads ([guid]::NewGuid().ToString('N')))).FullName
        if (-not (Test-PythonArchive $archive $pin)) {
            Write-Host "Downloading Python $($pin.version) for this notebook..."
            $partial = Join-Path $staging $pin.filename
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -UseBasicParsing -Uri $pin.url -OutFile $partial
            if (-not (Test-PythonArchive $partial $pin)) { throw 'The downloaded Python archive failed its size or SHA-256 check.' }
            [IO.File]::Copy($partial, $archive, $true)
        }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $bootstrap = Join-Path $staging 'python'
        [IO.Compression.ZipFile]::ExtractToDirectory($archive, $bootstrap)
        Write-Host 'Installing the pinned Python runtime, RDKit and chemistry libraries...'
        & (Join-Path $bootstrap 'python.exe') -B (Join-Path $packageDir 'build_runtime.py')
        if ($LASTEXITCODE -ne 0) { throw 'The chemistry runtime setup failed.' }
    }

    if (-not (Test-Path -LiteralPath (Join-Path $appDir 'sketcher\ketcher\index.html'))) {
        Write-Host 'Installing the Ketcher drawing editor...'
        & $runtime -B (Join-Path $packageDir 'build_sketcher.py')
        if ($LASTEXITCODE -ne 0) { throw 'The drawing editor setup failed.' }
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    if ($staging -and [IO.Path]::GetDirectoryName($staging) -eq [IO.Path]::GetFullPath($downloads)) {
        [IO.Directory]::Delete($staging, $true)
    }
    if ($lock) { $lock.Dispose() }
}
