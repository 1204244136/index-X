[CmdletBinding()]
param(
    [string]$SourceDirectory = 'C:\Users\12042\OneDrive\某系列\X系列\EPUB',
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'

$destinationRoot = Join-Path $PSScriptRoot 'EPUB'

if (-not (Test-Path -LiteralPath $SourceDirectory -PathType Container)) {
    throw "未找到线上 EPUB 目录: $SourceDirectory"
}

if (-not (Test-Path -LiteralPath $destinationRoot -PathType Container)) {
    throw "未找到项目 EPUB 目录: $destinationRoot"
}

$epubFiles = Get-ChildItem -LiteralPath $SourceDirectory -Filter '*.epub' -File | Sort-Object Name

if ($epubFiles.Count -eq 0) {
    throw "线上 EPUB 目录中没有找到 .epub 文件: $SourceDirectory"
}

Add-Type -AssemblyName System.IO.Compression

$bookCount = 0
$fileCount = 0
$failedBooks = [System.Collections.Generic.List[string]]::new()

foreach ($epubFile in $epubFiles) {
    $bookName = [System.IO.Path]::GetFileNameWithoutExtension($epubFile.Name)
    $bookDirectory = Join-Path $destinationRoot $bookName
    $bookDirectoryFullPath = [System.IO.Path]::GetFullPath($bookDirectory)
    $bookDirectoryPrefix = $bookDirectoryFullPath.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar

    if (-not (Test-Path -LiteralPath $bookDirectory -PathType Container)) {
        if ($WhatIf) {
            Write-Host "[预演] 创建目录: $bookDirectory"
        }
        else {
            New-Item -ItemType Directory -Path $bookDirectory -Force | Out-Null
        }
    }

    Write-Host "同步: $($epubFile.Name)"
    $zip = $null

    try {
        $zip = [System.IO.Compression.ZipFile]::OpenRead($epubFile.FullName)
        foreach ($entry in $zip.Entries) {
            if ([string]::IsNullOrEmpty($entry.Name)) {
                continue
            }

            $targetPath = [System.IO.Path]::GetFullPath((Join-Path $bookDirectoryFullPath $entry.FullName))
            if (-not $targetPath.StartsWith($bookDirectoryPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "压缩包包含越界路径: $($entry.FullName)"
            }

            $targetDirectory = Split-Path -Parent $targetPath
            if ($WhatIf) {
                Write-Host "[预演] 覆盖: $targetPath"
                continue
            }

            New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $targetPath, $true)
            $fileCount++
        }
    }
    catch {
        $failedBooks.Add($epubFile.Name)
        Write-Warning "跳过 $($epubFile.Name)：$($_.Exception.Message)"
        continue
    }
    finally {
        if ($null -ne $zip) {
            $zip.Dispose()
        }
    }

    $bookCount++
}

if ($WhatIf) {
    Write-Host "预演完成：成功读取 $bookCount 本 EPUB。"
}
else {
    Write-Host "同步完成：已处理 $bookCount 本 EPUB，覆盖 $fileCount 个文件。"
}

if ($failedBooks.Count -gt 0) {
    Write-Warning "有 $($failedBooks.Count) 本 EPUB 无法读取，可能仍是 OneDrive 仅联机文件："
    $failedBooks | ForEach-Object { Write-Warning "  $_" }
    exit 1
}
