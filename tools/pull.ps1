[CmdletBinding()]
param(
    [string]$ChineseSourceDirectory = (Join-Path $env:USERPROFILE 'OneDrive\某系列\X系列\EPUB'),
    [string]$JapaneseSourceDirectory = (Join-Path $env:USERPROFILE 'OneDrive\某系列\日文原文'),
    [string]$CacheDirectory = (Join-Path $PSScriptRoot '..\.cache\epub-work'),
    [string]$EpubDirectory = (Join-Path $PSScriptRoot '..\EPUB'),
    [ValidateSet('all', 'chinese', 'japanese')]
    [string]$Side = 'all',
    [string]$Pattern = '*',
    [switch]$Force,
    [switch]$SyncToEpub,
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'

# Incremental pull records OneDrive epub state (mtime ticks + size) per book.
# Books whose state did not change are skipped; -Force re-extracts everything.
$StateFileName = 'pull-state.tsv'

function Get-FullPath([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-PathWithin([string]$Path, [string]$Parent) {
    $fullPath = (Get-FullPath $Path).TrimEnd('\', '/') + '\'
    $fullParent = (Get-FullPath $Parent).TrimEnd('\', '/') + '\'
    return $fullPath.StartsWith($fullParent, [System.StringComparison]::OrdinalIgnoreCase)
}

function Read-PullState([string]$Path) {
    $state = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $state
    }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $parts = $line -split "`t"
        if ($parts.Count -lt 4) {
            continue
        }
        $state["$($parts[0])`t$($parts[1])"] = @{ mtime = $parts[2]; size = $parts[3] }
    }
    return $state
}

function Write-PullState([string]$Path, [hashtable]$State) {
    $lines = foreach ($entry in $State.GetEnumerator()) {
        "$($entry.Key)`t$($entry.Value.mtime)`t$($entry.Value.size)"
    }
    $lines | Sort-Object | Set-Content -LiteralPath $Path -Encoding UTF8
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
New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
$statePath = Join-Path $cacheRoot $StateFileName
$pullState = Read-PullState $statePath

# Clean up orphaned .extract-* directories from previous interrupted runs
foreach ($sideFolder in @('chinese-text', 'japanese-text')) {
    $sideRoot = Join-Path $cacheRoot $sideFolder
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
$skipped = 0
$extractedBooks = [System.Collections.Generic.List[string]]::new()

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
        $book = $epubFile.BaseName
        $stateKey = "$($source.Name)`t$book"

        if (-not $Force) {
            $record = $pullState[$stateKey]
            if ($null -ne $record -and
                $record.mtime -eq [string]$epubFile.LastWriteTimeUtc.Ticks -and
                $record.size -eq [string]$epubFile.Length) {
                $skipped++
                if ($WhatIf) {
                    Write-Host "[跳过] $($epubFile.FullName)（未变化）"
                }
                continue
            }
        }

        try {
            Extract-Epub $epubFile (Join-Path $destinationRoot $book) -Preview:$WhatIf
            if (-not $WhatIf) {
                $pullState[$stateKey] = @{
                    mtime = [string]$epubFile.LastWriteTimeUtc.Ticks
                    size  = [string]$epubFile.Length
                }
                $extractedBooks.Add("$($source.Name)/$book")
            }
            $total++
        }
        catch {
            $failed++
            Write-Warning "跳过 $($epubFile.Name)：$($_.Exception.Message)"
        }
    }
}

if ($WhatIf) {
    Write-Host "预演完成：$total 个 EPUB 需要解压，$skipped 个未变化，$failed 个失败。"
}
else {
    Write-Host "缓存解压完成：$total 个 EPUB，$skipped 个未变化，$failed 个失败。"

    if ($extractedBooks.Count -gt 0) {
        $downstreamSucceeded = $false

        if ($SyncToEpub) {
            # Sync only the changed files of the extracted books into EPUB/
            # and update the manifest for them. --only-books keeps pending
            # cache edits in other books as un-published changes.
            $publishScript = Join-Path $PSScriptRoot 'publish.py'
            $manifestPath = Join-Path $cacheRoot 'manifest.json'
            $pyArgs = @(
                $publishScript,
                '--sync-only',
                '--cache', $cacheRoot,
                '--epub', (Get-FullPath $EpubDirectory),
                '--side', $Side,
                '--pattern', $Pattern,
                '--only-books', ($extractedBooks -join ',')
            )
            if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
                # First pull into a fresh cache: no baseline, treat everything as added.
                $pyArgs += '--force'
            }
            Write-Host "`n同步变更到 EPUB/ ..."
            & python @pyArgs
            if ($LASTEXITCODE -ne 0) {
                $failed++
                Write-Warning "EPUB/ 同步失败（publish.py 退出码 $LASTEXITCODE）。未推进 pull-state；重跑本命令会重新解压并重试。"
            }
            else {
                $downstreamSucceeded = $true
            }
        }
        else {
            # Rebase only the extracted books; pending edits in other books
            # keep their old manifest baseline and stay publishable.
            $manifestScript = Join-Path $PSScriptRoot 'manifest.py'
            Write-Host "`n更新哈希清单..."
            if (Test-Path -LiteralPath (Join-Path $cacheRoot 'manifest.json') -PathType Leaf) {
                & python $manifestScript --cache $cacheRoot --update-books @extractedBooks
            }
            else {
                & python $manifestScript --cache $cacheRoot
            }
            if ($LASTEXITCODE -ne 0) {
                $failed++
                Write-Warning "清单更新失败，publish 时将无法正确检测增量变更。"
            }
            else {
                $downstreamSucceeded = $true
            }
        }

        if ($downstreamSucceeded) {
            # Commit the extraction state only after the corresponding
            # manifest/EPUB baseline has advanced successfully.
            Write-PullState $statePath $pullState
        }
    }
    else {
        Write-Host "没有检测到 OneDrive 变更，跳过清单与 EPUB/ 同步。"
    }
}

if ($failed -gt 0) {
    exit 1
}
