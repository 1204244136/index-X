[CmdletBinding()]
param(
    [string]$ChineseSourceDirectory = (Join-Path $env:USERPROFILE 'OneDrive\某系列\X系列\EPUB'),
    [string]$JapaneseSourceDirectory = (Join-Path $env:USERPROFILE 'OneDrive\某系列\日文原文'),
    [string]$CacheDirectory = (Join-Path $PSScriptRoot '..\.cache\epub-work'),
    [ValidateSet('all', 'chinese', 'japanese')]
    [string]$Side = 'all',
    [string]$Pattern = '*',
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'

function Get-FullPath([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-PathWithin([string]$Path, [string]$Parent) {
    $fullPath = (Get-FullPath $Path).TrimEnd('\', '/') + '\'
    $fullParent = (Get-FullPath $Parent).TrimEnd('\', '/') + '\'
    return $fullPath.StartsWith($fullParent, [System.StringComparison]::OrdinalIgnoreCase)
}

function Extract-Epub([System.IO.FileInfo]$EpubFile, [string]$Destination, [switch]$Preview) {
    $destinationFullPath = Get-FullPath $Destination
    $parent = Split-Path -Parent $destinationFullPath
    $temporary = Join-Path $parent ('.extract-' + [guid]::NewGuid().ToString('N'))

    if ($Preview) {
        Write-Host "[预演] $($EpubFile.FullName) -> $destinationFullPath"
        return
    }

    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    New-Item -ItemType Directory -Path $temporary -Force | Out-Null
    $zip = $null
    try {
        $zip = [System.IO.Compression.ZipFile]::OpenRead($EpubFile.FullName)
        $destinationPrefix = (Get-FullPath $temporary).TrimEnd('\', '/') + '\'
        foreach ($entry in $zip.Entries) {
            if ([string]::IsNullOrEmpty($entry.Name)) {
                continue
            }

            $targetPath = Get-FullPath (Join-Path $temporary $entry.FullName)
            if (-not $targetPath.StartsWith($destinationPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "压缩包包含越界路径: $($entry.FullName)"
            }

            $targetDirectory = Split-Path -Parent $targetPath
            New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $targetPath, $true)
        }

        if (-not (Test-Path -LiteralPath (Join-Path $temporary 'mimetype') -PathType Leaf)) {
            throw '压缩包缺少根目录 mimetype 文件'
        }
        if (-not (Test-Path -LiteralPath (Join-Path $temporary 'META-INF\container.xml') -PathType Leaf)) {
            throw '压缩包缺少 META-INF/container.xml'
        }

        if (Test-Path -LiteralPath $destinationFullPath) {
            Remove-Item -LiteralPath $destinationFullPath -Recurse -Force
        }
        Move-Item -LiteralPath $temporary -Destination $destinationFullPath
        Write-Host "已解压: $destinationFullPath"
    }
    finally {
        if ($null -ne $zip) {
            $zip.Dispose()
        }
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$cacheRoot = Get-FullPath $CacheDirectory

# Clean up orphaned .extract-* directories from previous interrupted runs
foreach ($side in @('chinese-text', 'japanese-text')) {
    $sideRoot = Join-Path $cacheRoot $side
    if (Test-Path -LiteralPath $sideRoot) {
        Get-ChildItem -LiteralPath $sideRoot -Directory -Filter '.extract-*' -ErrorAction SilentlyContinue |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

$sources = @(
    @{ Name = 'chinese-text'; Path = $ChineseSourceDirectory; Enabled = ($Side -in @('all', 'chinese')) },
    @{ Name = 'japanese-text'; Path = $JapaneseSourceDirectory; Enabled = ($Side -in @('all', 'japanese')) }
)

$total = 0
$failed = 0
foreach ($source in $sources) {
    if (-not $source.Enabled) {
        continue
    }
    $sourcePath = Get-FullPath $source.Path
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
        throw "未找到源目录: $sourcePath"
    }

    $destinationRoot = Join-Path $cacheRoot $source.Name
    $epubFiles = @(Get-ChildItem -LiteralPath $sourcePath -Filter '*.epub' -File |
        Where-Object { $_.BaseName -like $Pattern } |
        Sort-Object Name)
    if ($epubFiles.Count -eq 0) {
        Write-Warning "源目录中没有 EPUB: $sourcePath"
        continue
    }

    foreach ($epubFile in $epubFiles) {
        try {
            Extract-Epub $epubFile (Join-Path $destinationRoot ([System.IO.Path]::GetFileNameWithoutExtension($epubFile.Name))) -Preview:$WhatIf
            $total++
        }
        catch {
            $failed++
            Write-Warning "跳过 $($epubFile.Name)：$($_.Exception.Message)"
        }
    }
}

if ($WhatIf) {
    Write-Host "预演完成：$total 个 EPUB。"
}
else {
    Write-Host "缓存解压完成：$total 个 EPUB，$failed 个失败。"

    # Generate manifest for change detection in publish step
    $manifestScript = Join-Path $PSScriptRoot 'manifest.py'
    if (Test-Path -LiteralPath $manifestScript) {
        Write-Host "`n生成哈希清单..."
        & python $manifestScript --cache $cacheRoot
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "清单生成失败，publish 时将无法检测增量变更。"
        }
    }
}

if ($failed -gt 0) {
    exit 1
}
