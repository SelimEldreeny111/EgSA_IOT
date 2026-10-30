param([string]$CompilerPath='g++')
$ErrorActionPreference='Stop'
$flashCompiler=(Get-Command $CompilerPath).Source
$flashOldPath=$env:PATH
$flashBuild=Join-Path ([IO.Path]::GetTempPath()) ('wiot-flash-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $flashBuild | Out-Null
try {
    $env:PATH=(Split-Path -Parent $flashCompiler)+';'+$env:PATH
    $flashRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
    & $flashCompiler '-std=c++14' '-Wall' '-Wextra' '-Werror' '-pedantic' `
        (Join-Path $flashRoot 'src/storage/TelemetryJournal.cpp') `
        (Join-Path $PSScriptRoot 'journal_test.cpp') '-o' (Join-Path $flashBuild 'journal.exe')
    if($LASTEXITCODE -ne 0){throw 'Flash journal compile failed'}
    & (Join-Path $flashBuild 'journal.exe')
    if($LASTEXITCODE -ne 0){throw 'Flash journal tests failed'}
    $flashArgs=@('-std=c++14','-Wall','-Wextra','-Werror','-pedantic',
        '-I',(Join-Path $PSScriptRoot 'fakes'),'-include',(Join-Path $PSScriptRoot 'fakes/ArchiveConfig.h'),
        (Join-Path $flashRoot 'src/storage/S25Fl064l.cpp'),
        (Join-Path $flashRoot 'src/storage/TelemetryJournal.cpp'),
        (Join-Path $flashRoot 'src/storage/TelemetryArchive.cpp'),
        (Join-Path $flashRoot 'src/third_party/nanopb/pb_common.c'),
        (Join-Path $flashRoot 'src/third_party/nanopb/pb_encode.c'),
        (Join-Path $flashRoot 'src/third_party/nanopb/pb_decode.c'),
        (Join-Path $flashRoot 'src/generated/sensor.pb.c'),
        (Join-Path $PSScriptRoot 'archive_test.cpp'),'-o',(Join-Path $flashBuild 'archive.exe'))
    & $flashCompiler @flashArgs
    if($LASTEXITCODE -ne 0){throw 'Flash archive compile failed'}
    foreach($flashCase in @('driver','missing','capture','download','timeout','cancel','retention','resume','empty')){
        & (Join-Path $flashBuild 'archive.exe') $flashCase
        if($LASTEXITCODE -ne 0){throw "Flash archive regression: $flashCase"}
    }
    & $flashCompiler '-std=c++14' '-Wall' '-Wextra' '-Werror' '-pedantic' `
        '-I' (Join-Path $PSScriptRoot 'fakes') '-include' (Join-Path $PSScriptRoot 'fakes/LoraConfig.h') `
        (Join-Path $PSScriptRoot 'lora_large_frame_test.cpp') '-o' (Join-Path $flashBuild 'lora.exe')
    if($LASTEXITCODE -ne 0){throw 'Large LoRa frame compile failed'}
    & (Join-Path $flashBuild 'lora.exe')
    if($LASTEXITCODE -ne 0){throw 'Large LoRa frame test failed'}
} finally {$env:PATH=$flashOldPath}
