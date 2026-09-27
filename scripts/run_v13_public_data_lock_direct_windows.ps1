param(
    [switch] $Execute,
    [string] $ApprovedImplementationSha,
    [string] $ExecutionHead,
    [string] $AuthorizationRecord,
    [string] $PrivateT1State,
    [string] $CalendarLock,
    [string] $CalendarSha256,
    [string] $OutputDirectory
)

& {
    $ErrorActionPreference = 'Stop'
    $repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
    if (-not $Execute) {
        Write-Output 'V13_PUBLIC_DATALOCK_REHEARSAL=true'
        Write-Output 'NETWORK_REQUESTS=0'
        Write-Output 'PRIVATE_READS=0'
        Write-Output 'REAL_UNIVERSE_SELECTED=false'
        return
    }
    if ([string]::IsNullOrWhiteSpace($ApprovedImplementationSha) -or
        [string]::IsNullOrWhiteSpace($ExecutionHead) -or
        [string]::IsNullOrWhiteSpace($AuthorizationRecord) -or
        [string]::IsNullOrWhiteSpace($PrivateT1State) -or
        [string]::IsNullOrWhiteSpace($CalendarLock) -or
        [string]::IsNullOrWhiteSpace($CalendarSha256) -or
        [string]::IsNullOrWhiteSpace($OutputDirectory)) { throw 'BLOCK_MISSING_EXPLICIT_INPUT' }
    if ($ApprovedImplementationSha -cnotmatch '^[0-9a-f]{40}$' -or
        $ExecutionHead -cnotmatch '^[0-9a-f]{40}$' -or
        $CalendarSha256 -cne '30ad5d66c6c3b8bd2c71a814309e6133a03331437089103799551fa72150c44c') {
        throw 'BLOCK_INVALID_BINDING'
    }
    Set-Location -LiteralPath $repoRoot
    $branchName = (& git branch --show-current).Trim()
    $localHead = (& git rev-parse HEAD).Trim()
    $remoteHead = (& git ls-remote origin refs/heads/v13-conditional-cross-sectional-short-horizon)
    $treeStatus = & git status --porcelain
    if ($branchName -cne 'v13-conditional-cross-sectional-short-horizon' -or
        $localHead -cne $ExecutionHead -or
        @($remoteHead).Count -ne 1 -or
        (-not $remoteHead.StartsWith($ExecutionHead + "`t")) -or
        -not [string]::IsNullOrWhiteSpace(($treeStatus -join ''))) { throw 'BLOCK_REPOSITORY_PREFLIGHT' }
    $ancestor = (& git merge-base $ApprovedImplementationSha $ExecutionHead).Trim()
    if ($LASTEXITCODE -ne 0 -or $ancestor -cne $ApprovedImplementationSha) {
        throw 'BLOCK_IMPLEMENTATION_ANCESTRY'
    }
    $resultRelative = 'docs/v13/V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT.json'
    $resultTree = & git ls-tree HEAD -- $resultRelative
    $resultPath = Join-Path $repoRoot $resultRelative
    if (@($resultTree).Count -ne 1 -or
        $resultTree -cnotmatch '^100644 blob 336e5dd6141230b95fa4548231b0a137be6a15cb\s' -or
        -not (Test-Path -LiteralPath $resultPath -PathType Leaf) -or
        (& git hash-object -- $resultPath).Trim() -cne '336e5dd6141230b95fa4548231b0a137be6a15cb') {
        throw 'BLOCK_MASTER_CALENDAR_RESULT_BLOB'
    }
    $authorizationRelative = 'docs/v13/V13_PUBLIC_DATALOCK_POINT_OF_USE_AUTHORIZATION.json'
    $authorizationPath = Join-Path $repoRoot $authorizationRelative
    $authorizationBlob = '980fb0c764d9495f8e298865fe1f48373ac84281'
    if (-not (Test-Path -LiteralPath $AuthorizationRecord -PathType Leaf) -or
        -not [string]::Equals([System.IO.Path]::GetFullPath($AuthorizationRecord),
            [System.IO.Path]::GetFullPath($authorizationPath),
            [System.StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals((Resolve-Path -LiteralPath $AuthorizationRecord).Path,
            (Resolve-Path -LiteralPath $authorizationPath).Path,
            [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'BLOCK_AUTHORIZATION_PATH'
    }
    $authorizationTree = & git ls-tree HEAD -- $authorizationRelative
    if (@($authorizationTree).Count -ne 1 -or
        $authorizationTree -cnotmatch ('^100644 blob ' + $authorizationBlob + '\s') -or
        (& git hash-object -- $authorizationPath).Trim() -cne $authorizationBlob) {
        throw 'BLOCK_AUTHORIZATION_BLOB'
    }
    $standingRelative = 'V13_PUBLIC_ACQUISITION_AUTHORIZATION.json'
    $standingPath = Join-Path $repoRoot $standingRelative
    $standingBlob = '291eda465ae26f86bbe8540f12551e1f40283d5b'
    $standingTree = & git ls-tree HEAD -- $standingRelative
    if (@($standingTree).Count -ne 1 -or
        $standingTree -cnotmatch ('^100644 blob ' + $standingBlob + '\s') -or
        -not (Test-Path -LiteralPath $standingPath -PathType Leaf) -or
        (& git hash-object -- $standingPath).Trim() -cne $standingBlob) {
        throw 'BLOCK_STANDING_PUBLIC_AUTHORIZATION_BLOB'
    }
    $authorization = Get-Content -LiteralPath $authorizationPath -Raw | ConvertFrom-Json
    if ($authorization.schema -cne 'V13_PUBLIC_DATALOCK_POINT_OF_USE_AUTHORIZATION_V1' -or
        $authorization.study -cne 'V13_CONDITIONAL_CROSS_SECTIONAL_SHORT_HORIZON' -or
        $authorization.authoritative_branch -cne 'v13-conditional-cross-sectional-short-horizon' -or
        $authorization.authorization_scope -cne 'SELECTED500_PUBLIC_DATALOCK_ONLY' -or
        $authorization.github_issue -cne 95 -or
        $authorization.human_approval_comment_id -cne 5843355424 -or
        $authorization.human_approval_comment_url -cne 'https://github.com/ta1k1-arakawa/stock-analyzer/issues/95#issuecomment-5843355424' -or
        $authorization.predecessor_gpt_pass_issue -cne 94 -or
        $authorization.reviewed_implementation_sha -cne '6b4454aafc05c66c37d75e33a586d79653c1a413' -or
        $authorization.reviewed_implementation_sha -cne $ApprovedImplementationSha -or
        $authorization.master_calendar_sha256 -cne $CalendarSha256 -or
        $authorization.master_calendar_safe_result_blob -cne '336e5dd6141230b95fa4548231b0a137be6a15cb' -or
        $authorization.public_acquisition_authorization_blob -cne $standingBlob -or
        $authorization.operation_class -cne 'RETRIABLE_PUBLIC_PLUMBING' -or
        @($authorization.providers).Count -ne 2 -or
        $authorization.providers[0] -cne 'JPX_CURRENT_LISTED_ISSUES' -or
        $authorization.providers[1] -cne 'YAHOO_FINANCE_CHART' -or
        $authorization.price_window_start -cne '2015-01-01' -or
        $authorization.price_window_end -cne '2025-12-31' -or
        $authorization.selected_universe_size -cne 500 -or
        $authorization.public_datalock_execution_approved -cne $true -or
        $authorization.derived_t1_state_read_for_deterministic_exclusion_selection_resume_authorized -cne $true -or
        $authorization.original_private_source_reopen_authorized -cne $false -or
        $authorization.selected500_identity_print_authorized -cne $false -or
        $authorization.selected500_identity_commit_authorized -cne $false -or
        $authorization.model_fit_authorized -cne $false -or
        $authorization.historical_backtest_authorized -cne $false -or
        $authorization.a_to_q_execution_authorized -cne $false -or
        $authorization.forward_paper_authorized -cne $false -or
        $authorization.broker_access_authorized -cne $false -or
        $authorization.real_trading_authorized -cne $false) {
        throw 'BLOCK_AUTHORIZATION_OR_CALENDAR_SCOPE'
    }
    $localAppData = [Environment]::GetEnvironmentVariable('LOCALAPPDATA', 'Process')
    if ([string]::IsNullOrWhiteSpace($localAppData) -or
        -not [IO.Path]::IsPathRooted($localAppData)) { throw 'BLOCK_LOCALAPPDATA' }
    try {
        $expectedT1State = [IO.Path]::GetFullPath((Join-Path $localAppData 'stock-analyzer\private\v13-t1-exclusion-provenance\t1-exclusion-state.json'))
        $suppliedT1State = [IO.Path]::GetFullPath($PrivateT1State)
        $calendarFullPath = [IO.Path]::GetFullPath($CalendarLock)
        $outputFullPath = [IO.Path]::GetFullPath($OutputDirectory)
    }
    catch { throw 'BLOCK_PROTECTED_PATH' }
    if (-not [IO.Path]::IsPathRooted($PrivateT1State) -or
        -not [string]::Equals($suppliedT1State, $expectedT1State,
            [StringComparison]::OrdinalIgnoreCase)) { throw 'BLOCK_T1_STATE_IDENTITY' }

    function Assert-NoReparseAncestor([string] $protectedPath) {
        $cursor = $protectedPath
        while ($null -ne $cursor) {
            try { $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop }
            catch [System.Management.Automation.ItemNotFoundException] { $item = $null }
            catch { throw 'BLOCK_PROTECTED_PATH_TOPOLOGY' }
            if ($null -ne $item -and
                ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw 'BLOCK_PROTECTED_PATH_REPARSE'
            }
            $parent = [IO.Directory]::GetParent($cursor)
            $cursor = if ($null -eq $parent) { $null } else { $parent.FullName }
        }
    }
    foreach ($protectedPath in @($expectedT1State, $calendarFullPath, $outputFullPath)) {
        Assert-NoReparseAncestor $protectedPath
    }
    if (-not (Test-Path -LiteralPath $CalendarLock -PathType Leaf)) {
        throw 'BLOCK_CALENDAR_INPUT'
    }
    $calendarResolved = (Resolve-Path -LiteralPath $CalendarLock).Path
    if ($calendarResolved.StartsWith($repoRoot + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
        $calendarResolved -ceq $repoRoot) { throw 'BLOCK_CALENDAR_PATH_IN_REPOSITORY' }
    if (-not (Test-Path -LiteralPath $PrivateT1State -PathType Leaf) -or
        ((Test-Path -LiteralPath $OutputDirectory) -and
         -not (Test-Path -LiteralPath $OutputDirectory -PathType Container))) {
        throw 'BLOCK_INPUT_OR_OUTPUT_TOPOLOGY'
    }
    $privateResolved = (Resolve-Path -LiteralPath $PrivateT1State).Path
    $outputParent = Split-Path -Parent $outputFullPath
    if (-not (Test-Path -LiteralPath $outputParent -PathType Container)) { throw 'BLOCK_OUTPUT_PARENT' }
    $outputParentResolved = (Resolve-Path -LiteralPath $outputParent).Path
    foreach ($candidatePath in @($privateResolved, $outputFullPath, $outputParentResolved)) {
        if ($candidatePath.StartsWith($repoRoot + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
            $candidatePath -ceq $repoRoot) { throw 'BLOCK_PRIVATE_OR_RAW_PATH_IN_REPOSITORY' }
    }
    # Bind the reviewed Issue #128 successor implementation before any private read or public acquisition.
    function Assert-ReviewedSourceBlob([string] $relative, [string] $expectedBlob) {
        $path = Join-Path $repoRoot $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "BLOCK_REVIEWED_SOURCE_MISSING:$relative"
        }
        $headBlob = (& git rev-parse "HEAD:$relative").Trim()
        if ($LASTEXITCODE -ne 0 -or $headBlob -cne $expectedBlob) {
            throw "BLOCK_REVIEWED_SOURCE_TREE_MISMATCH:$relative"
        }
        $worktreeBlob = (& git hash-object --path $relative -- $path).Trim()
        if ($LASTEXITCODE -ne 0 -or $worktreeBlob -cne $expectedBlob) {
            throw "BLOCK_REVIEWED_SOURCE_WORKTREE_MISMATCH:$relative"
        }
    }
    Assert-ReviewedSourceBlob 'scripts/v13_public_data_lock_execute.py' '1eda70521328101b7d82408e28401d48d5ec8502'
    Assert-ReviewedSourceBlob 'src/v13_public_data_lock.py' '9ba735105a6bb6e944300812d425c04ac08df185'
    $pythonExe = Join-Path $repoRoot '.venv-real-execution\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw 'BLOCK_CANONICAL_ENVIRONMENT' }
    & $pythonExe scripts/check_current_protected_environment.py
    if ($LASTEXITCODE -ne 0) { throw 'BLOCK_CANONICAL_ENVIRONMENT' }
    & $pythonExe -m scripts.v13_xlsx_readiness
    if ($LASTEXITCODE -ne 0) { throw 'BLOCK_JPX_XLSX_READER' }
    & $pythonExe scripts/v13_public_data_lock_execute.py --preflight-calendar $CalendarLock $CalendarSha256
    if ($LASTEXITCODE -ne 0) { throw 'BLOCK_MASTER_CALENDAR_INPUT' }
    & $pythonExe scripts/v13_public_data_lock_execute.py --t1-state $PrivateT1State --v4-csv V4_UNIVERSE.csv --calendar-lock $CalendarLock --calendar-sha256 $CalendarSha256 --output $OutputDirectory --implementation-sha $ApprovedImplementationSha
    if ($LASTEXITCODE -ne 0) { throw 'BLOCK_PUBLIC_DATALOCK' }
}
